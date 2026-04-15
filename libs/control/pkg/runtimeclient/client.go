package runtimeclient

import (
	"context"
	"encoding/json"
	"io"
	"time"

	"agentctl/pkg/domain"
)

// SyncResponse 表示 ResourceSync 的通用响应。
type SyncResponse struct {
	OK      bool
	Message string
}

// AssembleResponse 表示 compile 动作的 southbound 响应。
type AssembleResponse struct {
	OK      bool
	Message string
	Status  string
}

// HealthAgent captures one runtime-side agent health snapshot.
type HealthAgent struct {
	Name              string
	Version           string
	Description       string
	Tags              []string
	Status            domain.ObservedRuntimeState
	ActiveThreadCount int32
	ActiveThreadIDs   []string
	LastInvokedAt     time.Time
}

// HealthResponse 表示 data plane 健康状态快照。
type HealthResponse struct {
	Status              string
	AssembledAgentCount int32
	InstalledAgentCount int32
	RunningAgentCount   int32
	RunningThreadCount  int32
	UptimeSeconds       float32
	Ready               bool
	Agents              []HealthAgent
}

// Action 表示一条可执行或可编辑的动作。
type Action struct {
	Name      string
	Arguments json.RawMessage
}

// Decision 表示一条 HITL decision。
type Decision struct {
	Type         string
	Message      string
	EditedAction *Action
}

// ToolDecision 保留为兼容别名，语义已收敛到通用 Decision。
type ToolDecision = Decision

// ActionRequest 表示一条待审批的工具动作。
type ActionRequest struct {
	Name        string
	Description string
	Arguments   json.RawMessage
}

// ReviewConfig 表示一条动作审批策略。
type ReviewConfig struct {
	ActionName       string
	AllowedDecisions []string
	ArgsSchema       json.RawMessage
}

// AgentEventType 表示 southbound stream 事件类型。
type AgentEventType string

const (
	AgentEventTypeRunStarted    AgentEventType = "run_started"
	AgentEventTypeTextDelta     AgentEventType = "text_delta"
	AgentEventTypeTextDone      AgentEventType = "text_done"
	AgentEventTypeToolCallStart AgentEventType = "tool_call_start"
	AgentEventTypeToolCallDone  AgentEventType = "tool_call_done"
	AgentEventTypeToolResult    AgentEventType = "tool_result"
	AgentEventTypeHITLRequest   AgentEventType = "hitl_request"
	AgentEventTypeRunEnded      AgentEventType = "run_ended"
	AgentEventTypeRunCanceled   AgentEventType = "run_canceled"
	AgentEventTypeError         AgentEventType = "error"
)

// AgentEvent 是 control layer 侧的运行流事件视图。
type AgentEvent struct {
	Type          AgentEventType
	RunID         string
	AgentName     string
	Timestamp     time.Time
	ThreadID      string
	Text          string
	ToolName      string
	ToolCallID    string
	InterruptID   string
	Reason        string
	ErrorMessage  string
	Payload       json.RawMessage
	Actions       []ActionRequest
	ReviewConfigs []ReviewConfig
}

// TelemetryEventRetention controls whether one telemetry event should be persisted.
type TelemetryEventRetention string

const (
	TelemetryEventRetentionUnspecified TelemetryEventRetention = ""
	TelemetryEventRetentionDurable     TelemetryEventRetention = "durable"
	TelemetryEventRetentionStreamOnly  TelemetryEventRetention = "stream_only"
)

// TelemetryEvent captures one audit-grade runtime event.
type TelemetryEvent struct {
	RunID         string
	ThreadID      string
	AgentName     string
	Timestamp     time.Time
	SchemaVersion uint32
	Retention     TelemetryEventRetention
	EventID       string
	Attempt       int32
	Seq           int64
	Namespace     []string
	StreamMode    string
	EventType     string
	NodeName      string
	TaskID        string
	ModelCallID   string
	ToolCallID    string
	InterruptID   string
	MessageID     string
	Metadata      json.RawMessage
	Payload       json.RawMessage
}

// ShouldPersistTelemetryEvent returns whether the event belongs in the durable audit store.
func ShouldPersistTelemetryEvent(event TelemetryEvent) bool {
	return event.Retention != TelemetryEventRetentionStreamOnly
}

// RunStream 表示一条已建立的 southbound 运行流。
type RunStream interface {
	Events() <-chan AgentEvent
	SendHITLDecision(ctx context.Context, interruptID string, decisions []ToolDecision) error
	SendCancel(ctx context.Context, reason string) error
	Close() error
}

// TelemetryStream represents one telemetry-grade southbound run stream.
type TelemetryStream interface {
	Events() <-chan TelemetryEvent
	SendHITLDecision(ctx context.Context, interruptID string, decisions []ToolDecision) error
	SendCancel(ctx context.Context, reason string) error
	Close() error
}

// ResourceSyncClient 封装 install / compile / uninstall / health 动作。
type ResourceSyncClient interface {
	SyncAgentSpec(ctx context.Context, spec domain.RuntimeAgentSpec) (SyncResponse, error)
	Assemble(ctx context.Context, agentName string) (AssembleResponse, error)
	GetAgentGraph(ctx context.Context, agentName string, xrayDepth int32) (json.RawMessage, error)
	UploadWorkspaceFiles(ctx context.Context, req domain.WorkspaceUploadRequest) (domain.WorkspaceUploadResponse, error)
	DownloadWorkspaceFile(ctx context.Context, req domain.WorkspaceFileDownloadRequest, writer io.Writer) error
	ListWorkspaceFiles(ctx context.Context, req domain.WorkspaceListRequest) (domain.WorkspaceListResponse, error)
	RemoveAgent(ctx context.Context, agentName string) (SyncResponse, error)
	Health(ctx context.Context) (HealthResponse, error)
}

// AgentExecutorClient 封装 southbound Run 双向流。
type AgentExecutorClient interface {
	OpenRun(ctx context.Context, req domain.RunRequest) (RunStream, error)
}

// AgentTelemetryClient wraps the southbound telemetry run stream.
type AgentTelemetryClient interface {
	OpenRunTelemetry(ctx context.Context, req domain.RunRequest) (TelemetryStream, error)
}

// SessionQueryClient 封装 session 相关 southbound 查询。
type SessionQueryClient interface {
	ListSessions(ctx context.Context, agentName string, pageSize int32, pageToken string) ([]domain.SessionSummary, string, error)
	GetSession(ctx context.Context, locator domain.SessionLocator) (domain.SessionSummary, error)
	GetSessionMessagePage(ctx context.Context, query domain.SessionMessageQuery) (domain.SessionMessagePage, error)
	GetSessionMessages(ctx context.Context, query domain.SessionMessageQuery) ([]domain.SessionMessage, string, error)
	GetLatestSession(ctx context.Context, agentName string) (domain.SessionSummary, error)
	DeleteSession(ctx context.Context, locator domain.SessionLocator) error
	ListThreadArtifacts(ctx context.Context, req domain.ListArtifactsRequest) (domain.ListArtifactsResponse, error)
}
