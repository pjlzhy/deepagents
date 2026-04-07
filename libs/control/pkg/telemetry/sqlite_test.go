package telemetry

import (
	"context"
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	"agentctl/pkg/domain"
	"agentctl/pkg/runtimeclient"
	"agentctl/pkg/store"
)

func TestSQLiteStoreRecordsRunsAndEvents(t *testing.T) {
	ctx := context.Background()
	sqliteStore, err := store.OpenSQLite(ctx, store.SQLiteConfig{Path: filepath.Join(t.TempDir(), "telemetry.sqlite")})
	if err != nil {
		t.Fatalf("open sqlite store: %v", err)
	}
	defer func() { _ = sqliteStore.Close() }()

	telemetryStore, err := NewSQLiteStore(sqliteStore.DB())
	if err != nil {
		t.Fatalf("new telemetry store: %v", err)
	}

	startedAt := time.Unix(1710000000, 0).UTC()
	finishedAt := startedAt.Add(2 * time.Second)

	started := runtimeclient.TelemetryEvent{
		RunID:      "run-1",
		AgentName:  "assistant",
		Timestamp:  startedAt,
		EventID:    "run-1:1:1",
		Attempt:    1,
		Seq:        1,
		StreamMode: "lifecycle",
		EventType:  "run_started",
		NodeName:   "run",
		PublicEvent: &runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeRunStarted,
			RunID:     "run-1",
			AgentName: "assistant",
			ThreadID:  "thread-1",
			Timestamp: startedAt,
		},
	}
	if err := telemetryStore.RecordEvent(ctx, started); err != nil {
		t.Fatalf("record started event: %v", err)
	}

	finished := runtimeclient.TelemetryEvent{
		RunID:      "run-1",
		AgentName:  "assistant",
		Timestamp:  finishedAt,
		EventID:    "run-1:1:2",
		Attempt:    1,
		Seq:        2,
		StreamMode: "lifecycle",
		EventType:  "run_ended",
		NodeName:   "run",
		Payload:    json.RawMessage(`{"stats":{"request_count":1}}`),
	}
	if err := telemetryStore.RecordEvent(ctx, finished); err != nil {
		t.Fatalf("record finished event: %v", err)
	}

	run, err := telemetryStore.GetRun(ctx, "run-1")
	if err != nil {
		t.Fatalf("get run: %v", err)
	}
	if run.Status != domain.TelemetryRunStatusCompleted {
		t.Fatalf("unexpected run status: %s", run.Status)
	}
	if run.ThreadID != "thread-1" {
		t.Fatalf("unexpected thread_id: %q", run.ThreadID)
	}
	if run.EventCount != 2 {
		t.Fatalf("unexpected event count: %d", run.EventCount)
	}

	page, err := telemetryStore.ListEvents(ctx, "run-1", domain.PageQuery{PageSize: 10, PageNumber: 1})
	if err != nil {
		t.Fatalf("list events: %v", err)
	}
	if len(page.Items) != 2 {
		t.Fatalf("unexpected event page size: %d", len(page.Items))
	}
	if page.Items[0].EventID != "run-1:1:1" || page.Items[1].EventID != "run-1:1:2" {
		t.Fatalf("unexpected event ids: %#v", page.Items)
	}

	runsPage, err := telemetryStore.ListRuns(ctx, domain.PageQuery{PageSize: 10, PageNumber: 1})
	if err != nil {
		t.Fatalf("list runs: %v", err)
	}
	if len(runsPage.Items) != 1 || runsPage.Items[0].RunID != "run-1" {
		t.Fatalf("unexpected runs page: %#v", runsPage.Items)
	}
}

func TestSQLiteStoreDeduplicatesEventsByEventID(t *testing.T) {
	ctx := context.Background()
	sqliteStore, err := store.OpenSQLite(ctx, store.SQLiteConfig{Path: filepath.Join(t.TempDir(), "telemetry.sqlite")})
	if err != nil {
		t.Fatalf("open sqlite store: %v", err)
	}
	defer func() { _ = sqliteStore.Close() }()

	telemetryStore, err := NewSQLiteStore(sqliteStore.DB())
	if err != nil {
		t.Fatalf("new telemetry store: %v", err)
	}

	event := runtimeclient.TelemetryEvent{
		RunID:      "run-dedup",
		AgentName:  "assistant",
		Timestamp:  time.Unix(1710000000, 0).UTC(),
		EventID:    "run-dedup:1:1",
		Attempt:    1,
		Seq:        1,
		StreamMode: "lifecycle",
		EventType:  "run_started",
		NodeName:   "run",
	}

	if err := telemetryStore.RecordEvent(ctx, event); err != nil {
		t.Fatalf("record first event: %v", err)
	}
	if err := telemetryStore.RecordEvent(ctx, event); err != nil {
		t.Fatalf("record duplicate event: %v", err)
	}

	run, err := telemetryStore.GetRun(ctx, "run-dedup")
	if err != nil {
		t.Fatalf("get run: %v", err)
	}
	if run.EventCount != 1 {
		t.Fatalf("expected deduped event count 1, got %d", run.EventCount)
	}

	eventsPage, err := telemetryStore.ListEvents(ctx, "run-dedup", domain.PageQuery{PageSize: 10, PageNumber: 1})
	if err != nil {
		t.Fatalf("list events: %v", err)
	}
	if len(eventsPage.Items) != 1 {
		t.Fatalf("expected 1 stored event, got %d", len(eventsPage.Items))
	}
}
