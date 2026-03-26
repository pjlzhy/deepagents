package domain

import "time"

// OperationKind 表示 control layer 的编排动作。
type OperationKind string

const (
	OperationKindInstall OperationKind = "install"
	OperationKindCompile OperationKind = "compile"
	OperationKindExecute OperationKind = "execute"
	OperationKindCancel  OperationKind = "cancel"
	OperationKindDelete  OperationKind = "delete"
	OperationKindQuery   OperationKind = "query"
)

// OperationStatus 表示编排动作状态。
type OperationStatus string

const (
	OperationStatusPending   OperationStatus = "pending"
	OperationStatusSucceeded OperationStatus = "succeeded"
	OperationStatusFailed    OperationStatus = "failed"
)

// Operation 表示一条 control plane 审计记录。
type Operation struct {
	ID           string
	AgentName    string
	TargetName   string
	Kind         OperationKind
	Status       OperationStatus
	ErrorMessage string
	CreatedAt    time.Time
	UpdatedAt    time.Time
}
