package domain

// AuthoredStatus 表示 control layer 中 authored resource 的状态。
type AuthoredStatus string

const (
	AuthoredStatusDraft     AuthoredStatus = "draft"
	AuthoredStatusPublished AuthoredStatus = "published"
	AuthoredStatusDeleted   AuthoredStatus = "deleted"
)

// Valid 返回 authored 状态是否合法。
func (s AuthoredStatus) Valid() bool {
	switch s {
	case AuthoredStatusDraft, AuthoredStatusPublished, AuthoredStatusDeleted:
		return true
	default:
		return false
	}
}

// DesiredDeploymentState 表示 control layer 想要达成的 runtime 状态。
type DesiredDeploymentState string

const (
	DesiredDeploymentStateInstalled DesiredDeploymentState = "installed"
	DesiredDeploymentStateCompiled  DesiredDeploymentState = "compiled"
)

// Valid 返回 desired deployment 状态是否合法。
func (s DesiredDeploymentState) Valid() bool {
	switch s {
	case DesiredDeploymentStateInstalled, DesiredDeploymentStateCompiled:
		return true
	default:
		return false
	}
}

// ObservedRuntimeState 表示从 data plane 观察到的运行时状态。
type ObservedRuntimeState string

const (
	ObservedRuntimeStateUnknown   ObservedRuntimeState = "unknown"
	ObservedRuntimeStateAbsent    ObservedRuntimeState = "absent"
	ObservedRuntimeStateInstalled ObservedRuntimeState = "installed"
	ObservedRuntimeStateCompiled  ObservedRuntimeState = "compiled"
	ObservedRuntimeStateRunning   ObservedRuntimeState = "running"
	ObservedRuntimeStateDegraded  ObservedRuntimeState = "degraded"
)

// Valid 返回 observed runtime 状态是否合法。
func (s ObservedRuntimeState) Valid() bool {
	switch s {
	case ObservedRuntimeStateUnknown,
		ObservedRuntimeStateAbsent,
		ObservedRuntimeStateInstalled,
		ObservedRuntimeStateCompiled,
		ObservedRuntimeStateRunning,
		ObservedRuntimeStateDegraded:
		return true
	default:
		return false
	}
}
