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
	if run.TurnIndex != 1 {
		t.Fatalf("unexpected turn_index: %d", run.TurnIndex)
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

	runsPage, err := telemetryStore.ListRuns(ctx, domain.TelemetryRunQuery{
		PageQuery: domain.PageQuery{PageSize: 10, PageNumber: 1},
	})
	if err != nil {
		t.Fatalf("list runs: %v", err)
	}
	if len(runsPage.Items) != 1 || runsPage.Items[0].RunID != "run-1" {
		t.Fatalf("unexpected runs page: %#v", runsPage.Items)
	}
}

func TestSQLiteStoreProjectsRunCheckpointBoundsAndFilters(t *testing.T) {
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

	checkpointAt := time.Unix(1710000001, 0).UTC()
	checkpointPayload := json.RawMessage(`{
		"config":{"configurable":{"checkpoint_id":"cp-002"}},
		"parent_config":{"configurable":{"checkpoint_id":"cp-001"}}
	}`)

	if err := telemetryStore.RecordEvent(ctx, runtimeclient.TelemetryEvent{
		RunID:      "run-checkpoint-1",
		AgentName:  "assistant",
		Timestamp:  checkpointAt,
		EventID:    "run-checkpoint-1:1:1",
		Attempt:    1,
		Seq:        1,
		StreamMode: "debug",
		EventType:  "checkpoint",
		NodeName:   "root",
		Payload:    checkpointPayload,
		PublicEvent: &runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeRunStarted,
			RunID:     "run-checkpoint-1",
			AgentName: "assistant",
			ThreadID:  "thread-a",
			Timestamp: checkpointAt,
		},
	}); err != nil {
		t.Fatalf("record checkpoint event: %v", err)
	}

	if err := telemetryStore.RecordEvent(ctx, runtimeclient.TelemetryEvent{
		RunID:      "run-checkpoint-2",
		AgentName:  "assistant",
		Timestamp:  checkpointAt.Add(time.Second),
		EventID:    "run-checkpoint-2:1:1",
		Attempt:    1,
		Seq:        1,
		StreamMode: "lifecycle",
		EventType:  "run_started",
		NodeName:   "run",
		PublicEvent: &runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeRunStarted,
			RunID:     "run-checkpoint-2",
			AgentName: "assistant",
			ThreadID:  "thread-b",
			Timestamp: checkpointAt.Add(time.Second),
		},
	}); err != nil {
		t.Fatalf("record second run event: %v", err)
	}

	run, err := telemetryStore.GetRun(ctx, "run-checkpoint-1")
	if err != nil {
		t.Fatalf("get run: %v", err)
	}
	if run.StartCheckpointID != "cp-001" || run.EndCheckpointID != "cp-002" {
		t.Fatalf("unexpected checkpoint bounds: %#v", run)
	}

	page, err := telemetryStore.ListRuns(ctx, domain.TelemetryRunQuery{
		PageQuery: domain.PageQuery{PageSize: 10, PageNumber: 1},
		ThreadID:  "thread-a",
	})
	if err != nil {
		t.Fatalf("list runs by thread: %v", err)
	}
	if len(page.Items) != 1 || page.Items[0].RunID != "run-checkpoint-1" {
		t.Fatalf("unexpected filtered runs page: %#v", page.Items)
	}
}

func TestSQLiteStoreAssignsTurnIndexPerThread(t *testing.T) {
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

	base := time.Unix(1710000100, 0).UTC()
	for index, runID := range []string{"run-a", "run-b"} {
		eventTime := base.Add(time.Duration(index) * time.Second)
		if err := telemetryStore.RecordEvent(ctx, runtimeclient.TelemetryEvent{
			RunID:      runID,
			AgentName:  "assistant",
			Timestamp:  eventTime,
			EventID:    runID + ":1:1",
			Attempt:    1,
			Seq:        1,
			StreamMode: "lifecycle",
			EventType:  "run_started",
			NodeName:   "run",
			PublicEvent: &runtimeclient.AgentEvent{
				Type:      runtimeclient.AgentEventTypeRunStarted,
				RunID:     runID,
				AgentName: "assistant",
				ThreadID:  "thread-seq",
				Timestamp: eventTime,
			},
		}); err != nil {
			t.Fatalf("record run %s: %v", runID, err)
		}
	}

	runA, err := telemetryStore.GetRun(ctx, "run-a")
	if err != nil {
		t.Fatalf("get run-a: %v", err)
	}
	runB, err := telemetryStore.GetRun(ctx, "run-b")
	if err != nil {
		t.Fatalf("get run-b: %v", err)
	}
	if runA.TurnIndex != 1 || runB.TurnIndex != 2 {
		t.Fatalf("unexpected turn indices: runA=%d runB=%d", runA.TurnIndex, runB.TurnIndex)
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
