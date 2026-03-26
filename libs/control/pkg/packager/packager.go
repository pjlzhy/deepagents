package packager

import (
	"agentctl/pkg/domain"
	"context"
)

// Packager 负责把 resolved authored input 打包成 runtime-ready agent spec。
type Packager interface {
	Package(ctx context.Context, input domain.ResolvedAgentInput) (domain.RuntimeAgentSpec, error)
}
