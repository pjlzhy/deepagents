package registry

import (
	"agentctl/pkg/domain"
	"context"
)

// Registry 定义 control layer authoritative resource registry。
type Registry interface {
	UpsertSkill(ctx context.Context, skill domain.Skill) error
	GetSkill(ctx context.Context, name string) (domain.Skill, error)
	ListSkills(ctx context.Context) ([]domain.Skill, error)
	DeleteSkill(ctx context.Context, name string) error

	UpsertMCPConfig(ctx context.Context, config domain.MCPConfig) error
	GetMCPConfig(ctx context.Context, name string) (domain.MCPConfig, error)
	ListMCPConfigs(ctx context.Context) ([]domain.MCPConfig, error)
	DeleteMCPConfig(ctx context.Context, name string) error

	UpsertAgentSpec(ctx context.Context, spec domain.AuthoredAgentSpec) error
	GetAgentSpec(ctx context.Context, name string) (domain.AuthoredAgentSpec, error)
	ListAgentSpecs(ctx context.Context) ([]domain.AuthoredAgentSpec, error)
	DeleteAgentSpec(ctx context.Context, name string) error

	UpsertDeployment(ctx context.Context, deployment domain.Deployment) error
	GetDeployment(ctx context.Context, agentName string) (domain.Deployment, error)

	UpsertRuntimeTarget(ctx context.Context, target domain.RuntimeTarget) error
	GetRuntimeTarget(ctx context.Context, name string) (domain.RuntimeTarget, error)
	ListRuntimeTargets(ctx context.Context) ([]domain.RuntimeTarget, error)

	CreateOperation(ctx context.Context, operation domain.Operation) error
}
