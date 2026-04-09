package telemetry

import (
	"encoding/json"
	"testing"
	"time"

	"agentctl/pkg/domain"
)

func TestBuildStepsProjectsNodeModelToolAndHitlSteps(t *testing.T) {
	events := []domain.TelemetryEventRecord{
		{
			EventID:    "run-1:1:1",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        1,
			Timestamp:  time.Unix(1710000000, 0).UTC(),
			StreamMode: "lifecycle",
			EventType:  "run_started",
			NodeName:   "run",
		},
		{
			EventID:    "run-1:1:2",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        2,
			Timestamp:  time.Unix(1710000001, 0).UTC(),
			Namespace:  []string{"task:research"},
			StreamMode: "debug",
			EventType:  "task",
			NodeName:   "research",
			TaskID:     "task-1",
			Metadata:   json.RawMessage(`{"step":2}`),
			Payload:    json.RawMessage(`{"id":"task-1","name":"research","input":{"question":"why"}}`),
		},
		{
			EventID:     "run-1:1:3",
			RunID:       "run-1",
			AgentName:   "assistant",
			Attempt:     1,
			Seq:         3,
			Timestamp:   time.Unix(1710000002, 0).UTC(),
			Namespace:   []string{"task:research"},
			StreamMode:  "messages",
			EventType:   "reasoning",
			NodeName:    "planner",
			ModelCallID: "msg-1",
			MessageID:   "msg-1",
			Metadata:    json.RawMessage(`{"ls_provider":"openai","ls_model_name":"gpt-5.4"}`),
			Payload:     json.RawMessage(`{"summary":[{"text":"thinking..."}]}`),
		},
		{
			EventID:     "run-1:1:4",
			RunID:       "run-1",
			AgentName:   "assistant",
			Attempt:     1,
			Seq:         4,
			Timestamp:   time.Unix(1710000003, 0).UTC(),
			Namespace:   []string{"task:research"},
			StreamMode:  "messages",
			EventType:   "text_done",
			NodeName:    "planner",
			ModelCallID: "msg-1",
			MessageID:   "msg-1",
			Metadata:    json.RawMessage(`{"ls_provider":"openai","ls_model_name":"gpt-5.4"}`),
			Payload:     json.RawMessage(`{"text":"done"}`),
		},
		{
			EventID:    "run-1:1:5",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        5,
			Timestamp:  time.Unix(1710000004, 0).UTC(),
			Namespace:  []string{"task:research"},
			StreamMode: "messages",
			EventType:  "tool_call_start",
			NodeName:   "research",
			ToolCallID: "tool-1",
			Payload:    json.RawMessage(`{"tool_name":"search","tool_call_id":"tool-1"}`),
		},
		{
			EventID:    "run-1:1:6",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        6,
			Timestamp:  time.Unix(1710000005, 0).UTC(),
			Namespace:  []string{"task:research"},
			StreamMode: "messages",
			EventType:  "tool_result",
			NodeName:   "research",
			ToolCallID: "tool-1",
			Payload:    json.RawMessage(`{"tool_call_id":"tool-1","content":"ok","is_error":false}`),
		},
		{
			EventID:     "run-1:1:7",
			RunID:       "run-1",
			AgentName:   "assistant",
			Attempt:     1,
			Seq:         7,
			Timestamp:   time.Unix(1710000006, 0).UTC(),
			Namespace:   []string{"task:research"},
			StreamMode:  "updates",
			EventType:   "interrupt",
			NodeName:    "research",
			InterruptID: "interrupt-1",
			Payload:     json.RawMessage(`{"interrupt_id":"interrupt-1"}`),
		},
		{
			EventID:    "run-1:1:8",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        8,
			Timestamp:  time.Unix(1710000007, 0).UTC(),
			Namespace:  []string{"task:research"},
			StreamMode: "debug",
			EventType:  "task_result",
			NodeName:   "research",
			TaskID:     "task-1",
			Payload:    json.RawMessage(`{"id":"task-1","result":{"answer":"ok"}}`),
		},
		{
			EventID:    "run-1:1:9",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        9,
			Timestamp:  time.Unix(1710000008, 0).UTC(),
			StreamMode: "lifecycle",
			EventType:  "run_ended",
			NodeName:   "run",
		},
	}

	steps := BuildSteps(events)
	if len(steps) < 5 {
		t.Fatalf("expected at least 5 steps, got %d", len(steps))
	}

	index := map[string]domain.TelemetryStep{}
	for _, step := range steps {
		index[step.StepID] = step
	}

	run := index["step:run:run-1"]
	if run.Kind != domain.TelemetryStepKindRun || run.Status != domain.TelemetryStepStatusCompleted {
		t.Fatalf("unexpected run step: %#v", run)
	}

	node := index["step:node:task-1"]
	if node.Kind != domain.TelemetryStepKindNode || node.Status != domain.TelemetryStepStatusCompleted {
		t.Fatalf("unexpected node step: %#v", node)
	}
	if node.ParentStepID != "step:run:run-1" {
		t.Fatalf("unexpected node parent: %#v", node)
	}
	if len(node.Reasoning) != 0 || len(node.Messages) != 0 {
		t.Fatalf("expected node step to exclude model content, got %#v", node)
	}

	model := index["step:model:msg-1"]
	if model.Kind != domain.TelemetryStepKindModel || model.Status != domain.TelemetryStepStatusCompleted {
		t.Fatalf("unexpected model step: %#v", model)
	}
	if model.Title != "openai/gpt-5.4" {
		t.Fatalf("unexpected model title: %#v", model)
	}
	if len(model.Reasoning) != 1 || model.Messages[len(model.Messages)-1] != "done" {
		t.Fatalf("unexpected model content: %#v", model)
	}

	tool := index["step:tool:tool-1"]
	if tool.Kind != domain.TelemetryStepKindTool || tool.Status != domain.TelemetryStepStatusCompleted {
		t.Fatalf("unexpected tool step: %#v", tool)
	}

	hitl := index["step:hitl:interrupt-1"]
	if hitl.Kind != domain.TelemetryStepKindHITL {
		t.Fatalf("unexpected hitl step: %#v", hitl)
	}
}

func TestBuildStepsDeduplicatesRepeatedTaskStarts(t *testing.T) {
	events := []domain.TelemetryEventRecord{
		{
			EventID:    "run-2:1:1",
			RunID:      "run-2",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        1,
			Timestamp:  time.Unix(1710001000, 0).UTC(),
			StreamMode: "lifecycle",
			EventType:  "run_started",
			NodeName:   "run",
		},
		{
			EventID:    "run-2:1:2",
			RunID:      "run-2",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        2,
			Timestamp:  time.Unix(1710001001, 0).UTC(),
			Namespace:  []string{"task:worker"},
			StreamMode: "debug",
			EventType:  "task",
			NodeName:   "worker",
			TaskID:     "task-repeat",
			Payload:    json.RawMessage(`{"id":"task-repeat","name":"worker","input":{"goal":"first"}}`),
		},
		{
			EventID:    "run-2:1:3",
			RunID:      "run-2",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        3,
			Timestamp:  time.Unix(1710001002, 0).UTC(),
			Namespace:  []string{"task:worker"},
			StreamMode: "debug",
			EventType:  "task",
			NodeName:   "worker",
			TaskID:     "task-repeat",
			Payload:    json.RawMessage(`{"id":"task-repeat","name":"worker","input":{"goal":"second"}}`),
		},
		{
			EventID:    "run-2:1:4",
			RunID:      "run-2",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        4,
			Timestamp:  time.Unix(1710001003, 0).UTC(),
			Namespace:  []string{"task:worker"},
			StreamMode: "debug",
			EventType:  "task_result",
			NodeName:   "worker",
			TaskID:     "task-repeat",
			Payload:    json.RawMessage(`{"id":"task-repeat","result":{"answer":"ok"}}`),
		},
		{
			EventID:    "run-2:1:5",
			RunID:      "run-2",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        5,
			Timestamp:  time.Unix(1710001004, 0).UTC(),
			StreamMode: "lifecycle",
			EventType:  "run_ended",
			NodeName:   "run",
		},
	}

	steps := BuildSteps(events)

	nodeCount := 0
	var node domain.TelemetryStep
	for _, step := range steps {
		if step.StepID == "step:node:task-repeat" {
			nodeCount++
			node = step
		}
	}

	if nodeCount != 1 {
		t.Fatalf("expected one deduplicated node step, got %d in %#v", nodeCount, steps)
	}
	if node.Status != domain.TelemetryStepStatusCompleted {
		t.Fatalf("unexpected node status: %#v", node)
	}
	if string(node.Input) != `{"goal":"second"}` {
		t.Fatalf("expected latest task input to win, got %s", node.Input)
	}
}

func TestBuildStepsMarksEncryptedReasoningAndFunctionCallsOnModelStep(t *testing.T) {
	events := []domain.TelemetryEventRecord{
		{
			EventID:    "run-3:1:1",
			RunID:      "run-3",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        1,
			Timestamp:  time.Unix(1710002000, 0).UTC(),
			StreamMode: "lifecycle",
			EventType:  "run_started",
			NodeName:   "run",
		},
		{
			EventID:    "run-3:1:2",
			RunID:      "run-3",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        2,
			Timestamp:  time.Unix(1710002001, 0).UTC(),
			Namespace:  []string{"task:model"},
			StreamMode: "debug",
			EventType:  "task",
			NodeName:   "model",
			TaskID:     "task-model",
			Payload:    json.RawMessage(`{"id":"task-model","name":"model"}`),
		},
		{
			EventID:     "run-3:1:3",
			RunID:       "run-3",
			AgentName:   "assistant",
			Attempt:     1,
			Seq:         3,
			Timestamp:   time.Unix(1710002002, 0).UTC(),
			Namespace:   []string{"task:model"},
			StreamMode:  "messages",
			EventType:   "reasoning",
			NodeName:    "model",
			ModelCallID: "model-call-1",
			MessageID:   "rs-1",
			Payload:     json.RawMessage(`{"id":"rs-1","encrypted_content":"ciphertext","summary":[]}`),
		},
		{
			EventID:     "run-3:1:4",
			RunID:       "run-3",
			AgentName:   "assistant",
			Attempt:     1,
			Seq:         4,
			Timestamp:   time.Unix(1710002003, 0).UTC(),
			Namespace:   []string{"task:model"},
			StreamMode:  "messages",
			EventType:   "function_call",
			NodeName:    "model",
			ModelCallID: "model-call-1",
			Payload:     json.RawMessage(`{"name":"execute","arguments":"{\"command\":\"pwd\"}"}`),
		},
		{
			EventID:    "run-3:1:5",
			RunID:      "run-3",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        5,
			Timestamp:  time.Unix(1710002004, 0).UTC(),
			Namespace:  []string{"task:model"},
			StreamMode: "debug",
			EventType:  "task_result",
			NodeName:   "model",
			TaskID:     "task-model",
			Payload:    json.RawMessage(`{"id":"task-model","result":{}}`),
		},
		{
			EventID:    "run-3:1:6",
			RunID:      "run-3",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        6,
			Timestamp:  time.Unix(1710002005, 0).UTC(),
			StreamMode: "lifecycle",
			EventType:  "run_ended",
			NodeName:   "run",
		},
	}

	steps := BuildSteps(events)

	index := map[string]domain.TelemetryStep{}
	for _, step := range steps {
		index[step.StepID] = step
	}

	model := index["step:model:model-call-1"]
	if model.Kind != domain.TelemetryStepKindModel {
		t.Fatalf("unexpected model step: %#v", model)
	}
	if !model.ReasoningEncrypted {
		t.Fatalf("expected encrypted reasoning marker, got %#v", model)
	}
	if len(model.Reasoning) != 0 {
		t.Fatalf("expected no visible reasoning text, got %#v", model.Reasoning)
	}
	if len(model.ToolCalls) != 1 || model.ToolCalls[0] != "execute" {
		t.Fatalf("expected function call summary, got %#v", model.ToolCalls)
	}
}

func TestBuildStepsBackfillsModelReasoningFromStateUpdateSnapshot(t *testing.T) {
	events := []domain.TelemetryEventRecord{
		{
			EventID:    "run-4:1:1",
			RunID:      "run-4",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        1,
			Timestamp:  time.Unix(1710003000, 0).UTC(),
			StreamMode: "lifecycle",
			EventType:  "run_started",
			NodeName:   "run",
		},
		{
			EventID:    "run-4:1:2",
			RunID:      "run-4",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        2,
			Timestamp:  time.Unix(1710003001, 0).UTC(),
			Namespace:  []string{"task:model"},
			StreamMode: "debug",
			EventType:  "task",
			NodeName:   "model",
			TaskID:     "task-model",
			Payload:    json.RawMessage(`{"id":"task-model","name":"model"}`),
		},
		{
			EventID:     "run-4:1:3",
			RunID:       "run-4",
			AgentName:   "assistant",
			Attempt:     1,
			Seq:         3,
			Timestamp:   time.Unix(1710003002, 0).UTC(),
			Namespace:   []string{"task:model"},
			StreamMode:  "messages",
			EventType:   "reasoning",
			NodeName:    "model",
			ModelCallID: "model-call-2",
			MessageID:   "rs-2",
			Payload:     json.RawMessage(`{"id":"rs-2","summary":[{"index":0,"text":"I"},{"index":0,"text":"need"},{"index":0,"text":"to"}]}`),
		},
		{
			EventID:    "run-4:1:4",
			RunID:      "run-4",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        4,
			Timestamp:  time.Unix(1710003003, 0).UTC(),
			Namespace:  []string{"task:model"},
			StreamMode: "updates",
			EventType:  "state_update",
			NodeName:   "root",
			Payload: json.RawMessage(`{
				"model": {
					"messages": [
						{
							"content": [
								{
									"type": "reasoning",
									"summary": [
										{
											"index": 0,
											"text": "I need to provide an answer in Chinese."
										}
									]
								},
								{
									"type": "text",
									"text": "最终答案"
								}
							]
						}
					]
				}
			}`),
		},
		{
			EventID:    "run-4:1:5",
			RunID:      "run-4",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        5,
			Timestamp:  time.Unix(1710003004, 0).UTC(),
			Namespace:  []string{"task:model"},
			StreamMode: "debug",
			EventType:  "task_result",
			NodeName:   "model",
			TaskID:     "task-model",
			Payload:    json.RawMessage(`{"id":"task-model","result":{}}`),
		},
		{
			EventID:    "run-4:1:6",
			RunID:      "run-4",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        6,
			Timestamp:  time.Unix(1710003005, 0).UTC(),
			StreamMode: "lifecycle",
			EventType:  "run_ended",
			NodeName:   "run",
		},
	}

	steps := BuildSteps(events)
	index := map[string]domain.TelemetryStep{}
	for _, step := range steps {
		index[step.StepID] = step
	}

	model := index["step:model:model-call-2"]
	if len(model.Reasoning) != 1 || model.Reasoning[0] != "I need to provide an answer in Chinese." {
		t.Fatalf("expected snapshot reasoning text, got %#v", model.Reasoning)
	}
	if len(model.Messages) != 1 || model.Messages[0] != "最终答案" {
		t.Fatalf("expected snapshot text message, got %#v", model.Messages)
	}
}
