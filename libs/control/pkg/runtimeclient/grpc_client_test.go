package runtimeclient

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"reflect"
	"testing"
	"time"

	"agentctl/pkg/domain"
	runtimev1 "agentctl/pkg/proto"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	grpcstatus "google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/types/known/structpb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type testRuntimeServer struct {
	runtimev1.UnimplementedResourceSyncServer
	runtimev1.UnimplementedAgentExecutorServer
	runtimev1.UnimplementedAgentTelemetryServer
	runtimev1.UnimplementedSessionQueryServer

	syncAgentSpecResponse *runtimev1.SyncResponse
	syncAgentSpecRequest  *runtimev1.SyncAgentSpecRequest

	assembleResponse *runtimev1.AssembleResponse
	assembleRequest  *runtimev1.AssembleRequest
	graphResponse    *runtimev1.GetAgentGraphResponse
	graphRequest     *runtimev1.GetAgentGraphRequest

	uploadResponse *runtimev1.UploadWorkspaceFilesResponse
	uploadRequest  *runtimev1.UploadWorkspaceFilesRequest

	removeResponse *runtimev1.SyncResponse
	removeRequest  *runtimev1.RemoveResourceRequest

	healthResponse *runtimev1.HealthResponse

	listSessionsResponse  *runtimev1.ListSessionsResponse
	getSessionResponse    *runtimev1.GetSessionResponse
	getSessionRequest     *runtimev1.GetSessionRequest
	getMessagesResponse   *runtimev1.GetSessionMessagesResponse
	getMessagesRequest    *runtimev1.GetSessionMessagesRequest
	getLatestResponse     *runtimev1.GetLatestSessionResponse
	deleteSessionResponse *runtimev1.DeleteSessionResponse
	deleteSessionRequest  *runtimev1.DeleteSessionRequest

	receivedRunRequest      *runtimev1.RunRequest
	receivedTelemetryRun    *runtimev1.RunRequest
	receivedHITLDecision    *runtimev1.HITLDecision
	receivedCancel          *runtimev1.CancelRequest
	receivedTelemetryHITL   *runtimev1.HITLDecision
	receivedTelemetryCancel *runtimev1.CancelRequest
}

func (s *testRuntimeServer) SyncAgentSpec(
	_ context.Context,
	_ *runtimev1.SyncAgentSpecRequest,
) (*runtimev1.SyncResponse, error) {
	return &runtimev1.SyncResponse{Ok: true}, nil
}

func (s *testRuntimeServer) Assemble(
	_ context.Context,
	request *runtimev1.AssembleRequest,
) (*runtimev1.AssembleResponse, error) {
	s.assembleRequest = request
	if s.assembleResponse == nil {
		return &runtimev1.AssembleResponse{Ok: true, Status: "compiled"}, nil
	}
	return s.assembleResponse, nil
}

func (s *testRuntimeServer) GetAgentGraph(
	_ context.Context,
	request *runtimev1.GetAgentGraphRequest,
) (*runtimev1.GetAgentGraphResponse, error) {
	s.graphRequest = request
	if s.graphResponse == nil {
		return &runtimev1.GetAgentGraphResponse{}, nil
	}
	return s.graphResponse, nil
}

func (s *testRuntimeServer) UploadWorkspaceFiles(
	_ context.Context,
	request *runtimev1.UploadWorkspaceFilesRequest,
) (*runtimev1.UploadWorkspaceFilesResponse, error) {
	s.uploadRequest = request
	if s.uploadResponse == nil {
		return &runtimev1.UploadWorkspaceFilesResponse{}, nil
	}
	return s.uploadResponse, nil
}

func (s *testRuntimeServer) RemoveResource(
	_ context.Context,
	request *runtimev1.RemoveResourceRequest,
) (*runtimev1.SyncResponse, error) {
	s.removeRequest = request
	if s.removeResponse == nil {
		return &runtimev1.SyncResponse{Ok: true, Message: "removed"}, nil
	}
	return s.removeResponse, nil
}

func (s *testRuntimeServer) Health(
	_ context.Context,
	_ *runtimev1.HealthRequest,
) (*runtimev1.HealthResponse, error) {
	if s.healthResponse == nil {
		return &runtimev1.HealthResponse{Status: "ok", Ready: true}, nil
	}
	return s.healthResponse, nil
}

func (s *testRuntimeServer) ListSessions(
	_ context.Context,
	_ *runtimev1.ListSessionsRequest,
) (*runtimev1.ListSessionsResponse, error) {
	if s.listSessionsResponse == nil {
		return &runtimev1.ListSessionsResponse{}, nil
	}
	return s.listSessionsResponse, nil
}

func (s *testRuntimeServer) GetSession(
	_ context.Context,
	request *runtimev1.GetSessionRequest,
) (*runtimev1.GetSessionResponse, error) {
	s.getSessionRequest = request
	if s.getSessionResponse == nil {
		return &runtimev1.GetSessionResponse{Found: false}, nil
	}
	return s.getSessionResponse, nil
}

func (s *testRuntimeServer) GetSessionMessages(
	_ context.Context,
	request *runtimev1.GetSessionMessagesRequest,
) (*runtimev1.GetSessionMessagesResponse, error) {
	s.getMessagesRequest = request
	if s.getMessagesResponse == nil {
		return nil, grpcstatus.Error(codes.NotFound, "session not found")
	}
	return s.getMessagesResponse, nil
}

func (s *testRuntimeServer) GetLatestSession(
	_ context.Context,
	_ *runtimev1.GetLatestSessionRequest,
) (*runtimev1.GetLatestSessionResponse, error) {
	if s.getLatestResponse == nil {
		return &runtimev1.GetLatestSessionResponse{Found: false}, nil
	}
	return s.getLatestResponse, nil
}

func (s *testRuntimeServer) DeleteSession(
	_ context.Context,
	request *runtimev1.DeleteSessionRequest,
) (*runtimev1.DeleteSessionResponse, error) {
	s.deleteSessionRequest = request
	if s.deleteSessionResponse == nil {
		return &runtimev1.DeleteSessionResponse{Deleted: false}, nil
	}
	return s.deleteSessionResponse, nil
}

func (s *testRuntimeServer) Run(
	stream runtimev1.AgentExecutor_RunServer,
) error {
	first, err := stream.Recv()
	if err != nil {
		return err
	}
	s.receivedRunRequest = first.GetRunRequest()

	if err := stream.Send(&runtimev1.AgentEvent{
		RunId:     "run-1",
		AgentName: s.receivedRunRequest.GetAgentName(),
		Timestamp: timestamppb.New(time.Unix(100, 0)),
		Payload: &runtimev1.AgentEvent_RunStarted{
			RunStarted: &runtimev1.RunStarted{ThreadId: "thread-1"},
		},
	}); err != nil {
		return err
	}
	if err := stream.Send(&runtimev1.AgentEvent{
		RunId:     "run-1",
		AgentName: s.receivedRunRequest.GetAgentName(),
		Timestamp: timestamppb.New(time.Unix(101, 0)),
		Payload: &runtimev1.AgentEvent_HitlRequest{
			HitlRequest: &runtimev1.HITLRequest{
				InterruptId: "interrupt-1",
				ActionRequests: []*runtimev1.ActionRequest{
					{
						Name:        "write_file",
						Args:        mustStructValue(map[string]any{"path": "/tmp/a.txt"}),
						Description: "Write /tmp/a.txt",
					},
				},
				ReviewConfigs: []*runtimev1.ReviewConfig{
					{
						ActionName:       "write_file",
						AllowedDecisions: []string{"approve", "reject"},
					},
				},
			},
		},
	}); err != nil {
		return err
	}

	next, err := stream.Recv()
	if err != nil {
		return err
	}
	s.receivedHITLDecision = next.GetHitlDecision()

	if err := stream.Send(&runtimev1.AgentEvent{
		RunId:     "run-1",
		AgentName: s.receivedRunRequest.GetAgentName(),
		Timestamp: timestamppb.New(time.Unix(102, 0)),
		Payload: &runtimev1.AgentEvent_ToolCallStart{
			ToolCallStart: &runtimev1.ToolCallStart{
				ToolName:   "write_file",
				ToolCallId: "tool-1",
				Args: mustStructValue(map[string]any{
					"path":    "/tmp/a.txt",
					"content": "hello",
				}),
			},
		},
	}); err != nil {
		return err
	}

	if err := stream.Send(&runtimev1.AgentEvent{
		RunId:     "run-1",
		AgentName: s.receivedRunRequest.GetAgentName(),
		Timestamp: timestamppb.New(time.Unix(103, 0)),
		Payload: &runtimev1.AgentEvent_ToolResult{
			ToolResult: &runtimev1.ToolResult{
				ToolCallId: "tool-1",
				Content:    "ok",
				IsError:    false,
				Payload:    mustValueValue(map[string]any{"path": "/tmp/a.txt", "written": true}),
			},
		},
	}); err != nil {
		return err
	}

	last, err := stream.Recv()
	if err != nil {
		return err
	}
	s.receivedCancel = last.GetCancel()

	return stream.Send(&runtimev1.AgentEvent{
		RunId:     "run-1",
		AgentName: s.receivedRunRequest.GetAgentName(),
		Timestamp: timestamppb.New(time.Unix(104, 0)),
		Payload: &runtimev1.AgentEvent_RunCanceled{
			RunCanceled: &runtimev1.RunCanceled{Reason: s.receivedCancel.GetReason()},
		},
	})
}

func (s *testRuntimeServer) RunTelemetry(
	stream runtimev1.AgentTelemetry_RunTelemetryServer,
) error {
	first, err := stream.Recv()
	if err != nil {
		return err
	}
	s.receivedTelemetryRun = first.GetRunRequest()

	if err := stream.Send(&runtimev1.TelemetryEvent{
		RunId:      "run-telemetry-1",
		AgentName:  s.receivedTelemetryRun.GetAgentName(),
		Timestamp:  timestamppb.New(time.Unix(200, 0)),
		EventId:    "run-telemetry-1:1:1",
		Attempt:    1,
		Seq:        1,
		NodeName:   "run",
		StreamMode: "lifecycle",
		EventType:  "run_started",
		PublicEvent: &runtimev1.AgentEvent{
			RunId:     "run-telemetry-1",
			AgentName: s.receivedTelemetryRun.GetAgentName(),
			Timestamp: timestamppb.New(time.Unix(200, 0)),
			Payload: &runtimev1.AgentEvent_RunStarted{
				RunStarted: &runtimev1.RunStarted{ThreadId: s.receivedTelemetryRun.GetThreadId()},
			},
		},
	}); err != nil {
		return err
	}

	if err := stream.Send(&runtimev1.TelemetryEvent{
		RunId:       "run-telemetry-1",
		AgentName:   s.receivedTelemetryRun.GetAgentName(),
		Timestamp:   timestamppb.New(time.Unix(201, 0)),
		EventId:     "run-telemetry-1:1:2",
		Attempt:     1,
		Seq:         2,
		NodeName:    "planner",
		MessageId:   "msg-1",
		ModelCallId: "msg-1",
		Ns:          []string{"task:research"},
		StreamMode:  "messages",
		EventType:   "reasoning",
		Metadata:    mustStructValue(map[string]any{"langgraph_node": "planner"}),
		Payload: mustValueValue(map[string]any{
			"summary": []any{
				map[string]any{"type": "summary_text", "text": "thinking..."},
			},
		}),
	}); err != nil {
		return err
	}

	if err := stream.Send(&runtimev1.TelemetryEvent{
		RunId:      "run-telemetry-1",
		AgentName:  s.receivedTelemetryRun.GetAgentName(),
		Timestamp:  timestamppb.New(time.Unix(202, 0)),
		EventId:    "run-telemetry-1:1:3",
		Attempt:    1,
		Seq:        3,
		NodeName:   "research",
		TaskId:     "task-1",
		Ns:         []string{"task:research"},
		StreamMode: "debug",
		EventType:  "task",
		Metadata:   mustStructValue(map[string]any{"step": 2}),
		Payload: mustValueValue(map[string]any{
			"id":       "task-1",
			"name":     "research",
			"triggers": []any{"messages"},
		}),
	}); err != nil {
		return err
	}

	if err := stream.Send(&runtimev1.TelemetryEvent{
		RunId:      "run-telemetry-1",
		AgentName:  s.receivedTelemetryRun.GetAgentName(),
		Timestamp:  timestamppb.New(time.Unix(203, 0)),
		StreamMode: "lifecycle",
		EventType:  "hitl_request",
		PublicEvent: &runtimev1.AgentEvent{
			RunId:     "run-telemetry-1",
			AgentName: s.receivedTelemetryRun.GetAgentName(),
			Timestamp: timestamppb.New(time.Unix(203, 0)),
			Payload: &runtimev1.AgentEvent_HitlRequest{
				HitlRequest: &runtimev1.HITLRequest{
					InterruptId: "interrupt-1",
					ActionRequests: []*runtimev1.ActionRequest{
						{
							Name:        "write_file",
							Args:        mustStructValue(map[string]any{"path": "/tmp/a.txt"}),
							Description: "Write /tmp/a.txt",
						},
					},
					ReviewConfigs: []*runtimev1.ReviewConfig{
						{
							ActionName:       "write_file",
							AllowedDecisions: []string{"approve", "reject"},
						},
					},
				},
			},
		},
	}); err != nil {
		return err
	}

	next, err := stream.Recv()
	if err != nil {
		return err
	}
	s.receivedTelemetryHITL = next.GetHitlDecision()

	last, err := stream.Recv()
	if err != nil {
		return err
	}
	s.receivedTelemetryCancel = last.GetCancel()

	return stream.Send(&runtimev1.TelemetryEvent{
		RunId:      "run-telemetry-1",
		AgentName:  s.receivedTelemetryRun.GetAgentName(),
		Timestamp:  timestamppb.New(time.Unix(204, 0)),
		StreamMode: "lifecycle",
		EventType:  "run_canceled",
		PublicEvent: &runtimev1.AgentEvent{
			RunId:     "run-telemetry-1",
			AgentName: s.receivedTelemetryRun.GetAgentName(),
			Timestamp: timestamppb.New(time.Unix(204, 0)),
			Payload: &runtimev1.AgentEvent_RunCanceled{
				RunCanceled: &runtimev1.RunCanceled{Reason: s.receivedTelemetryCancel.GetReason()},
			},
		},
	})
}

func TestGRPCClientSyncAgentSpecHealthAndRemove(t *testing.T) {
	server := &testRuntimeServer{
		syncAgentSpecResponse: &runtimev1.SyncResponse{Ok: true, Message: "synced"},
		graphResponse: &runtimev1.GetAgentGraphResponse{
			Graph: mustValueValue(map[string]any{
				"nodes": []any{
					map[string]any{"id": "model", "type": "runnable", "data": map[string]any{"name": "model"}},
				},
				"edges": []any{
					map[string]any{"source": "__start__", "target": "model"},
				},
			}),
		},
		uploadResponse: &runtimev1.UploadWorkspaceFilesResponse{
			ThreadId: "thread-upload",
			Files: []*runtimev1.UploadWorkspaceFileResult{
				{Path: "report.txt"},
			},
		},
		healthResponse: &runtimev1.HealthResponse{
			Status:              "ok",
			AssembledAgentCount: 2,
			InstalledAgentCount: 3,
			RunningAgentCount:   1,
			UptimeSeconds:       42.5,
			Ready:               true,
		},
		removeResponse: &runtimev1.SyncResponse{Ok: true, Message: "removed"},
	}

	client, cleanup := newTestClient(t, server)
	defer cleanup()

	spec := domain.RuntimeAgentSpec{
		Name:        "assistant",
		Version:     "1.0.0",
		Description: "demo agent",
		Tags:        []string{"prod"},
		Model: domain.ModelSpec{
			Provider:    "openai",
			Model:       "gpt-5",
			BaseURL:     "https://example.com/v1",
			APIKeyEnv:   "OPENAI_API_KEY",
			ExtraParams: map[string]string{"temperature": "0"},
		},
		Prompt: domain.PromptSpec{System: "You are helpful"},
		Skills: []domain.Skill{
			{
				Name:        "writer",
				Content:     "# writer",
				Description: "writes",
				Tags:        []string{"content"},
				Files: []domain.SkillFile{
					{Path: "scripts/init.py", Content: "print('ok')"},
				},
			},
		},
		MCPServers: []domain.MCPConfig{
			{
				Name:        "docs",
				Command:     "uvx",
				Args:        []string{"mcp-docs"},
				Env:         map[string]string{"TOKEN": "redacted"},
				Transport:   "stdio",
				Description: "docs server",
			},
		},
		Subagents: []domain.SubagentSpec{
			{
				Name:         "planner",
				Description:  "plans work",
				SystemPrompt: "plan first",
				Model: domain.ModelSpec{
					Provider: "anthropic",
					Model:    "claude-sonnet-4-6",
				},
			},
		},
		Sandbox: domain.SandboxSpec{
			Docker: &domain.DockerSandboxSpec{
				Image: domain.ImageReference{Reference: "python:3.12"},
				Resources: domain.DockerResourceSpec{
					CPU: "2",
				},
			},
			SetupCommands: []string{"echo ready"},
		},
		InterruptOn: []string{"write_file"},
	}

	syncResponse, err := client.SyncAgentSpec(context.Background(), spec)
	if err != nil {
		t.Fatalf("SyncAgentSpec returned error: %v", err)
	}
	if !syncResponse.OK || syncResponse.Message != "synced" {
		t.Fatalf("unexpected sync response: %#v", syncResponse)
	}

	request := server.syncAgentSpecRequest
	if request == nil {
		t.Fatal("expected SyncAgentSpec request capture")
	}
	if request.GetModel() != "openai:gpt-5" {
		t.Fatalf("unexpected model string: %s", request.GetModel())
	}
	if request.GetModelConfig().GetProvider() != "openai" {
		t.Fatalf("unexpected model provider: %#v", request.GetModelConfig())
	}
	if request.GetModelConfig().GetApiKeyEnv() != "OPENAI_API_KEY" {
		t.Fatalf("unexpected api key env: %#v", request.GetModelConfig())
	}
	if request.GetSubagents()[0].GetModel() != "anthropic:claude-sonnet-4-6" {
		t.Fatalf("unexpected subagent model: %#v", request.GetSubagents()[0])
	}
	if request.GetSkills()[0].GetFiles()[0].GetPath() != "scripts/init.py" {
		t.Fatalf("unexpected skill file path: %#v", request.GetSkills()[0])
	}
	if request.GetMcpServers()[0].GetTransport() != "stdio" {
		t.Fatalf("unexpected mcp server transport: %#v", request.GetMcpServers()[0])
	}
	if request.GetSandbox().GetDocker().GetImage().GetReference() != "python:3.12" {
		t.Fatalf("unexpected sandbox image: %#v", request.GetSandbox())
	}
	if request.GetSandbox().GetDocker().GetResources().GetCpu() != "2" {
		t.Fatalf("unexpected sandbox resources: %#v", request.GetSandbox().GetDocker())
	}
	if len(request.GetSandbox().GetSetupCommands()) != 1 {
		t.Fatalf("unexpected sandbox setup commands: %#v", request.GetSandbox())
	}

	uploadResponse, err := client.UploadWorkspaceFiles(
		context.Background(),
		domain.WorkspaceUploadRequest{
			AgentName: "assistant",
			ThreadID:  "thread-upload",
			Files: []domain.WorkspaceUploadFile{
				{
					Path:    "report.txt",
					Content: []byte("hello"),
				},
			},
		},
	)
	if err != nil {
		t.Fatalf("UploadWorkspaceFiles returned error: %v", err)
	}
	if uploadResponse.ThreadID != "thread-upload" || len(uploadResponse.Files) != 1 {
		t.Fatalf("unexpected upload response: %#v", uploadResponse)
	}
	if server.uploadRequest == nil || server.uploadRequest.GetAgentName() != "assistant" {
		t.Fatalf("unexpected upload request: %#v", server.uploadRequest)
	}
	if server.uploadRequest.GetFiles()[0].GetPath() != "report.txt" {
		t.Fatalf("unexpected upload file request: %#v", server.uploadRequest.GetFiles()[0])
	}

	health, err := client.Health(context.Background())
	if err != nil {
		t.Fatalf("Health returned error: %v", err)
	}
	if !health.Ready || health.AssembledAgentCount != 2 || health.UptimeSeconds != 42.5 {
		t.Fatalf("unexpected health response: %#v", health)
	}

	assembleResponse, err := client.Assemble(context.Background(), "assistant")
	if err != nil {
		t.Fatalf("Assemble returned error: %v", err)
	}
	if !assembleResponse.OK || assembleResponse.Status != "compiled" {
		t.Fatalf("unexpected assemble response: %#v", assembleResponse)
	}
	if server.assembleRequest.GetAgentName() != "assistant" {
		t.Fatalf("unexpected assemble request: %#v", server.assembleRequest)
	}

	graph, err := client.GetAgentGraph(context.Background(), "assistant", 1)
	if err != nil {
		t.Fatalf("GetAgentGraph returned error: %v", err)
	}
	if !payloadContains(t, graph, "nodes", []any{
		map[string]any{
			"id":   "model",
			"type": "runnable",
			"data": map[string]any{"name": "model"},
		},
	}) {
		t.Fatalf("unexpected graph payload: %s", string(graph))
	}
	if server.graphRequest == nil || server.graphRequest.GetAgentName() != "assistant" || server.graphRequest.GetXrayDepth() != 1 {
		t.Fatalf("unexpected graph request: %#v", server.graphRequest)
	}

	removeResponse, err := client.RemoveAgent(context.Background(), "assistant")
	if err != nil {
		t.Fatalf("RemoveAgent returned error: %v", err)
	}
	if !removeResponse.OK || server.removeRequest.GetResourceType() != "agent" {
		t.Fatalf("unexpected remove response/request: %#v %#v", removeResponse, server.removeRequest)
	}
}

func TestGRPCClientSessionQueries(t *testing.T) {
	server := &testRuntimeServer{
		listSessionsResponse: &runtimev1.ListSessionsResponse{
			Sessions: []*runtimev1.SessionSummary{
				{
					ThreadId:           "thread-1",
					AgentName:          "assistant",
					UpdatedAt:          timestamppb.New(time.Unix(200, 0)),
					LatestCheckpointId: "cp-2",
					MessageCount:       4,
					InitialPrompt:      "hello",
					HistoryMode:        runtimev1.SessionHistoryMode_SESSION_HISTORY_MODE_RESUME_VIEW,
					AgentStatus:        runtimev1.AgentRuntimeStatus_AGENT_RUNTIME_STATUS_RUNNING,
				},
			},
			NextPageToken: "page-2",
		},
		getSessionResponse: &runtimev1.GetSessionResponse{
			Found: true,
			Session: &runtimev1.SessionDetail{
				Summary: &runtimev1.SessionSummary{
					ThreadId:           "thread-1",
					AgentName:          "assistant",
					UpdatedAt:          timestamppb.New(time.Unix(201, 0)),
					LatestCheckpointId: "cp-3",
					MessageCount:       6,
					InitialPrompt:      "hello again",
					HistoryMode:        runtimev1.SessionHistoryMode_SESSION_HISTORY_MODE_FULL_TRANSCRIPT,
					AgentStatus:        runtimev1.AgentRuntimeStatus_AGENT_RUNTIME_STATUS_COMPILED,
				},
				CheckpointCount: 3,
			},
		},
		getMessagesResponse: &runtimev1.GetSessionMessagesResponse{
			ThreadId:             "thread-1",
			ResolvedCheckpointId: "cp-3",
			ActualMode:           runtimev1.SessionHistoryMode_SESSION_HISTORY_MODE_RESUME_VIEW,
			TotalMessageCount:    2,
			Messages: []*runtimev1.SessionMessage{
				{
					Index:      0,
					Role:       runtimev1.SessionMessageRole_SESSION_MESSAGE_ROLE_HUMAN,
					Text:       "hello",
					ToolCallId: "",
					ToolName:   "",
					IsError:    false,
					Raw:        mustStruct(t, map[string]any{"kind": "human"}),
				},
				{
					Index:      1,
					Role:       runtimev1.SessionMessageRole_SESSION_MESSAGE_ROLE_TOOL,
					Text:       "ok",
					ToolCallId: "tool-1",
					ToolName:   "write_file",
					IsError:    false,
					Raw:        mustStruct(t, map[string]any{"kind": "tool"}),
				},
			},
			NextPageToken: "page-3",
		},
		getLatestResponse: &runtimev1.GetLatestSessionResponse{
			Found: true,
			Session: &runtimev1.SessionSummary{
				ThreadId:           "thread-9",
				AgentName:          "assistant",
				UpdatedAt:          timestamppb.New(time.Unix(202, 0)),
				LatestCheckpointId: "cp-9",
				MessageCount:       8,
				InitialPrompt:      "latest prompt",
				HistoryMode:        runtimev1.SessionHistoryMode_SESSION_HISTORY_MODE_RESUME_VIEW,
				AgentStatus:        runtimev1.AgentRuntimeStatus_AGENT_RUNTIME_STATUS_INSTALLED,
			},
		},
		deleteSessionResponse: &runtimev1.DeleteSessionResponse{Deleted: true},
	}

	client, cleanup := newTestClient(t, server)
	defer cleanup()

	sessions, nextPageToken, err := client.ListSessions(context.Background(), "assistant", 20, "")
	if err != nil {
		t.Fatalf("ListSessions returned error: %v", err)
	}
	if len(sessions) != 1 || nextPageToken != "page-2" {
		t.Fatalf("unexpected list response: %#v %q", sessions, nextPageToken)
	}
	if sessions[0].InitialPrompt != "hello" || sessions[0].AgentStatus != domain.ObservedRuntimeStateRunning {
		t.Fatalf("unexpected session summary mapping: %#v", sessions[0])
	}

	session, err := client.GetSession(context.Background(), domain.SessionLocator{
		AgentName: "assistant",
		ThreadID:  "thread-1",
	})
	if err != nil {
		t.Fatalf("GetSession returned error: %v", err)
	}
	if session.CheckpointCount != 3 || session.HistoryMode != domain.SessionHistoryModeFullTranscript {
		t.Fatalf("unexpected session detail mapping: %#v", session)
	}
	if server.getSessionRequest == nil ||
		server.getSessionRequest.GetAgentName() != "assistant" ||
		server.getSessionRequest.GetThreadId() != "thread-1" {
		t.Fatalf("unexpected session request capture: %#v", server.getSessionRequest)
	}

	page, err := client.GetSessionMessagePage(context.Background(), domain.SessionMessageQuery{
		AgentName:    "assistant",
		ThreadID:     "thread-1",
		CheckpointID: "cp-2",
		Mode:         domain.SessionHistoryModeResumeView,
		PageSize:     20,
		PageToken:    "page-2",
		IncludeRaw:   true,
	})
	if err != nil {
		t.Fatalf("GetSessionMessagePage returned error: %v", err)
	}
	if page.ThreadID != "thread-1" || page.ResolvedCheckpointID != "cp-3" {
		t.Fatalf("unexpected page identity mapping: %#v", page)
	}
	if page.ActualMode != domain.SessionHistoryModeResumeView || page.TotalMessageCount != 2 {
		t.Fatalf("unexpected page metadata mapping: %#v", page)
	}
	if server.getMessagesRequest == nil {
		t.Fatal("expected GetSessionMessages request capture")
	}
	if server.getMessagesRequest.GetCheckpointId() != "cp-2" ||
		server.getMessagesRequest.GetAgentName() != "assistant" ||
		server.getMessagesRequest.GetPageToken() != "page-2" ||
		server.getMessagesRequest.GetRequestedMode() != runtimev1.SessionHistoryMode_SESSION_HISTORY_MODE_RESUME_VIEW ||
		!server.getMessagesRequest.GetIncludeRaw() {
		t.Fatalf("unexpected page request capture: %#v", server.getMessagesRequest)
	}

	messages, token, err := client.GetSessionMessages(context.Background(), domain.SessionMessageQuery{
		AgentName: "assistant",
		ThreadID:  "thread-1",
		Mode:      domain.SessionHistoryModeResumeView,
		PageSize:  20,
	})
	if err != nil {
		t.Fatalf("GetSessionMessages returned error: %v", err)
	}
	if len(messages) != 2 || token != "page-3" {
		t.Fatalf("unexpected messages response: %#v %q", messages, token)
	}
	if messages[0].Text != "hello" || messages[0].Content != "hello" {
		t.Fatalf("unexpected first message mapping: %#v", messages[0])
	}
	if messages[1].CheckpointID != "cp-3" || messages[1].ToolName != "write_file" || string(messages[1].Raw) == "" {
		t.Fatalf("unexpected second message mapping: %#v", messages[1])
	}

	latest, err := client.GetLatestSession(context.Background(), "assistant")
	if err != nil {
		t.Fatalf("GetLatestSession returned error: %v", err)
	}
	if latest.ThreadID != "thread-9" || latest.AgentStatus != domain.ObservedRuntimeStateInstalled {
		t.Fatalf("unexpected latest session mapping: %#v", latest)
	}

	if err := client.DeleteSession(context.Background(), domain.SessionLocator{
		AgentName: "assistant",
		ThreadID:  "thread-1",
	}); err != nil {
		t.Fatalf("DeleteSession returned error: %v", err)
	}
	if server.deleteSessionRequest == nil ||
		server.deleteSessionRequest.GetAgentName() != "assistant" ||
		server.deleteSessionRequest.GetThreadId() != "thread-1" {
		t.Fatalf("unexpected delete session request: %#v", server.deleteSessionRequest)
	}
}

func TestGRPCClientRunStream(t *testing.T) {
	server := &testRuntimeServer{}
	client, cleanup := newTestClient(t, server)
	defer cleanup()

	stream, err := client.OpenRun(context.Background(), domain.RunRequest{
		AgentName: "assistant",
		Message:   "hello",
		ThreadID:  "thread-1",
		Metadata:  map[string]string{"timeout_seconds": "30"},
	})
	if err != nil {
		t.Fatalf("OpenRun returned error: %v", err)
	}
	defer stream.Close()

	first := <-stream.Events()
	if first.Type != AgentEventTypeRunStarted || first.ThreadID != "thread-1" {
		t.Fatalf("unexpected first event: %#v", first)
	}

	second := <-stream.Events()
	if second.Type != AgentEventTypeHITLRequest || second.InterruptID != "interrupt-1" {
		t.Fatalf("unexpected second event: %#v", second)
	}
	if len(second.Actions) != 1 || second.Actions[0].Name != "write_file" ||
		second.Actions[0].Description != "Write /tmp/a.txt" {
		t.Fatalf("unexpected hitl action mapping: %#v", second.Actions)
	}
	if len(second.ReviewConfigs) != 1 || second.ReviewConfigs[0].ActionName != "write_file" {
		t.Fatalf("unexpected review config mapping: %#v", second.ReviewConfigs)
	}

	if err := stream.SendHITLDecision(context.Background(), "interrupt-1", []ToolDecision{
		{Type: "approve"},
	}); err != nil {
		t.Fatalf("SendHITLDecision returned error: %v", err)
	}
	if err := stream.SendCancel(context.Background(), "user canceled"); err != nil {
		t.Fatalf("SendCancel returned error: %v", err)
	}

	third := <-stream.Events()
	if third.Type != AgentEventTypeToolCallStart ||
		third.ToolName != "write_file" ||
		third.ToolCallID != "tool-1" {
		t.Fatalf("unexpected third event: %#v", third)
	}
	if !payloadContains(t, third.Payload, "path", "/tmp/a.txt") {
		t.Fatalf("unexpected third payload: %s", string(third.Payload))
	}

	fourth := <-stream.Events()
	if fourth.Type != AgentEventTypeToolResult || fourth.Text != "ok" {
		t.Fatalf("unexpected fourth event: %#v", fourth)
	}
	if !payloadContains(t, fourth.Payload, "written", true) {
		t.Fatalf("unexpected fourth payload: %s", string(fourth.Payload))
	}

	fifth := <-stream.Events()
	if fifth.Type != AgentEventTypeRunCanceled || fifth.Reason != "user canceled" {
		t.Fatalf("unexpected fifth event: %#v", fifth)
	}

	if server.receivedRunRequest == nil || server.receivedRunRequest.GetAgentName() != "assistant" {
		t.Fatalf("unexpected initial run request: %#v", server.receivedRunRequest)
	}
	if server.receivedHITLDecision == nil || server.receivedHITLDecision.GetInterruptId() != "interrupt-1" {
		t.Fatalf("unexpected hitl decision: %#v", server.receivedHITLDecision)
	}
	if server.receivedCancel == nil || server.receivedCancel.GetReason() != "user canceled" {
		t.Fatalf("unexpected cancel request: %#v", server.receivedCancel)
	}
}

func TestGRPCClientRunTelemetryStream(t *testing.T) {
	server := &testRuntimeServer{}
	client, cleanup := newTestClient(t, server)
	defer cleanup()

	stream, err := client.OpenRunTelemetry(context.Background(), domain.RunRequest{
		AgentName: "assistant",
		Message:   "hello telemetry",
		ThreadID:  "thread-telemetry-1",
		Metadata:  map[string]string{"timeout_seconds": "30"},
	})
	if err != nil {
		t.Fatalf("OpenRunTelemetry returned error: %v", err)
	}
	defer stream.Close()

	first := <-stream.Events()
	if first.StreamMode != "lifecycle" || first.EventType != "run_started" {
		t.Fatalf("unexpected first telemetry event: %#v", first)
	}
	if first.EventID != "run-telemetry-1:1:1" || first.Attempt != 1 || first.Seq != 1 || first.NodeName != "run" {
		t.Fatalf("unexpected first telemetry identifiers: %#v", first)
	}
	if first.PublicEvent == nil || first.PublicEvent.ThreadID != "thread-telemetry-1" {
		t.Fatalf("unexpected first telemetry public event: %#v", first.PublicEvent)
	}

	second := <-stream.Events()
	if second.StreamMode != "messages" || second.EventType != "reasoning" {
		t.Fatalf("unexpected second telemetry event: %#v", second)
	}
	if len(second.Namespace) != 1 || second.Namespace[0] != "task:research" {
		t.Fatalf("unexpected second telemetry namespace: %#v", second.Namespace)
	}
	if !payloadContains(t, second.Metadata, "langgraph_node", "planner") {
		t.Fatalf("unexpected second telemetry metadata: %s", string(second.Metadata))
	}
	if !payloadContains(t, second.Payload, "summary", []any{map[string]any{"type": "summary_text", "text": "thinking..."}}) {
		t.Fatalf("unexpected second telemetry payload: %s", string(second.Payload))
	}
	if second.MessageID != "msg-1" || second.ModelCallID != "msg-1" || second.NodeName != "planner" {
		t.Fatalf("unexpected second telemetry identifiers: %#v", second)
	}

	third := <-stream.Events()
	if third.StreamMode != "debug" || third.EventType != "task" {
		t.Fatalf("unexpected third telemetry event: %#v", third)
	}
	if !payloadContains(t, third.Metadata, "step", float64(2)) {
		t.Fatalf("unexpected third telemetry metadata: %s", string(third.Metadata))
	}
	if third.TaskID != "task-1" || third.Seq != 3 {
		t.Fatalf("unexpected third telemetry identifiers: %#v", third)
	}

	fourth := <-stream.Events()
	if fourth.EventType != "hitl_request" || fourth.PublicEvent == nil || fourth.PublicEvent.InterruptID != "interrupt-1" {
		t.Fatalf("unexpected fourth telemetry event: %#v", fourth)
	}
	if len(fourth.PublicEvent.Actions) != 1 || fourth.PublicEvent.Actions[0].Name != "write_file" {
		t.Fatalf("unexpected telemetry HITL action mapping: %#v", fourth.PublicEvent)
	}

	if err := stream.SendHITLDecision(context.Background(), "interrupt-1", []ToolDecision{
		{Type: "approve"},
	}); err != nil {
		t.Fatalf("telemetry SendHITLDecision returned error: %v", err)
	}
	if err := stream.SendCancel(context.Background(), "stop telemetry"); err != nil {
		t.Fatalf("telemetry SendCancel returned error: %v", err)
	}

	fifth := <-stream.Events()
	if fifth.EventType != "run_canceled" || fifth.PublicEvent == nil || fifth.PublicEvent.Reason != "stop telemetry" {
		t.Fatalf("unexpected fifth telemetry event: %#v", fifth)
	}

	if server.receivedTelemetryRun == nil || server.receivedTelemetryRun.GetAgentName() != "assistant" {
		t.Fatalf("unexpected telemetry run request: %#v", server.receivedTelemetryRun)
	}
	if server.receivedTelemetryHITL == nil || server.receivedTelemetryHITL.GetInterruptId() != "interrupt-1" {
		t.Fatalf("unexpected telemetry hitl decision: %#v", server.receivedTelemetryHITL)
	}
	if server.receivedTelemetryCancel == nil || server.receivedTelemetryCancel.GetReason() != "stop telemetry" {
		t.Fatalf("unexpected telemetry cancel request: %#v", server.receivedTelemetryCancel)
	}
}

func TestGRPCClientMapsNotFound(t *testing.T) {
	client, cleanup := newTestClient(t, &testRuntimeServer{})
	defer cleanup()

	if _, err := client.GetSession(context.Background(), domain.SessionLocator{
		AgentName: "assistant",
		ThreadID:  "missing",
	}); err == nil || err != ErrNotFound {
		t.Fatalf("expected GetSession ErrNotFound, got %v", err)
	}
	if _, err := client.GetLatestSession(context.Background(), "assistant"); err == nil || err != ErrNotFound {
		t.Fatalf("expected GetLatestSession ErrNotFound, got %v", err)
	}
	if err := client.DeleteSession(context.Background(), domain.SessionLocator{
		AgentName: "assistant",
		ThreadID:  "missing",
	}); err == nil || err != ErrNotFound {
		t.Fatalf("expected DeleteSession ErrNotFound, got %v", err)
	}
	if _, _, err := client.GetSessionMessages(context.Background(), domain.SessionMessageQuery{
		AgentName: "assistant",
		ThreadID:  "missing",
		Mode:      domain.SessionHistoryModeResumeView,
		PageSize:  20,
	}); err == nil || !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected GetSessionMessages error, got %v", err)
	}
}

func newTestClient(t *testing.T, server *testRuntimeServer) (*GRPCClient, func()) {
	t.Helper()

	listener := bufconn.Listen(1024 * 1024)
	grpcServer := grpc.NewServer()
	runtimev1.RegisterResourceSyncServer(grpcServer, &resourceSyncCaptureServer{server})
	runtimev1.RegisterAgentExecutorServer(grpcServer, server)
	runtimev1.RegisterAgentTelemetryServer(grpcServer, server)
	runtimev1.RegisterSessionQueryServer(grpcServer, server)

	go func() {
		_ = grpcServer.Serve(listener)
	}()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	client, err := NewGRPCClient(
		ctx,
		"bufnet",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) {
			return listener.Dial()
		}),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	cancel()
	if err != nil {
		listener.Close()
		grpcServer.Stop()
		t.Fatalf("failed to create gRPC client: %v", err)
	}

	cleanup := func() {
		_ = client.Close()
		grpcServer.Stop()
		_ = listener.Close()
	}
	return client, cleanup
}

type resourceSyncCaptureServer struct {
	*testRuntimeServer
}

func (s *resourceSyncCaptureServer) SyncAgentSpec(
	_ context.Context,
	request *runtimev1.SyncAgentSpecRequest,
) (*runtimev1.SyncResponse, error) {
	s.syncAgentSpecRequest = request
	if s.syncAgentSpecResponse == nil {
		return &runtimev1.SyncResponse{Ok: true}, nil
	}
	return s.syncAgentSpecResponse, nil
}

func mustStruct(t *testing.T, value map[string]any) *structpb.Struct {
	t.Helper()

	return mustStructValue(value)
}

func mustStructValue(value map[string]any) *structpb.Struct {
	result, err := structpb.NewStruct(value)
	if err != nil {
		panic(err)
	}
	return result
}

func mustValueValue(value any) *structpb.Value {
	result, err := structpb.NewValue(value)
	if err != nil {
		panic(err)
	}
	return result
}

func payloadContains(t *testing.T, payload json.RawMessage, key string, expected any) bool {
	t.Helper()

	if len(payload) == 0 {
		return false
	}

	var decoded map[string]any
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}

	value, ok := decoded[key]
	if !ok {
		return false
	}
	return reflect.DeepEqual(value, expected)
}
