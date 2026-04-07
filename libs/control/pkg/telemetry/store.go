package telemetry

import (
	"context"

	"agentctl/pkg/domain"
	"agentctl/pkg/runtimeclient"
)

// Store persists telemetry facts and serves northbound history queries.
type Store interface {
	RecordEvent(ctx context.Context, event runtimeclient.TelemetryEvent) error
	ListRuns(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.TelemetryRun], error)
	GetRun(ctx context.Context, runID string) (domain.TelemetryRun, error)
	LoadEvents(ctx context.Context, runID string) ([]domain.TelemetryEventRecord, error)
	ListEvents(
		ctx context.Context,
		runID string,
		query domain.PageQuery,
	) (domain.ResourcePage[domain.TelemetryEventRecord], error)
}
