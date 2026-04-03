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
	Agent            AuthoredAgentSpec
	ModelConfig      ModelConfig
	Skills           []Skill
	MCPConfigs       []MCPConfig
	SandboxConfig    *SandboxConfig
	Target           RuntimeTarget
	SubagentResolved map[string]ResolvedSubagentInput // keyed by subagent name
}

// ResolvedSubagentInput contains resolved resources for a single subagent.
type ResolvedSubagentInput struct {
	ModelConfig *ModelConfig // nil = inherit main agent model
	Skills      []Skill
}

// RunRequest is shared across northbound and southbound run flows.
type RunRequest struct {
	AgentName string
	Message   string
	ThreadID  string
	Metadata  map[string]string
}

// WorkspaceUploadFile describes one file staged into a thread workspace.
type WorkspaceUploadFile struct {
	Path    string
	Content []byte
}

// WorkspaceUploadRequest is shared across northbound and southbound upload flows.
type WorkspaceUploadRequest struct {
	AgentName string
	ThreadID  string
	Files     []WorkspaceUploadFile
}

// WorkspaceUploadResult captures one uploaded file outcome.
type WorkspaceUploadResult struct {
	Path  string
	Error string
}

// WorkspaceUploadResponse reports the resolved thread and per-file results.
type WorkspaceUploadResponse struct {
	ThreadID string
	Files    []WorkspaceUploadResult
}

// WorkspaceDownloadRequest is shared across northbound and southbound download flows.
type WorkspaceDownloadRequest struct {
	AgentName string
	ThreadID  string
	Paths     []string
}

// WorkspaceDownloadResult captures one downloaded file outcome.
type WorkspaceDownloadResult struct {
	Path    string
	Content []byte
	Error   string
}

// WorkspaceDownloadResponse reports the resolved thread and per-file results.
type WorkspaceDownloadResponse struct {
	ThreadID string
	Files    []WorkspaceDownloadResult
}

// WorkspaceListRequest is shared across northbound and southbound list flows.
type WorkspaceListRequest struct {
	AgentName string
	ThreadID  string
	Path      string
}

// WorkspaceFileInfo describes one file entry in a workspace directory listing.
type WorkspaceFileInfo struct {
	Path       string
	IsDir      bool
	Size       int64
	ModifiedAt string
}

// WorkspaceListResponse reports the resolved thread and directory entries.
type WorkspaceListResponse struct {
	ThreadID string
	Files    []WorkspaceFileInfo
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

// SessionLocator identifies one session within one agent namespace.
type SessionLocator struct {
	AgentName string
	ThreadID  string
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
	AgentName    string
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

// ThreadArtifact describes one artifact produced by an agent within a thread.
type ThreadArtifact struct {
	ID            string
	Type          string
	Path          string
	Title         string
	ContentType   string
	Language      string
	CreatedByTool string
	CreatedAt     string
	ModifiedAt    string
	Size          int64
}

// ListArtifactsRequest identifies the thread to query for artifacts.
type ListArtifactsRequest struct {
	ThreadID  string
	AgentName string
}

// ListArtifactsResponse carries the artifact list for one thread.
type ListArtifactsResponse struct {
	ThreadID  string
	Artifacts []ThreadArtifact
}
