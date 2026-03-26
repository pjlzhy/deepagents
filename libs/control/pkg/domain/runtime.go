package domain

import (
	"encoding/json"
	"time"
)

// RuntimeTargetKind represents one southbound runtime endpoint kind.
type RuntimeTargetKind string

const (
	RuntimeTargetKindLocalGRPC  RuntimeTargetKind = "local_grpc"
	RuntimeTargetKindRemoteGRPC RuntimeTargetKind = "remote_grpc"
	RuntimeTargetKindKubernetes RuntimeTargetKind = "kubernetes"
)

// RuntimeTarget describes one data plane endpoint.
type RuntimeTarget struct {
	Name        string
	Kind        RuntimeTargetKind
	Endpoint    string
	Description string
	Metadata    map[string]string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// Deployment describes one agent-to-runtime-target binding.
type Deployment struct {
	AgentName     string
	TargetName    string
	DesiredState  DesiredDeploymentState
	ObservedState ObservedRuntimeState
	UpdatedAt     time.Time
}

// ResolvedAgentInput contains the authored resources needed by the packager.
type ResolvedAgentInput struct {
	Agent      AuthoredAgentSpec
	Skills     []Skill
	MCPConfigs []MCPConfig
	Target     RuntimeTarget
}

// RunRequest is shared across northbound and southbound run flows.
type RunRequest struct {
	AgentName string
	Message   string
	ThreadID  string
	Metadata  map[string]string
}

// SessionHistoryMode describes one session-history view mode.
type SessionHistoryMode string

const (
	SessionHistoryModeResumeView     SessionHistoryMode = "resume_view"
	SessionHistoryModeFullTranscript SessionHistoryMode = "full_transcript"
)

// SessionMessageRole describes one session-message role.
type SessionMessageRole string

const (
	SessionMessageRoleSystem SessionMessageRole = "system"
	SessionMessageRoleHuman  SessionMessageRole = "human"
	SessionMessageRoleAI     SessionMessageRole = "ai"
	SessionMessageRoleTool   SessionMessageRole = "tool"
)

// SessionSummary describes one runtime session summary.
type SessionSummary struct {
	ThreadID           string
	AgentName          string
	LatestCheckpointID string
	MessageCount       int32
	CheckpointCount    int32
	InitialPrompt      string
	HistoryMode        SessionHistoryMode
	AgentStatus        ObservedRuntimeState
	UpdatedAt          time.Time
}

// SessionMessage describes one session-history message.
type SessionMessage struct {
	Index        int32
	CheckpointID string
	Role         SessionMessageRole
	Text         string
	Content      string
	ToolCallID   string
	ToolName     string
	IsError      bool
	Raw          json.RawMessage
	CreatedAt    time.Time
}

// SessionMessageQuery describes one paged session-history query.
type SessionMessageQuery struct {
	ThreadID     string
	CheckpointID string
	Mode         SessionHistoryMode
	PageSize     int32
	PageToken    string
	IncludeRaw   bool
}

// SessionMessagePage captures one paged checkpoint-backed session-history result.
type SessionMessagePage struct {
	ThreadID             string
	ResolvedCheckpointID string
	ActualMode           SessionHistoryMode
	TotalMessageCount    int32
	Messages             []SessionMessage
	NextPageToken        string
}
