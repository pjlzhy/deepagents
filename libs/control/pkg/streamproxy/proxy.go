package streamproxy

import (
	"agentctl/pkg/runtimeclient"
	"context"
)

// Downstream 表示 northbound 流式消费者。
type Downstream interface {
	SendEvent(ctx context.Context, event runtimeclient.AgentEvent) error
}

// Proxy 负责把 southbound run stream 转发给 northbound 消费者。
type Proxy interface {
	Proxy(ctx context.Context, upstream runtimeclient.RunStream, downstream Downstream) error
}
