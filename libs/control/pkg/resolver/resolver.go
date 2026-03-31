package resolver

import (
	"agentctl/pkg/domain"
	"agentctl/pkg/registry"
	"context"
	"errors"
)

// Resolver 负责把 authored resources 解析成 packager 可消费的聚合输入。
type Resolver interface {
	ResolveAgent(ctx context.Context, agentName string) (domain.ResolvedAgentInput, error)
}

// RegistryResolver 基于 registry 聚合 authored resources。
type RegistryResolver struct {
	registry registry.Registry
}

// NewRegistryResolver 创建一个新的 registry-backed resolver。
func NewRegistryResolver(reg registry.Registry) (*RegistryResolver, error) {
	if reg == nil {
		return nil, errors.New("registry must not be nil")
	}
	return &RegistryResolver{registry: reg}, nil
}

// ResolveAgent 解析一个 agent 的依赖技能、MCP 配置和 runtime target。
func (r *RegistryResolver) ResolveAgent(
	ctx context.Context,
	agentName string,
) (domain.ResolvedAgentInput, error) {
	agent, err := r.registry.GetAgentSpec(ctx, agentName)
	if err != nil {
		return domain.ResolvedAgentInput{}, err
	}
	modelConfig, err := r.registry.GetModelConfig(ctx, agent.ModelRef)
	if err != nil {
		return domain.ResolvedAgentInput{}, err
	}

	skills := make([]domain.Skill, 0, len(agent.SkillRefs))
	for _, name := range agent.SkillRefs {
		skill, err := r.registry.GetSkill(ctx, name)
		if err != nil {
			return domain.ResolvedAgentInput{}, err
		}
		skills = append(skills, skill)
	}

	mcpConfigs := make([]domain.MCPConfig, 0, len(agent.MCPRefs))
	for _, name := range agent.MCPRefs {
		config, err := r.registry.GetMCPConfig(ctx, name)
		if err != nil {
			return domain.ResolvedAgentInput{}, err
		}
		mcpConfigs = append(mcpConfigs, config)
	}

	var sandboxConfig *domain.SandboxConfig
	if agent.SandboxRef != "" {
		resolvedSandbox, err := r.registry.GetSandboxConfig(ctx, agent.SandboxRef)
		if err != nil {
			return domain.ResolvedAgentInput{}, err
		}
		sandboxConfig = &resolvedSandbox
	}

	return domain.ResolvedAgentInput{
		Agent:         agent,
		ModelConfig:   modelConfig,
		Skills:        skills,
		MCPConfigs:    mcpConfigs,
		SandboxConfig: sandboxConfig,
	}, nil
}
