package runtimeclient

import (
	"context"
	"encoding/json"
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

// HealthResponse 表示 data plane 健康状态快照。
type HealthResponse struct {
	Status              string
	AssembledAgentCount int32
	InstalledAgentCount int32
	RunningAgentCount   int32
	UptimeSeconds       float32
	Ready               bool
}

// ToolDecision 表示一条 HITL decision。
type ToolDecision struct {
	ToolCallID string
	Approved   bool
	Reason     string
}

// ActionRequest 表示一条待审批的工具动作。
type ActionRequest struct {
	Action     string
	ToolCallID string
	Arguments  json.RawMessage
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
	Type         AgentEventType
	RunID        string
	AgentName    string
	Timestamp    time.Time
	ThreadID     string
	Text         string
	ToolName     string
	ToolCallID   string
	InterruptID  string
	Reason       string
	ErrorMessage string
	Payload      json.RawMessage
	Actions      []ActionRequest
}

// RunStream 表示一条已建立的 southbound 运行流。
type RunStream interface {
	Events() <-chan AgentEvent
	SendHITLDecision(ctx context.Context, interruptID string, decisions []ToolDecision) error
	SendCancel(ctx context.Context, reason string) error
	Close() error
}

// ResourceSyncClient 封装 install / compile / uninstall / health 动作。
type ResourceSyncClient interface {
	SyncAgentSpec(ctx context.Context, spec domain.RuntimeAgentSpec) (SyncResponse, error)
	Assemble(ctx context.Context, agentName string) (AssembleResponse, error)
	RemoveAgent(ctx context.Context, agentName string) (SyncResponse, error)
	Health(ctx context.Context) (HealthResponse, error)
}

// AgentExecutorClient 封装 southbound Run 双向流。
type AgentExecutorClient interface {
	OpenRun(ctx context.Context, req domain.RunRequest) (RunStream, error)
}

// SessionQueryClient 封装 session 相关 southbound 查询。
type SessionQueryClient interface {
	ListSessions(ctx context.Context, agentName string, pageSize int32, pageToken string) ([]domain.SessionSummary, string, error)
	GetSession(ctx context.Context, threadID string) (domain.SessionSummary, error)
	GetSessionMessagePage(ctx context.Context, query domain.SessionMessageQuery) (domain.SessionMessagePage, error)
	GetSessionMessages(
		ctx context.Context,
		threadID string,
		mode domain.SessionHistoryMode,
		pageSize int32,
		pageToken string,
	) ([]domain.SessionMessage, string, error)
	GetLatestSession(ctx context.Context, agentName string) (domain.SessionSummary, error)
	DeleteSession(ctx context.Context, threadID string) error
}
