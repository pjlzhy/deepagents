package telemetry

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"time"

	"agentctl/pkg/domain"
)

// BuildSteps projects one ordered telemetry event stream into product-facing trace steps.
func BuildSteps(events []domain.TelemetryEventRecord) []domain.TelemetryStep {
	if len(events) == 0 {
		return nil
	}

	sorted := slices.Clone(events)
	slices.SortFunc(sorted, func(left, right domain.TelemetryEventRecord) int {
		switch {
		case left.Attempt != right.Attempt:
			if left.Attempt < right.Attempt {
				return -1
			}
			return 1
		case left.Seq != right.Seq:
			if left.Seq < right.Seq {
				return -1
			}
			return 1
		case !left.Timestamp.Equal(right.Timestamp):
			if left.Timestamp.Before(right.Timestamp) {
				return -1
			}
			return 1
		default:
			return strings.Compare(left.EventID, right.EventID)
		}
	})

	var (
		steps                  []*domain.TelemetryStep
		stepByID               = map[string]*domain.TelemetryStep{}
		activeNodeByTaskID     = map[string]*domain.TelemetryStep{}
		latestNodeByNamespace  = map[string]*domain.TelemetryStep{}
		latestModelByNamespace = map[string]*domain.TelemetryStep{}
		modelStepByID          = map[string]*domain.TelemetryStep{}
		toolStepByID           = map[string]*domain.TelemetryStep{}
		hitlStepByID           = map[string]*domain.TelemetryStep{}
		runStep                *domain.TelemetryStep
		reasoningIndexByStep   = map[string]map[string]int{}
		messageIndexByStep     = map[string]map[string]int{}
	)

	appendStep := func(step domain.TelemetryStep) *domain.TelemetryStep {
		step.Order = int32(len(steps))
		copy := step
		steps = append(steps, &copy)
		stepByID[copy.StepID] = &copy
		return &copy
	}

	ensureRunStep := func(event domain.TelemetryEventRecord) *domain.TelemetryStep {
		if runStep != nil {
			return runStep
		}
		runStep = appendStep(domain.TelemetryStep{
			StepID:    fmt.Sprintf("step:run:%s", event.RunID),
			RunID:     event.RunID,
			Kind:      domain.TelemetryStepKindRun,
			Title:     "run",
			Status:    domain.TelemetryStepStatusRunning,
			StartedAt: event.Timestamp,
			Depth:     0,
		})
		return runStep
	}

	closeOpenHitlSteps := func(status domain.TelemetryStepStatus, finishedAt time.Time) {
		for _, step := range hitlStepByID {
			if step.FinishedAt.IsZero() {
				step.FinishedAt = finishedAt
				step.Status = status
			}
		}
	}

	for _, event := range sorted {
		run := ensureRunStep(event)
		payload := decodeRawObject(event.Payload)
		metadata := decodeRawObject(event.Metadata)

		if event.EventType == "run_started" {
			run.Status = domain.TelemetryStepStatusRunning
			if run.StartedAt.IsZero() {
				run.StartedAt = event.Timestamp
			}
			appendRelatedEvent(run, event.EventID)
			continue
		}

		if event.EventType == "run_ended" {
			run.Status = domain.TelemetryStepStatusCompleted
			run.FinishedAt = event.Timestamp
			appendRelatedEvent(run, event.EventID)
			closeOpenHitlSteps(domain.TelemetryStepStatusCompleted, event.Timestamp)
			continue
		}

		if event.EventType == "run_canceled" {
			run.Status = domain.TelemetryStepStatusInterrupted
			run.FinishedAt = event.Timestamp
			run.Error = stringValue(payload["reason"])
			appendRelatedEvent(run, event.EventID)
			closeOpenHitlSteps(domain.TelemetryStepStatusInterrupted, event.Timestamp)
			continue
		}

		if event.EventType == "error" {
			run.Status = domain.TelemetryStepStatusFailed
			run.FinishedAt = event.Timestamp
			run.Error = firstNonEmpty(
				stringValue(payload["message"]),
				stringValue(payload["error"]),
			)
			appendRelatedEvent(run, event.EventID)
			closeOpenHitlSteps(domain.TelemetryStepStatusFailed, event.Timestamp)
			continue
		}

		if event.EventType != "interrupt" && event.EventType != "hitl_request" {
			closeOpenHitlSteps(domain.TelemetryStepStatusCompleted, event.Timestamp)
		}

		switch {
		case event.EventType == "task":
			stepID := fmt.Sprintf("step:node:%s", event.TaskID)
			step := stepByID[stepID]
			if step == nil {
				step = appendStep(domain.TelemetryStep{
					StepID:       stepID,
					RunID:        event.RunID,
					ParentStepID: parentNodeStepID(event.Namespace, latestNodeByNamespace, run.StepID),
					Kind:         domain.TelemetryStepKindNode,
					Title:        firstNonEmpty(stringValue(payload["name"]), event.NodeName, "node"),
					Namespace:    cloneStrings(event.Namespace),
					Status:       domain.TelemetryStepStatusRunning,
					StartedAt:    event.Timestamp,
					Depth:        int32(len(event.Namespace)),
					Step:         int32(numberValue(metadata["langgraph_step"], metadata["step"])),
					TaskID:       event.TaskID,
					Input:        rawJSONValue(payload["input"]),
					Triggers:     stringSliceValue(payload["triggers"]),
				})
			} else {
				step.ParentStepID = firstNonEmpty(
					step.ParentStepID,
					parentNodeStepID(event.Namespace, latestNodeByNamespace, run.StepID),
				)
				step.Title = firstNonEmpty(step.Title, stringValue(payload["name"]), event.NodeName, "node")
				step.Namespace = cloneStrings(event.Namespace)
				step.Depth = int32(len(event.Namespace))
				step.Status = domain.TelemetryStepStatusRunning
				step.FinishedAt = time.Time{}
				if step.StartedAt.IsZero() || event.Timestamp.Before(step.StartedAt) {
					step.StartedAt = event.Timestamp
				}
				if step.Step == 0 {
					step.Step = int32(numberValue(metadata["langgraph_step"], metadata["step"]))
				}
				if input := rawJSONValue(payload["input"]); len(input) > 0 {
					step.Input = input
				}
				if triggers := stringSliceValue(payload["triggers"]); len(triggers) > 0 {
					step.Triggers = triggers
				}
				step.TaskID = firstNonEmpty(step.TaskID, event.TaskID)
				step.Synthetic = false
			}
			appendRelatedEvent(step, event.EventID)
			if event.TaskID != "" {
				activeNodeByTaskID[event.TaskID] = step
			}
			latestNodeByNamespace[namespaceLabel(event.Namespace)] = step

		case event.EventType == "task_result":
			if step := activeNodeByTaskID[event.TaskID]; step != nil {
				step.FinishedAt = event.Timestamp
				step.Output = rawJSONValue(payload["result"])
				step.Error = firstNonEmpty(step.Error, stringValue(payload["error"]))
				if step.Error != "" {
					step.Status = domain.TelemetryStepStatusFailed
				} else if hasInterrupts(payload["interrupts"]) {
					step.Status = domain.TelemetryStepStatusInterrupted
				} else {
					step.Status = domain.TelemetryStepStatusCompleted
				}
				appendRelatedEvent(step, event.EventID)
				delete(activeNodeByTaskID, event.TaskID)
			}

		case event.EventType == "tool_call_start" || event.EventType == "tool_call_done" || event.EventType == "tool_result":
			step := ensureChildStep(
				toolStepByID,
				stepByID,
				steps,
				appendStep,
				event.ToolCallID,
				domain.TelemetryStep{
					StepID:       fmt.Sprintf("step:tool:%s", event.ToolCallID),
					RunID:        event.RunID,
					ParentStepID: parentActiveNodeStepID(event.Namespace, latestNodeByNamespace, activeNodeByTaskID, run.StepID),
					Kind:         domain.TelemetryStepKindTool,
					Title:        firstNonEmpty(stringValue(payload["tool_name"]), event.NodeName, "tool"),
					Namespace:    cloneStrings(event.Namespace),
					Status:       domain.TelemetryStepStatusRunning,
					StartedAt:    event.Timestamp,
					Depth:        int32(len(event.Namespace) + 1),
					ToolCallID:   event.ToolCallID,
				},
			)
			if step == nil {
				continue
			}
			appendRelatedEvent(step, event.EventID)
			if event.EventType == "tool_result" {
				step.FinishedAt = event.Timestamp
				step.Output = rawJSONValue(payload["payload"])
				if len(step.Output) == 0 {
					step.Output = rawJSONValue(payload["content"])
				}
				if boolValue(payload["is_error"]) {
					step.Status = domain.TelemetryStepStatusFailed
				} else {
					step.Status = domain.TelemetryStepStatusCompleted
				}
			}

		case event.EventType == "interrupt" || event.EventType == "hitl_request":
			step := ensureChildStep(
				hitlStepByID,
				stepByID,
				steps,
				appendStep,
				event.InterruptID,
				domain.TelemetryStep{
					StepID:       fmt.Sprintf("step:hitl:%s", event.InterruptID),
					RunID:        event.RunID,
					ParentStepID: parentActiveNodeStepID(event.Namespace, latestNodeByNamespace, activeNodeByTaskID, run.StepID),
					Kind:         domain.TelemetryStepKindHITL,
					Title:        "hitl",
					Namespace:    cloneStrings(event.Namespace),
					Status:       domain.TelemetryStepStatusInterrupted,
					StartedAt:    event.Timestamp,
					Depth:        int32(len(event.Namespace) + 1),
					InterruptID:  event.InterruptID,
					Input:        normalizeRaw(event.Payload),
				},
			)
			if step != nil {
				appendRelatedEvent(step, event.EventID)
			}

		case event.StreamMode == "messages":
			modelTitle := telemetryModelTitle(metadata)
			step := ensureChildStep(
				modelStepByID,
				stepByID,
				steps,
				appendStep,
				event.ModelCallID,
				domain.TelemetryStep{
					StepID:       fmt.Sprintf("step:model:%s", event.ModelCallID),
					RunID:        event.RunID,
					ParentStepID: parentActiveNodeStepID(event.Namespace, latestNodeByNamespace, activeNodeByTaskID, run.StepID),
					Kind:         domain.TelemetryStepKindModel,
					Title:        modelTitle,
					Namespace:    cloneStrings(event.Namespace),
					Status:       domain.TelemetryStepStatusRunning,
					StartedAt:    event.Timestamp,
					Depth:        int32(len(event.Namespace) + 1),
					ModelCallID:  event.ModelCallID,
					MessageID:    event.MessageID,
				},
			)
			if step == nil {
				continue
			}
			step.Title = firstNonEmpty(modelTitle, step.Title, "model")
			appendRelatedEvent(step, event.EventID)
			step.MessageID = firstNonEmpty(step.MessageID, event.MessageID)
			latestModelByNamespace[namespaceLabel(event.Namespace)] = step
			appendReasoning(step, payload, reasoningIndexByStep)
			appendModelToolCall(step, event, payload)
			if text := firstNonEmpty(stringValue(payload["text"]), stringValue(payload["content"])); text != "" &&
				(event.EventType == "text" || event.EventType == "text_done") {
				appendMessage(step, event, text, messageIndexByStep)
				if event.EventType == "text_done" {
					step.Output = rawJSONValue(text)
				}
			}
			if event.EventType == "text_done" {
				step.FinishedAt = event.Timestamp
				step.Status = domain.TelemetryStepStatusCompleted
			}

		default:
			step := ensureSyntheticNodeStep(
				event,
				latestNodeByNamespace,
				appendStep,
			)
			appendRelatedEvent(step, event.EventID)
			if event.EventType == "state_update" {
				step.Updates = append(step.Updates, normalizeRaw(event.Payload))
				backfillModelStepFromStateUpdate(
					payload,
					event.Namespace,
					latestModelByNamespace,
				)
			}
			if event.EventType == "custom" {
				step.Custom = append(step.Custom, normalizeRaw(event.Payload))
			}
		}
	}

	for _, step := range steps {
		if step.FinishedAt.IsZero() {
			switch step.Kind {
			case domain.TelemetryStepKindRun:
				if runStep != nil {
					step.Status = runStep.Status
					step.FinishedAt = runStep.FinishedAt
				}
			case domain.TelemetryStepKindModel, domain.TelemetryStepKindTool, domain.TelemetryStepKindNode:
				if runStep != nil && !runStep.FinishedAt.IsZero() {
					step.FinishedAt = runStep.FinishedAt
					switch runStep.Status {
					case domain.TelemetryStepStatusFailed:
						step.Status = domain.TelemetryStepStatusFailed
					case domain.TelemetryStepStatusInterrupted:
						step.Status = domain.TelemetryStepStatusInterrupted
					default:
						if step.Status == domain.TelemetryStepStatusRunning {
							step.Status = domain.TelemetryStepStatusCompleted
						}
					}
				} else if step.Status == domain.TelemetryStepStatusRunning {
					step.Status = domain.TelemetryStepStatusObserved
				}
			case domain.TelemetryStepKindHITL:
				if step.Status == domain.TelemetryStepStatusRunning {
					step.Status = domain.TelemetryStepStatusInterrupted
				}
			}
		}
	}

	projected := make([]domain.TelemetryStep, 0, len(steps))
	for _, step := range steps {
		projected = append(projected, *step)
	}
	return projected
}

func ensureChildStep(
	index map[string]*domain.TelemetryStep,
	_ map[string]*domain.TelemetryStep,
	_ []*domain.TelemetryStep,
	appendStep func(domain.TelemetryStep) *domain.TelemetryStep,
	key string,
	template domain.TelemetryStep,
) *domain.TelemetryStep {
	if key == "" {
		return nil
	}
	if existing := index[key]; existing != nil {
		return existing
	}
	created := appendStep(template)
	index[key] = created
	return created
}

func ensureSyntheticNodeStep(
	event domain.TelemetryEventRecord,
	latestNodeByNamespace map[string]*domain.TelemetryStep,
	appendStep func(domain.TelemetryStep) *domain.TelemetryStep,
) *domain.TelemetryStep {
	key := namespaceLabel(event.Namespace)
	if existing := latestNodeByNamespace[key]; existing != nil {
		return existing
	}
	created := appendStep(domain.TelemetryStep{
		StepID:    fmt.Sprintf("step:node:synthetic:%s:%s", key, event.NodeName),
		RunID:     event.RunID,
		Kind:      domain.TelemetryStepKindNode,
		Title:     firstNonEmpty(event.NodeName, "root"),
		Namespace: cloneStrings(event.Namespace),
		Status:    domain.TelemetryStepStatusObserved,
		StartedAt: event.Timestamp,
		Depth:     int32(len(event.Namespace)),
		Synthetic: true,
	})
	latestNodeByNamespace[key] = created
	return created
}

func appendRelatedEvent(step *domain.TelemetryStep, eventID string) {
	if step == nil || eventID == "" {
		return
	}
	step.EventCount += 1
}

func appendReasoning(
	step *domain.TelemetryStep,
	payload map[string]any,
	indexByStep map[string]map[string]int,
) {
	if step == nil {
		return
	}
	blockID := firstNonEmpty(stringValue(payload["id"]), fmt.Sprintf("%v", payload["index"]))
	if len(step.Reasoning) == 0 && stringValue(payload["encrypted_content"]) != "" {
		step.ReasoningEncrypted = true
	}
	if summary, ok := payload["summary"].([]any); ok {
		for _, item := range summary {
			record, ok := item.(map[string]any)
			if !ok {
				continue
			}
			text := stringValue(record["text"])
			if text == "" {
				continue
			}
			key := fmt.Sprintf("summary:%s:%v", blockID, record["index"])
			appendReasoningText(step, key, text, indexByStep)
		}
		return
	}
	if text := stringValue(payload["reasoning"]); text != "" {
		appendReasoningText(step, "reasoning:"+blockID, text, indexByStep)
	}
}

func appendModelToolCall(
	step *domain.TelemetryStep,
	event domain.TelemetryEventRecord,
	payload map[string]any,
) {
	if step == nil {
		return
	}
	switch event.EventType {
	case "tool_call", "tool_call_chunk", "tool_call_start", "function_call", "function_call_chunk":
	default:
		return
	}

	name := firstNonEmpty(stringValue(payload["tool_name"]), stringValue(payload["name"]))
	if name == "" {
		return
	}
	appendUniqueString(&step.ToolCalls, name)
}

func appendReasoningText(
	step *domain.TelemetryStep,
	key string,
	text string,
	indexByStep map[string]map[string]int,
) {
	if step == nil || text == "" {
		return
	}
	index := messageOrReasoningIndex(indexByStep, step.StepID)
	if existing, ok := index[key]; ok {
		step.Reasoning[existing] += text
		return
	}
	index[key] = len(step.Reasoning)
	step.Reasoning = append(step.Reasoning, text)
}

func appendMessage(
	step *domain.TelemetryStep,
	event domain.TelemetryEventRecord,
	text string,
	indexByStep map[string]map[string]int,
) {
	if step == nil || text == "" {
		return
	}
	key := firstNonEmpty(event.MessageID, event.ModelCallID, event.EventType)
	index := messageOrReasoningIndex(indexByStep, step.StepID)
	if existing, ok := index[key]; ok {
		if event.EventType == "text_done" {
			step.Messages[existing] = text
			return
		}
		step.Messages[existing] += text
		return
	}
	index[key] = len(step.Messages)
	step.Messages = append(step.Messages, text)
}

func appendUniqueString(target *[]string, value string) {
	if target == nil || value == "" {
		return
	}
	for _, existing := range *target {
		if existing == value {
			return
		}
	}
	*target = append(*target, value)
}

func telemetryModelTitle(metadata map[string]any) string {
	provider := stringValue(metadata["ls_provider"])
	modelName := firstNonEmpty(
		stringValue(metadata["ls_model_name"]),
		stringValue(metadata["model_name"]),
	)
	switch {
	case provider != "" && modelName != "":
		return provider + "/" + modelName
	case modelName != "":
		return modelName
	default:
		return "model"
	}
}

func backfillModelStepFromStateUpdate(
	payload map[string]any,
	namespace []string,
	latestModelByNamespace map[string]*domain.TelemetryStep,
) {
	if len(payload) == 0 {
		return
	}
	step := latestModelByNamespace[namespaceLabel(namespace)]
	if step == nil {
		return
	}

	container := stateUpdateMessageContainer(payload)
	if len(container) == 0 {
		return
	}

	messagesValue, ok := container["messages"].([]any)
	if !ok || len(messagesValue) == 0 {
		return
	}

	reasoning, reasoningEncrypted, text, toolCalls := extractModelMessageSummary(messagesValue)
	if len(reasoning) > 0 {
		step.Reasoning = reasoning
		step.ReasoningEncrypted = false
	} else if reasoningEncrypted {
		step.ReasoningEncrypted = true
	}
	if text != "" {
		step.Messages = []string{text}
		step.Output = rawJSONValue(text)
	}
	if len(toolCalls) > 0 {
		step.ToolCalls = toolCalls
	}
}

func stateUpdateMessageContainer(payload map[string]any) map[string]any {
	if len(payload) == 0 {
		return nil
	}
	for _, value := range payload {
		record, ok := value.(map[string]any)
		if !ok {
			continue
		}
		if _, hasMessages := record["messages"]; hasMessages {
			return record
		}
	}
	return nil
}

func extractModelMessageSummary(messages []any) ([]string, bool, string, []string) {
	var (
		reasoning          []string
		reasoningEncrypted bool
		textParts          []string
		toolCalls          []string
	)

	for _, rawMessage := range messages {
		record, ok := rawMessage.(map[string]any)
		if !ok {
			continue
		}
		content, ok := record["content"].([]any)
		if !ok {
			continue
		}

		reasoning = reasoning[:0]
		reasoningEncrypted = false
		textParts = textParts[:0]
		toolCalls = toolCalls[:0]

		for _, rawPart := range content {
			part, ok := rawPart.(map[string]any)
			if !ok {
				continue
			}
			switch stringValue(part["type"]) {
			case "reasoning":
				if summaries, ok := part["summary"].([]any); ok {
					for _, rawSummary := range summaries {
						summary, ok := rawSummary.(map[string]any)
						if !ok {
							continue
						}
						text := stringValue(summary["text"])
						if text == "" {
							continue
						}
						reasoning = append(reasoning, text)
					}
				}
				if len(reasoning) == 0 && stringValue(part["encrypted_content"]) != "" {
					reasoningEncrypted = true
				}
			case "text", "output_text":
				if text := stringValue(part["text"]); text != "" {
					textParts = append(textParts, text)
				}
			case "function_call", "tool_call":
				if name := firstNonEmpty(stringValue(part["name"]), stringValue(part["tool_name"])); name != "" {
					appendUniqueString(&toolCalls, name)
				}
			}
		}
	}

	return reasoning, reasoningEncrypted, strings.TrimSpace(strings.Join(textParts, "")), toolCalls
}

func messageOrReasoningIndex(indexByStep map[string]map[string]int, stepID string) map[string]int {
	if existing := indexByStep[stepID]; existing != nil {
		return existing
	}
	created := map[string]int{}
	indexByStep[stepID] = created
	return created
}

func decodeRawObject(raw json.RawMessage) map[string]any {
	if len(raw) == 0 || string(raw) == "null" {
		return nil
	}
	var value map[string]any
	if err := json.Unmarshal(raw, &value); err != nil {
		return nil
	}
	return value
}

func normalizeRaw(raw json.RawMessage) json.RawMessage {
	if len(raw) == 0 {
		return json.RawMessage("null")
	}
	return raw
}

func rawJSONValue(value any) json.RawMessage {
	if value == nil {
		return nil
	}
	switch typed := value.(type) {
	case json.RawMessage:
		return normalizeRaw(typed)
	case string:
		payload, err := json.Marshal(typed)
		if err != nil {
			return nil
		}
		return payload
	default:
		payload, err := json.Marshal(value)
		if err != nil {
			return nil
		}
		return payload
	}
}

func namespaceLabel(namespace []string) string {
	if len(namespace) == 0 {
		return "root"
	}
	return strings.Join(namespace, " / ")
}

func parentNodeStepID(
	namespace []string,
	latestNodeByNamespace map[string]*domain.TelemetryStep,
	runStepID string,
) string {
	for index := len(namespace) - 1; index >= 1; index -= 1 {
		key := namespaceLabel(namespace[:index])
		if step := latestNodeByNamespace[key]; step != nil {
			return step.StepID
		}
	}
	return runStepID
}

func parentActiveNodeStepID(
	namespace []string,
	latestNodeByNamespace map[string]*domain.TelemetryStep,
	activeNodeByTaskID map[string]*domain.TelemetryStep,
	runStepID string,
) string {
	if step := latestNodeByNamespace[namespaceLabel(namespace)]; step != nil {
		return step.StepID
	}
	return parentNodeStepID(namespace, latestNodeByNamespace, runStepID)
}

func cloneStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	cloned := make([]string, len(values))
	copy(cloned, values)
	return cloned
}

func stringValue(value any) string {
	typed, ok := value.(string)
	if !ok {
		return ""
	}
	return strings.TrimSpace(typed)
}

func boolValue(value any) bool {
	typed, ok := value.(bool)
	return ok && typed
}

func numberValue(values ...any) float64 {
	for _, value := range values {
		switch typed := value.(type) {
		case float64:
			return typed
		case int:
			return float64(typed)
		case int32:
			return float64(typed)
		case int64:
			return float64(typed)
		}
	}
	return 0
}

func stringSliceValue(value any) []string {
	items, ok := value.([]any)
	if !ok {
		return nil
	}
	result := make([]string, 0, len(items))
	for _, item := range items {
		text := stringValue(item)
		if text == "" {
			continue
		}
		result = append(result, text)
	}
	return result
}

func hasInterrupts(value any) bool {
	items, ok := value.([]any)
	return ok && len(items) > 0
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}
