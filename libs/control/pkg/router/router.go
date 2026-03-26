package router

import (
	"agentctl/pkg/domain"
	"context"
)

// Router 负责把 agent 映射到 data plane runtime target。
type Router interface {
	ResolveTarget(ctx context.Context, agentName string) (domain.RuntimeTarget, error)
}
