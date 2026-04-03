package runtimeclient

import (
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
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
			Skills:       skillsToProto(subagent.Skills),
			ModelConfig:  modelConfigToProto(subagent.Model),
		})
	}
	return items, nil
}

func sandboxSpecToProto(spec domain.SandboxSpec) *runtimev1.SandboxSpec {
	if spec.Empty() {
		return nil
	}
	sandbox := &runtimev1.SandboxSpec{
		Execution: &runtimev1.SandboxExecutionPolicy{
			CommandTimeoutSeconds: spec.Execution.CommandTimeoutSeconds,
			SetupTimeoutSeconds:   spec.Execution.SetupTimeoutSeconds,
			StartupTimeoutSeconds: spec.Execution.StartupTimeoutSeconds,
			MaxOutputBytes:        spec.Execution.MaxOutputBytes,
		},
		Env:           sandboxEnvVarsToProto(spec.Env),
		SetupCommands: cloneStrings(spec.SetupCommands),
	}
	switch {
	case spec.Local != nil:
		sandbox.Backend = &runtimev1.SandboxSpec_Local{
			Local: &runtimev1.LocalSandboxSpec{},
		}
	case spec.Docker != nil:
		sandbox.Backend = &runtimev1.SandboxSpec_Docker{
			Docker: &runtimev1.DockerSandboxSpec{
				Image: &runtimev1.ImageReference{
					Reference:  spec.Docker.Image.Reference,
					PullPolicy: imagePullPolicyToProto(spec.Docker.Image.PullPolicy),
				},
				Resources: &runtimev1.DockerResourceSpec{
					Cpu:       spec.Docker.Resources.CPU,
					Memory:    spec.Docker.Resources.Memory,
					ShmSize:   spec.Docker.Resources.ShmSize,
					PidsLimit: spec.Docker.Resources.PidsLimit,
				},
			},
		}
	case spec.Kubernetes != nil:
		sandbox.Backend = &runtimev1.SandboxSpec_Kubernetes{
			Kubernetes: &runtimev1.KubernetesSandboxSpec{
				Image: &runtimev1.ImageReference{
					Reference:  spec.Kubernetes.Image.Reference,
					PullPolicy: imagePullPolicyToProto(spec.Kubernetes.Image.PullPolicy),
				},
				Resources: &runtimev1.KubernetesResourceRequirements{
					Requests: cloneStringMap(spec.Kubernetes.Resources.Requests),
					Limits:   cloneStringMap(spec.Kubernetes.Resources.Limits),
				},
			},
		}
	}
	return sandbox
}

func sandboxEnvVarsToProto(env []domain.SandboxEnvVar) []*runtimev1.SandboxEnvVar {
	items := make([]*runtimev1.SandboxEnvVar, 0, len(env))
	for _, item := range env {
		items = append(items, &runtimev1.SandboxEnvVar{
			Name:  item.Name,
			Value: item.Value,
		})
	}
	return items
}

func imagePullPolicyToProto(policy domain.ImagePullPolicy) runtimev1.ImagePullPolicy {
	switch strings.TrimSpace(string(policy)) {
	case string(domain.ImagePullPolicyIfNotPresent):
		return runtimev1.ImagePullPolicy_IMAGE_PULL_POLICY_IF_NOT_PRESENT
	case string(domain.ImagePullPolicyAlways):
		return runtimev1.ImagePullPolicy_IMAGE_PULL_POLICY_ALWAYS
	case string(domain.ImagePullPolicyNever):
		return runtimev1.ImagePullPolicy_IMAGE_PULL_POLICY_NEVER
	default:
		return runtimev1.ImagePullPolicy_IMAGE_PULL_POLICY_UNSPECIFIED
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
		ApiKey:      spec.APIKey,
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

func workspaceUploadRequestToProto(
	req domain.WorkspaceUploadRequest,
) *runtimev1.UploadWorkspaceFilesRequest {
	files := make([]*runtimev1.UploadWorkspaceFile, 0, len(req.Files))
	for _, item := range req.Files {
		cleaned := filepath.ToSlash(filepath.Clean(item.Path))
		if filepath.IsAbs(cleaned) || strings.HasPrefix(cleaned, "..") {
			continue // skip paths that escape the workspace root
		}
		files = append(files, &runtimev1.UploadWorkspaceFile{
			Path:    cleaned,
			Content: item.Content,
		})
	}

	return &runtimev1.UploadWorkspaceFilesRequest{
		AgentName: req.AgentName,
		ThreadId:  req.ThreadID,
		Files:     files,
	}
}

func workspaceUploadResponseFromProto(
	resp *runtimev1.UploadWorkspaceFilesResponse,
) domain.WorkspaceUploadResponse {
	if resp == nil {
		return domain.WorkspaceUploadResponse{}
	}

	files := make([]domain.WorkspaceUploadResult, 0, len(resp.GetFiles()))
	for _, item := range resp.GetFiles() {
		files = append(files, domain.WorkspaceUploadResult{
			Path:  item.GetPath(),
			Error: item.GetError(),
		})
	}
	return domain.WorkspaceUploadResponse{
		ThreadID: resp.GetThreadId(),
		Files:    files,
	}
}

func workspaceDownloadRequestToProto(
	req domain.WorkspaceDownloadRequest,
) *runtimev1.DownloadWorkspaceFilesRequest {
	paths := make([]string, 0, len(req.Paths))
	for _, p := range req.Paths {
		cleaned := filepath.ToSlash(filepath.Clean(p))
		if filepath.IsAbs(cleaned) || strings.HasPrefix(cleaned, "..") {
			continue // skip paths that escape the workspace root
		}
		paths = append(paths, cleaned)
	}
	return &runtimev1.DownloadWorkspaceFilesRequest{
		AgentName: req.AgentName,
		ThreadId:  req.ThreadID,
		Paths:     paths,
	}
}

func workspaceDownloadResponseFromProto(
	resp *runtimev1.DownloadWorkspaceFilesResponse,
) domain.WorkspaceDownloadResponse {
	if resp == nil {
		return domain.WorkspaceDownloadResponse{}
	}
	files := make([]domain.WorkspaceDownloadResult, 0, len(resp.GetFiles()))
	for _, item := range resp.GetFiles() {
		files = append(files, domain.WorkspaceDownloadResult{
			Path:    item.GetPath(),
			Content: item.GetContent(),
			Error:   item.GetError(),
		})
	}
	return domain.WorkspaceDownloadResponse{
		ThreadID: resp.GetThreadId(),
		Files:    files,
	}
}

func workspaceListRequestToProto(
	req domain.WorkspaceListRequest,
) *runtimev1.ListWorkspaceFilesRequest {
	path := filepath.ToSlash(filepath.Clean(req.Path))
	if filepath.IsAbs(path) || strings.HasPrefix(path, "..") {
		path = "."
	}
	return &runtimev1.ListWorkspaceFilesRequest{
		AgentName: req.AgentName,
		ThreadId:  req.ThreadID,
		Path:      path,
	}
}

func workspaceListResponseFromProto(
	resp *runtimev1.ListWorkspaceFilesResponse,
) domain.WorkspaceListResponse {
	if resp == nil {
		return domain.WorkspaceListResponse{}
	}
	files := make([]domain.WorkspaceFileInfo, 0, len(resp.GetFiles()))
	for _, item := range resp.GetFiles() {
		files = append(files, domain.WorkspaceFileInfo{
			Path:       item.GetPath(),
			IsDir:      item.GetIsDir(),
			Size:       item.GetSize(),
			ModifiedAt: item.GetModifiedAt(),
		})
	}
	return domain.WorkspaceListResponse{
		ThreadID: resp.GetThreadId(),
		Files:    files,
	}
}

func threadArtifactsResponseFromProto(
	resp *runtimev1.ListThreadArtifactsResponse,
) domain.ListArtifactsResponse {
	if resp == nil {
		return domain.ListArtifactsResponse{}
	}
	artifacts := make([]domain.ThreadArtifact, 0, len(resp.GetArtifacts()))
	for _, item := range resp.GetArtifacts() {
		artifacts = append(artifacts, domain.ThreadArtifact{
			ID:            item.GetId(),
			Type:          item.GetType(),
			Path:          item.GetPath(),
			Title:         item.GetTitle(),
			ContentType:   item.GetContentType(),
			Language:      item.GetLanguage(),
			CreatedByTool: item.GetCreatedByTool(),
			CreatedAt:     item.GetCreatedAt(),
			ModifiedAt:    item.GetModifiedAt(),
			Size:          item.GetSize(),
		})
	}
	return domain.ListArtifactsResponse{
		ThreadID:  resp.GetThreadId(),
		Artifacts: artifacts,
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
		mapped.Payload = valueToRawJSON(payload.ToolResult.GetPayload())
	case *runtimev1.AgentEvent_HitlRequest:
		mapped.Type = AgentEventTypeHITLRequest
		mapped.InterruptID = payload.HitlRequest.GetInterruptId()
		mapped.Actions = actionRequestsFromProto(payload.HitlRequest.GetActionRequests())
		mapped.ReviewConfigs = reviewConfigsFromProto(payload.HitlRequest.GetReviewConfigs())
		//mapped.Payload = protoMessageToRawJSON(payload.HitlRequest)
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
		//mapped.Payload = protoMessageToRawJSON(payload.Error)
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
			Name:        request.GetName(),
			Description: request.GetDescription(),
			Arguments:   structToRawJSON(request.GetArgs()),
		})
	}
	return items
}

func reviewConfigsFromProto(configs []*runtimev1.ReviewConfig) []ReviewConfig {
	items := make([]ReviewConfig, 0, len(configs))
	for _, config := range configs {
		items = append(items, ReviewConfig{
			ActionName:       config.GetActionName(),
			AllowedDecisions: cloneStrings(config.GetAllowedDecisions()),
			ArgsSchema:       structToRawJSON(config.GetArgsSchema()),
		})
	}
	return items
}

func toolDecisionsToProto(decisions []ToolDecision) []*runtimev1.Decision {
	items := make([]*runtimev1.Decision, 0, len(decisions))
	for _, decision := range decisions {
		item := &runtimev1.Decision{
			Type:    decision.Type,
			Message: decision.Message,
		}
		if decision.EditedAction != nil {
			item.EditedAction = &runtimev1.Action{
				Name: decision.EditedAction.Name,
			}
			if arguments := rawJSONToStruct(decision.EditedAction.Arguments); arguments != nil {
				item.EditedAction.Args = arguments
			}
		}
		items = append(items, item)
	}
	return items
}

func rawJSONToStruct(payload json.RawMessage) *structpb.Struct {
	if len(payload) == 0 {
		return nil
	}

	var value map[string]any
	if err := json.Unmarshal(payload, &value); err != nil {
		return nil
	}

	result, err := structpb.NewStruct(value)
	if err != nil {
		return nil
	}
	return result
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

func valueToRawJSON(message *structpb.Value) json.RawMessage {
	if message == nil {
		return nil
	}

	bytes, err := json.Marshal(message.AsInterface())
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
