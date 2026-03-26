package runtimeclient

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"agentctl/pkg/domain"
	runtimev1 "agentctl/pkg/proto"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/structpb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func runtimeAgentSpecToProto(spec domain.RuntimeAgentSpec) (*runtimev1.SyncAgentSpecRequest, error) {
	model, err := modelSpecString(spec.Model, true)
	if err != nil {
		return nil, fmt.Errorf("build agent model string: %w", err)
	}

	request := &runtimev1.SyncAgentSpecRequest{
		Name:        spec.Name,
		Version:     spec.Version,
		Description: spec.Description,
		Tags:        cloneStrings(spec.Tags),
		Model:       model,
		InterruptOn: cloneStrings(spec.InterruptOn),
		McpServers:  mcpConfigsToProto(spec.MCPServers),
		ModelConfig: modelConfigToProto(spec.Model),
	}

	if prompt := promptSpecToProto(spec.Prompt); prompt != nil {
		request.Prompt = prompt
	}
	if sandbox := sandboxSpecToProto(spec.Sandbox); sandbox != nil {
		request.Sandbox = sandbox
	}
	if skills := skillsToProto(spec.Skills); len(skills) > 0 {
		request.Skills = skills
	}
	if subagents, err := subagentsToProto(spec.Subagents); err != nil {
		return nil, err
	} else if len(subagents) > 0 {
		request.Subagents = subagents
	}

	return request, nil
}

func promptSpecToProto(spec domain.PromptSpec) *runtimev1.PromptSpec {
	if strings.TrimSpace(spec.System) == "" {
		return nil
	}
	return &runtimev1.PromptSpec{
		System: spec.System,
	}
}

func skillsToProto(skills []domain.Skill) []*runtimev1.SkillContent {
	items := make([]*runtimev1.SkillContent, 0, len(skills))
	for _, skill := range skills {
		item := &runtimev1.SkillContent{
			Name:    skill.Name,
			Content: skill.Content,
			Files:   skillFilesToProto(skill.Files),
		}
		items = append(items, item)
	}
	return items
}

func skillFilesToProto(files []domain.SkillFile) []*runtimev1.SkillFile {
	items := make([]*runtimev1.SkillFile, 0, len(files))
	for _, file := range files {
		items = append(items, &runtimev1.SkillFile{
			Path:    file.Path,
			Content: file.Content,
		})
	}
	return items
}

func mcpConfigsToProto(configs []domain.MCPConfig) []*runtimev1.McpServerConfig {
	items := make([]*runtimev1.McpServerConfig, 0, len(configs))
	for _, config := range configs {
		items = append(items, &runtimev1.McpServerConfig{
			Name:        config.Name,
			Command:     config.Command,
			Args:        cloneStrings(config.Args),
			Env:         cloneStringMap(config.Env),
			Transport:   config.Transport,
			Description: config.Description,
		})
	}
	return items
}

func subagentsToProto(subagents []domain.SubagentSpec) ([]*runtimev1.SubagentSpec, error) {
	items := make([]*runtimev1.SubagentSpec, 0, len(subagents))
	for _, subagent := range subagents {
		model, err := modelSpecString(subagent.Model, false)
		if err != nil {
			return nil, fmt.Errorf("build subagent %q model string: %w", subagent.Name, err)
		}
		items = append(items, &runtimev1.SubagentSpec{
			Name:         subagent.Name,
			Description:  subagent.Description,
			SystemPrompt: subagent.SystemPrompt,
			Model:        model,
		})
	}
	return items, nil
}

func sandboxSpecToProto(spec domain.SandboxSpec) *runtimev1.SandboxSpec {
	if strings.TrimSpace(spec.Image) == "" && len(spec.Resources) == 0 && len(spec.Init) == 0 {
		return nil
	}
	return &runtimev1.SandboxSpec{
		Image:     spec.Image,
		Resources: cloneStringMap(spec.Resources),
		Init:      cloneStrings(spec.Init),
	}
}

func modelConfigToProto(spec domain.ModelSpec) *runtimev1.ModelConfig {
	if strings.TrimSpace(spec.Provider) == "" && strings.TrimSpace(spec.Model) == "" {
		return nil
	}
	return &runtimev1.ModelConfig{
		Provider:    spec.Provider,
		Model:       spec.Model,
		BaseUrl:     spec.BaseURL,
		ApiKeyEnv:   spec.APIKeyEnv,
		ExtraParams: cloneStringMap(spec.ExtraParams),
	}
}

func modelSpecString(spec domain.ModelSpec, required bool) (string, error) {
	provider := strings.TrimSpace(spec.Provider)
	model := strings.TrimSpace(spec.Model)

	if provider == "" && model == "" && !required {
		return "", nil
	}
	if provider == "" || model == "" {
		return "", errors.New("model spec must include both provider and model")
	}
	return provider + ":" + model, nil
}

func runRequestToProto(req domain.RunRequest) *runtimev1.RunRequest {
	return &runtimev1.RunRequest{
		AgentName: req.AgentName,
		Message:   req.Message,
		ThreadId:  req.ThreadID,
		Metadata:  cloneStringMap(req.Metadata),
	}
}

func sessionSummaryFromProto(
	summary *runtimev1.SessionSummary,
	checkpointCount int32,
) domain.SessionSummary {
	if summary == nil {
		return domain.SessionSummary{}
	}

	return domain.SessionSummary{
		ThreadID:           summary.GetThreadId(),
		AgentName:          summary.GetAgentName(),
		LatestCheckpointID: summary.GetLatestCheckpointId(),
		MessageCount:       summary.GetMessageCount(),
		CheckpointCount:    checkpointCount,
		InitialPrompt:      summary.GetInitialPrompt(),
		HistoryMode:        sessionHistoryModeFromProto(summary.GetHistoryMode()),
		AgentStatus:        observedRuntimeStateFromProto(summary.GetAgentStatus()),
		UpdatedAt:          timestampFromProto(summary.GetUpdatedAt()),
	}
}

func sessionMessageFromProto(
	message *runtimev1.SessionMessage,
	resolvedCheckpointID string,
) domain.SessionMessage {
	if message == nil {
		return domain.SessionMessage{}
	}

	text := message.GetText()
	return domain.SessionMessage{
		Index:        message.GetIndex(),
		CheckpointID: resolvedCheckpointID,
		Role:         sessionMessageRoleFromProto(message.GetRole()),
		Text:         text,
		Content:      text,
		ToolCallID:   message.GetToolCallId(),
		ToolName:     message.GetToolName(),
		IsError:      message.GetIsError(),
		Raw:          structToRawJSON(message.GetRaw()),
	}
}

func sessionMessagePageFromProto(response *runtimev1.GetSessionMessagesResponse) domain.SessionMessagePage {
	if response == nil {
		return domain.SessionMessagePage{}
	}

	messages := make([]domain.SessionMessage, 0, len(response.GetMessages()))
	for _, message := range response.GetMessages() {
		messages = append(messages, sessionMessageFromProto(message, response.GetResolvedCheckpointId()))
	}

	return domain.SessionMessagePage{
		ThreadID:             response.GetThreadId(),
		ResolvedCheckpointID: response.GetResolvedCheckpointId(),
		ActualMode:           sessionHistoryModeFromProto(response.GetActualMode()),
		TotalMessageCount:    response.GetTotalMessageCount(),
		Messages:             messages,
		NextPageToken:        response.GetNextPageToken(),
	}
}

func agentEventFromProto(event *runtimev1.AgentEvent) AgentEvent {
	if event == nil {
		return AgentEvent{}
	}

	mapped := AgentEvent{
		RunID:     event.GetRunId(),
		AgentName: event.GetAgentName(),
		Timestamp: timestampFromProto(event.GetTimestamp()),
	}

	switch payload := event.GetPayload().(type) {
	case *runtimev1.AgentEvent_RunStarted:
		mapped.Type = AgentEventTypeRunStarted
		mapped.ThreadID = payload.RunStarted.GetThreadId()
	case *runtimev1.AgentEvent_TextDelta:
		mapped.Type = AgentEventTypeTextDelta
		mapped.Text = payload.TextDelta.GetText()
	case *runtimev1.AgentEvent_TextDone:
		mapped.Type = AgentEventTypeTextDone
		mapped.Text = payload.TextDone.GetText()
	case *runtimev1.AgentEvent_ToolCallStart:
		mapped.Type = AgentEventTypeToolCallStart
		mapped.ToolName = payload.ToolCallStart.GetToolName()
		mapped.ToolCallID = payload.ToolCallStart.GetToolCallId()
		mapped.Payload = structToRawJSON(payload.ToolCallStart.GetArgs())
	case *runtimev1.AgentEvent_ToolCallDone:
		mapped.Type = AgentEventTypeToolCallDone
		mapped.ToolName = payload.ToolCallDone.GetToolName()
		mapped.ToolCallID = payload.ToolCallDone.GetToolCallId()
	case *runtimev1.AgentEvent_ToolResult:
		mapped.Type = AgentEventTypeToolResult
		mapped.ToolCallID = payload.ToolResult.GetToolCallId()
		mapped.Text = payload.ToolResult.GetContent()
		mapped.Payload = protoMessageToRawJSON(payload.ToolResult)
	case *runtimev1.AgentEvent_HitlRequest:
		mapped.Type = AgentEventTypeHITLRequest
		mapped.InterruptID = payload.HitlRequest.GetInterruptId()
		mapped.Actions = actionRequestsFromProto(payload.HitlRequest.GetActionRequests())
		mapped.Payload = protoMessageToRawJSON(payload.HitlRequest)
	case *runtimev1.AgentEvent_RunEnded:
		mapped.Type = AgentEventTypeRunEnded
		mapped.Payload = protoMessageToRawJSON(payload.RunEnded)
	case *runtimev1.AgentEvent_RunCanceled:
		mapped.Type = AgentEventTypeRunCanceled
		mapped.Reason = payload.RunCanceled.GetReason()
	case *runtimev1.AgentEvent_Error:
		mapped.Type = AgentEventTypeError
		mapped.ErrorMessage = payload.Error.GetMessage()
		mapped.Reason = payload.Error.GetErrorType()
		mapped.Payload = protoMessageToRawJSON(payload.Error)
	default:
		mapped.Type = AgentEventTypeError
		mapped.ErrorMessage = "agent event payload is empty"
	}

	return mapped
}

func actionRequestsFromProto(requests []*runtimev1.ActionRequest) []ActionRequest {
	items := make([]ActionRequest, 0, len(requests))
	for _, request := range requests {
		items = append(items, ActionRequest{
			Action:     request.GetAction(),
			ToolCallID: request.GetToolCallId(),
			Arguments:  structToRawJSON(request.GetArgs()),
		})
	}
	return items
}

func toolDecisionsToProto(decisions []ToolDecision) []*runtimev1.ToolDecision {
	items := make([]*runtimev1.ToolDecision, 0, len(decisions))
	for _, decision := range decisions {
		items = append(items, &runtimev1.ToolDecision{
			ToolCallId: decision.ToolCallID,
			Approved:   decision.Approved,
			Reason:     decision.Reason,
		})
	}
	return items
}

func sessionHistoryModeToProto(mode domain.SessionHistoryMode) runtimev1.SessionHistoryMode {
	switch mode {
	case domain.SessionHistoryModeResumeView:
		return runtimev1.SessionHistoryMode_SESSION_HISTORY_MODE_RESUME_VIEW
	case domain.SessionHistoryModeFullTranscript:
		return runtimev1.SessionHistoryMode_SESSION_HISTORY_MODE_FULL_TRANSCRIPT
	default:
		return runtimev1.SessionHistoryMode_SESSION_HISTORY_MODE_UNSPECIFIED
	}
}

func sessionHistoryModeFromProto(mode runtimev1.SessionHistoryMode) domain.SessionHistoryMode {
	switch mode {
	case runtimev1.SessionHistoryMode_SESSION_HISTORY_MODE_RESUME_VIEW:
		return domain.SessionHistoryModeResumeView
	case runtimev1.SessionHistoryMode_SESSION_HISTORY_MODE_FULL_TRANSCRIPT:
		return domain.SessionHistoryModeFullTranscript
	default:
		return ""
	}
}

func sessionMessageRoleFromProto(role runtimev1.SessionMessageRole) domain.SessionMessageRole {
	switch role {
	case runtimev1.SessionMessageRole_SESSION_MESSAGE_ROLE_SYSTEM:
		return domain.SessionMessageRoleSystem
	case runtimev1.SessionMessageRole_SESSION_MESSAGE_ROLE_HUMAN:
		return domain.SessionMessageRoleHuman
	case runtimev1.SessionMessageRole_SESSION_MESSAGE_ROLE_AI:
		return domain.SessionMessageRoleAI
	case runtimev1.SessionMessageRole_SESSION_MESSAGE_ROLE_TOOL:
		return domain.SessionMessageRoleTool
	default:
		return ""
	}
}

func observedRuntimeStateFromProto(status runtimev1.AgentRuntimeStatus) domain.ObservedRuntimeState {
	switch status {
	case runtimev1.AgentRuntimeStatus_AGENT_RUNTIME_STATUS_INSTALLED:
		return domain.ObservedRuntimeStateInstalled
	case runtimev1.AgentRuntimeStatus_AGENT_RUNTIME_STATUS_COMPILED:
		return domain.ObservedRuntimeStateCompiled
	case runtimev1.AgentRuntimeStatus_AGENT_RUNTIME_STATUS_RUNNING:
		return domain.ObservedRuntimeStateRunning
	case runtimev1.AgentRuntimeStatus_AGENT_RUNTIME_STATUS_UNKNOWN,
		runtimev1.AgentRuntimeStatus_AGENT_RUNTIME_STATUS_UNSPECIFIED:
		return domain.ObservedRuntimeStateUnknown
	default:
		return domain.ObservedRuntimeStateUnknown
	}
}

func timestampFromProto(timestamp *timestamppb.Timestamp) time.Time {
	if timestamp == nil {
		return time.Time{}
	}
	return timestamp.AsTime()
}

func structToRawJSON(message *structpb.Struct) json.RawMessage {
	if message == nil {
		return nil
	}

	bytes, err := json.Marshal(message.AsMap())
	if err != nil {
		return nil
	}
	return json.RawMessage(bytes)
}

func protoMessageToRawJSON(message proto.Message) json.RawMessage {
	if message == nil {
		return nil
	}

	bytes, err := protojson.Marshal(message)
	if err != nil {
		return nil
	}
	return json.RawMessage(bytes)
}

func cloneStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	cloned := make([]string, len(values))
	copy(cloned, values)
	return cloned
}

func cloneStringMap(values map[string]string) map[string]string {
	if len(values) == 0 {
		return nil
	}
	cloned := make(map[string]string, len(values))
	for key, value := range values {
		cloned[key] = value
	}
	return cloned
}
