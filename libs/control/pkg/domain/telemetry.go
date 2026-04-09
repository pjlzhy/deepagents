package domain

import (
	"encoding/json"
	"time"
)

// TelemetryRunStatus describes one persisted telemetry run state.
type TelemetryRunStatus string

const (
	TelemetryRunStatusPending   TelemetryRunStatus = "pending"
	TelemetryRunStatusRunning   TelemetryRunStatus = "running"
	TelemetryRunStatusCompleted TelemetryRunStatus = "completed"
	TelemetryRunStatusCanceled  TelemetryRunStatus = "canceled"
	TelemetryRunStatusFailed    TelemetryRunStatus = "failed"
)

// TelemetryRun captures one persisted telemetry run summary.
type TelemetryRun struct {
	RunID             string
	AgentName         string
	ThreadID          string
	TurnIndex         int32
	StartCheckpointID string
	EndCheckpointID   string
	RuntimeTarget     string
	Status            TelemetryRunStatus
	RequestMetadata   json.RawMessage
	TraceContext      json.RawMessage
	GraphSnapshotID   string
	ReasoningSummary  string
	NodeStepCount     int32
	ModelStepCount    int32
	ToolStepCount     int32
	HitlWaitCount     int32
	ErrorCount        int32
	EventCount        int32
	StartedAt         time.Time
	FinishedAt        time.Time
	LastEventAt       time.Time
	CreatedAt         time.Time
	UpdatedAt         time.Time
}

// TelemetryRunQuery describes one telemetry run page query with optional filters.
type TelemetryRunQuery struct {
	PageQuery
	AgentName string
	ThreadID  string
}

// TelemetryRunSnapshotPosition describes which run-bound snapshot to resolve.
type TelemetryRunSnapshotPosition string

const (
	TelemetryRunSnapshotPositionBefore TelemetryRunSnapshotPosition = "before"
	TelemetryRunSnapshotPositionAfter  TelemetryRunSnapshotPosition = "after"
)

// TelemetryEventRecord captures one persisted telemetry event.
type TelemetryEventRecord struct {
	EventID     string
	RunID       string
	AgentName   string
	Attempt     int32
	Seq         int64
	Timestamp   time.Time
	Namespace   []string
	StreamMode  string
	EventType   string
	NodeName    string
	TaskID      string
	ModelCallID string
	ToolCallID  string
	InterruptID string
	MessageID   string
	Metadata    json.RawMessage
	Payload     json.RawMessage
	PublicEvent json.RawMessage
	CreatedAt   time.Time
}

// TelemetryStepKind describes one projected trace step kind.
type TelemetryStepKind string

const (
	TelemetryStepKindRun   TelemetryStepKind = "run"
	TelemetryStepKindNode  TelemetryStepKind = "node"
	TelemetryStepKindModel TelemetryStepKind = "model"
	TelemetryStepKindTool  TelemetryStepKind = "tool"
	TelemetryStepKindHITL  TelemetryStepKind = "hitl"
)

// TelemetryStepStatus describes one projected trace step status.
type TelemetryStepStatus string

const (
	TelemetryStepStatusRunning     TelemetryStepStatus = "running"
	TelemetryStepStatusCompleted   TelemetryStepStatus = "completed"
	TelemetryStepStatusFailed      TelemetryStepStatus = "failed"
	TelemetryStepStatusInterrupted TelemetryStepStatus = "interrupted"
	TelemetryStepStatusObserved    TelemetryStepStatus = "observed"
)

// TelemetryStep captures one control-projected trace step.
type TelemetryStep struct {
	StepID             string
	RunID              string
	ParentStepID       string
	Kind               TelemetryStepKind
	Title              string
	Namespace          []string
	Status             TelemetryStepStatus
	StartedAt          time.Time
	FinishedAt         time.Time
	Depth              int32
	Step               int32
	TaskID             string
	ModelCallID        string
	ToolCallID         string
	InterruptID        string
	MessageID          string
	Input              json.RawMessage
	Output             json.RawMessage
	Error              string
	Triggers           []string
	Reasoning          []string
	ReasoningEncrypted bool
	Messages           []string
	ToolCalls          []string
	Updates            []json.RawMessage
	Custom             []json.RawMessage
	RelatedEventIDs    []string
	Order              int32
	Synthetic          bool
}
