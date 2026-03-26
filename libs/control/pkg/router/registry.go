package router

import (
	"agentctl/pkg/domain"
	"agentctl/pkg/registry"
	"context"
	"errors"
	"fmt"
	"strings"
)

// RegistryRouter 基于 registry 解析 agent 到 runtime target 的映射。
type RegistryRouter struct {
	registry registry.Registry
}

// NewRegistryRouter 创建一个最小 registry-backed router。
func NewRegistryRouter(reg registry.Registry) (*RegistryRouter, error) {
	if reg == nil {
		return nil, errors.New("registry must not be nil")
	}
	return &RegistryRouter{registry: reg}, nil
}

// ResolveTarget 通过 deployment 绑定查找 agent 对应的 runtime target。
func (r *RegistryRouter) ResolveTarget(ctx context.Context, agentName string) (domain.RuntimeTarget, error) {
	deployment, err := r.registry.GetDeployment(ctx, agentName)
	if err != nil {
		return domain.RuntimeTarget{}, fmt.Errorf("get deployment for agent %q: %w", agentName, err)
	}

	targetName := strings.TrimSpace(deployment.TargetName)
	if targetName == "" {
		return domain.RuntimeTarget{}, fmt.Errorf("deployment for agent %q has empty target name", agentName)
	}

	target, err := r.registry.GetRuntimeTarget(ctx, targetName)
	if err != nil {
		return domain.RuntimeTarget{}, fmt.Errorf("get runtime target %q: %w", targetName, err)
	}
	return target, nil
}
