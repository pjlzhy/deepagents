package registry

import (
	"agentctl/pkg/domain"
	"context"
)

// Registry 定义 control layer authoritative resource registry。
type Registry interface {
	UpsertModelConfig(ctx context.Context, config domain.ModelConfig) error
	GetModelConfig(ctx context.Context, name string) (domain.ModelConfig, error)
	ListModelConfigs(ctx context.Context) ([]domain.ModelConfig, error)
	ListModelConfigsPage(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.ModelConfig], error)
	DeleteModelConfig(ctx context.Context, name string) error

	UpsertSkill(ctx context.Context, skill domain.Skill) error
	GetSkill(ctx context.Context, name string) (domain.Skill, error)
	ListSkills(ctx context.Context) ([]domain.Skill, error)
	ListSkillsPage(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.Skill], error)
	DeleteSkill(ctx context.Context, name string) error

	UpsertMCPConfig(ctx context.Context, config domain.MCPConfig) error
	GetMCPConfig(ctx context.Context, name string) (domain.MCPConfig, error)
	ListMCPConfigs(ctx context.Context) ([]domain.MCPConfig, error)
	ListMCPConfigsPage(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.MCPConfig], error)
	DeleteMCPConfig(ctx context.Context, name string) error

	UpsertSandboxConfig(ctx context.Context, config domain.SandboxConfig) error
	GetSandboxConfig(ctx context.Context, name string) (domain.SandboxConfig, error)
	ListSandboxConfigs(ctx context.Context) ([]domain.SandboxConfig, error)
	ListSandboxConfigsPage(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.SandboxConfig], error)
	DeleteSandboxConfig(ctx context.Context, name string) error

	UpsertAgentSpec(ctx context.Context, spec domain.AuthoredAgentSpec) error
	GetAgentSpec(ctx context.Context, name string) (domain.AuthoredAgentSpec, error)
	ListAgentSpecs(ctx context.Context) ([]domain.AuthoredAgentSpec, error)
	ListAgentSpecsPage(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.AuthoredAgentSpec], error)
	DeleteAgentSpec(ctx context.Context, name string) error

	UpsertDeployment(ctx context.Context, deployment domain.Deployment) error
	GetDeployment(ctx context.Context, agentName string) (domain.Deployment, error)

	UpsertRuntimeTarget(ctx context.Context, target domain.RuntimeTarget) error
	GetRuntimeTarget(ctx context.Context, name string) (domain.RuntimeTarget, error)
	ListRuntimeTargets(ctx context.Context) ([]domain.RuntimeTarget, error)

	CreateOperation(ctx context.Context, operation domain.Operation) error
}
