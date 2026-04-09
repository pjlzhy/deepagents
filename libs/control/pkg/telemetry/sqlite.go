package telemetry

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"agentctl/pkg/domain"
	"agentctl/pkg/runtimeclient"
)

var (
	ErrRunNotFound            = errors.New("telemetry run not found")
	ErrRunSnapshotUnavailable = errors.New("telemetry run snapshot unavailable")
)

// SQLiteStore persists telemetry history into the control SQLite database.
type SQLiteStore struct {
	db *sql.DB
}

// NewSQLiteStore constructs a telemetry store backed by one SQLite connection.
func NewSQLiteStore(db *sql.DB) (*SQLiteStore, error) {
	if db == nil {
		return nil, errors.New("sqlite db must not be nil")
	}
	return &SQLiteStore{db: db}, nil
}

// RecordEvent appends one telemetry event and updates the run summary.
func (s *SQLiteStore) RecordEvent(ctx context.Context, event runtimeclient.TelemetryEvent) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if s == nil || s.db == nil {
		return errors.New("telemetry store is not initialized")
	}
	if strings.TrimSpace(event.RunID) == "" {
		return errors.New("telemetry event run_id must not be empty")
	}
	if strings.TrimSpace(event.EventID) == "" {
		return errors.New("telemetry event event_id must not be empty")
	}

	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin telemetry record tx: %w", err)
	}
	defer func() {
		if err != nil {
			_ = tx.Rollback()
		}
	}()

	now := time.Now().UTC()
	inserted, err := s.insertEvent(ctx, tx, event, now)
	if err != nil {
		return err
	}
	if inserted {
		if err = s.upsertRunSummary(ctx, tx, event, now); err != nil {
			return err
		}
	}
	if err = tx.Commit(); err != nil {
		return fmt.Errorf("commit telemetry record tx: %w", err)
	}
	return nil
}

// ListRuns returns one page of telemetry runs ordered by latest activity.
func (s *SQLiteStore) ListRuns(
	ctx context.Context,
	query domain.TelemetryRunQuery,
) (domain.ResourcePage[domain.TelemetryRun], error) {
	if err := ctx.Err(); err != nil {
		return domain.ResourcePage[domain.TelemetryRun]{}, err
	}
	if s == nil || s.db == nil {
		return domain.ResourcePage[domain.TelemetryRun]{}, errors.New("telemetry store is not initialized")
	}

	pageSize, pageNumber := normalizePage(query.PageQuery)
	filters, args := telemetryRunListFilter(query)
	totalSize, err := s.countRuns(ctx, filters, args)
	if err != nil {
		return domain.ResourcePage[domain.TelemetryRun]{}, err
	}
	offset := (pageNumber - 1) * pageSize

	listArgs := append(append([]any{}, args...), pageSize, offset)

	rows, err := s.db.QueryContext(
		ctx,
		fmt.Sprintf(`SELECT
			run_id,
			agent_name,
			thread_id,
			turn_index,
			start_checkpoint_id,
			end_checkpoint_id,
			runtime_target,
			status,
			request_metadata_json,
			trace_context_json,
			graph_snapshot_id,
			reasoning_summary,
			node_step_count,
			model_step_count,
			tool_step_count,
			hitl_wait_count,
			error_count,
			event_count,
			started_at,
			finished_at,
			last_event_at,
			created_at,
			updated_at
		FROM telemetry_runs
		%s
		ORDER BY
			CASE WHEN last_event_at = '' THEN created_at ELSE last_event_at END DESC,
			run_id DESC
		LIMIT ? OFFSET ?`, filters),
		listArgs...,
	)
	if err != nil {
		return domain.ResourcePage[domain.TelemetryRun]{}, fmt.Errorf("list telemetry runs: %w", err)
	}
	defer rows.Close()

	items := make([]domain.TelemetryRun, 0, pageSize)
	for rows.Next() {
		run, scanErr := scanTelemetryRun(rows)
		if scanErr != nil {
			return domain.ResourcePage[domain.TelemetryRun]{}, scanErr
		}
		items = append(items, run)
	}
	if err := rows.Err(); err != nil {
		return domain.ResourcePage[domain.TelemetryRun]{}, fmt.Errorf("iterate telemetry runs: %w", err)
	}

	return domain.ResourcePage[domain.TelemetryRun]{
		Items: items,
		PageMetadata: domain.PageMetadata{
			PageSize:   pageSize,
			PageNumber: pageNumber,
			TotalSize:  totalSize,
			TotalPages: totalPages(totalSize, pageSize),
		},
	}, nil
}

// GetRun returns one telemetry run summary by run ID.
func (s *SQLiteStore) GetRun(ctx context.Context, runID string) (domain.TelemetryRun, error) {
	if err := ctx.Err(); err != nil {
		return domain.TelemetryRun{}, err
	}
	if s == nil || s.db == nil {
		return domain.TelemetryRun{}, errors.New("telemetry store is not initialized")
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		return domain.TelemetryRun{}, errors.New("run_id must not be empty")
	}

	row := s.db.QueryRowContext(
		ctx,
		`SELECT
			run_id,
			agent_name,
			thread_id,
			turn_index,
			start_checkpoint_id,
			end_checkpoint_id,
			runtime_target,
			status,
			request_metadata_json,
			trace_context_json,
			graph_snapshot_id,
			reasoning_summary,
			node_step_count,
			model_step_count,
			tool_step_count,
			hitl_wait_count,
			error_count,
			event_count,
			started_at,
			finished_at,
			last_event_at,
			created_at,
			updated_at
		FROM telemetry_runs
		WHERE run_id = ?`,
		runID,
	)

	run, err := scanTelemetryRun(row)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return domain.TelemetryRun{}, ErrRunNotFound
		}
		return domain.TelemetryRun{}, err
	}
	return run, nil
}

// ListEvents returns one page of persisted telemetry events for one run.
func (s *SQLiteStore) ListEvents(
	ctx context.Context,
	runID string,
	query domain.PageQuery,
) (domain.ResourcePage[domain.TelemetryEventRecord], error) {
	if err := ctx.Err(); err != nil {
		return domain.ResourcePage[domain.TelemetryEventRecord]{}, err
	}
	if s == nil || s.db == nil {
		return domain.ResourcePage[domain.TelemetryEventRecord]{}, errors.New("telemetry store is not initialized")
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		return domain.ResourcePage[domain.TelemetryEventRecord]{}, errors.New("run_id must not be empty")
	}

	pageSize, pageNumber := normalizePage(query)
	totalSize, err := s.countEvents(ctx, runID)
	if err != nil {
		return domain.ResourcePage[domain.TelemetryEventRecord]{}, err
	}
	offset := (pageNumber - 1) * pageSize

	rows, err := s.db.QueryContext(
		ctx,
		`SELECT
			event_id,
			run_id,
			agent_name,
			attempt,
			seq,
			timestamp,
			namespace_json,
			stream_mode,
			event_type,
			node_name,
			task_id,
			model_call_id,
			tool_call_id,
			interrupt_id,
			message_id,
			metadata_json,
			payload_json,
			public_event_json,
			created_at
		FROM telemetry_events
		WHERE run_id = ?
		ORDER BY attempt ASC, seq ASC
		LIMIT ? OFFSET ?`,
		runID,
		pageSize,
		offset,
	)
	if err != nil {
		return domain.ResourcePage[domain.TelemetryEventRecord]{}, fmt.Errorf("list telemetry events: %w", err)
	}
	defer rows.Close()

	items := make([]domain.TelemetryEventRecord, 0, pageSize)
	for rows.Next() {
		event, scanErr := scanTelemetryEvent(rows)
		if scanErr != nil {
			return domain.ResourcePage[domain.TelemetryEventRecord]{}, scanErr
		}
		items = append(items, event)
	}
	if err := rows.Err(); err != nil {
		return domain.ResourcePage[domain.TelemetryEventRecord]{}, fmt.Errorf("iterate telemetry events: %w", err)
	}

	return domain.ResourcePage[domain.TelemetryEventRecord]{
		Items: items,
		PageMetadata: domain.PageMetadata{
			PageSize:   pageSize,
			PageNumber: pageNumber,
			TotalSize:  totalSize,
			TotalPages: totalPages(totalSize, pageSize),
		},
	}, nil
}

// LoadEvents returns all persisted telemetry events for one run in attempt/seq order.
func (s *SQLiteStore) LoadEvents(ctx context.Context, runID string) ([]domain.TelemetryEventRecord, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if s == nil || s.db == nil {
		return nil, errors.New("telemetry store is not initialized")
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		return nil, errors.New("run_id must not be empty")
	}

	rows, err := s.db.QueryContext(
		ctx,
		`SELECT
			event_id,
			run_id,
			agent_name,
			attempt,
			seq,
			timestamp,
			namespace_json,
			stream_mode,
			event_type,
			node_name,
			task_id,
			model_call_id,
			tool_call_id,
			interrupt_id,
			message_id,
			metadata_json,
			payload_json,
			public_event_json,
			created_at
		FROM telemetry_events
		WHERE run_id = ?
		ORDER BY attempt ASC, seq ASC`,
		runID,
	)
	if err != nil {
		return nil, fmt.Errorf("load telemetry events: %w", err)
	}
	defer rows.Close()

	items := make([]domain.TelemetryEventRecord, 0, 64)
	for rows.Next() {
		event, scanErr := scanTelemetryEvent(rows)
		if scanErr != nil {
			return nil, scanErr
		}
		items = append(items, event)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate telemetry events: %w", err)
	}
	return items, nil
}

func (s *SQLiteStore) upsertRunSummary(
	ctx context.Context,
	tx *sql.Tx,
	event runtimeclient.TelemetryEvent,
	now time.Time,
) error {
	threadID := ""
	if event.PublicEvent != nil {
		threadID = strings.TrimSpace(event.PublicEvent.ThreadID)
	}
	startCheckpointID, endCheckpointID := extractTelemetryRunCheckpoints(event)
	turnIndex, err := s.allocateTurnIndex(ctx, tx, event.RunID, event.AgentName, threadID)
	if err != nil {
		return err
	}
	status := runStatusFromEvent(event.EventType)
	if status == "" {
		status = string(domain.TelemetryRunStatusRunning)
	}
	startedAt := isoTime(event.Timestamp)
	lastEventAt := isoTime(event.Timestamp)
	finishedAt := ""
	if isTelemetryTerminalEvent(event.EventType) {
		finishedAt = lastEventAt
	}
	errorIncrement := int64(0)
	if event.EventType == string(domain.TelemetryRunStatusFailed) || event.EventType == "error" {
		errorIncrement = 1
	}

	_, err = tx.ExecContext(
		ctx,
		`INSERT INTO telemetry_runs (
			run_id,
			agent_name,
			thread_id,
			turn_index,
			start_checkpoint_id,
			end_checkpoint_id,
			runtime_target,
			status,
			request_metadata_json,
			trace_context_json,
			graph_snapshot_id,
			reasoning_summary,
			node_step_count,
			model_step_count,
			tool_step_count,
			hitl_wait_count,
			error_count,
			event_count,
			started_at,
			finished_at,
			last_event_at,
			created_at,
			updated_at
		) VALUES (?, ?, ?, ?, ?, ?, '', ?, '{}', '{}', '', '', 0, 0, 0, 0, ?, 1, ?, ?, ?, ?, ?)
		ON CONFLICT(run_id) DO UPDATE SET
			agent_name = CASE
				WHEN excluded.agent_name <> '' THEN excluded.agent_name
				ELSE telemetry_runs.agent_name
			END,
			thread_id = CASE
				WHEN telemetry_runs.thread_id = '' AND excluded.thread_id <> '' THEN excluded.thread_id
				ELSE telemetry_runs.thread_id
			END,
			turn_index = CASE
				WHEN telemetry_runs.turn_index = 0 AND excluded.turn_index <> 0 THEN excluded.turn_index
				ELSE telemetry_runs.turn_index
			END,
			start_checkpoint_id = CASE
				WHEN telemetry_runs.start_checkpoint_id = '' AND excluded.start_checkpoint_id <> '' THEN excluded.start_checkpoint_id
				ELSE telemetry_runs.start_checkpoint_id
			END,
			end_checkpoint_id = CASE
				WHEN excluded.end_checkpoint_id <> '' THEN excluded.end_checkpoint_id
				ELSE telemetry_runs.end_checkpoint_id
			END,
			status = CASE
				WHEN telemetry_runs.status IN ('completed', 'canceled', 'failed') AND excluded.status = 'running' THEN telemetry_runs.status
				WHEN excluded.status <> '' THEN excluded.status
				ELSE telemetry_runs.status
			END,
			error_count = telemetry_runs.error_count + ?,
			event_count = telemetry_runs.event_count + 1,
			started_at = CASE
				WHEN telemetry_runs.started_at = '' AND excluded.started_at <> '' THEN excluded.started_at
				ELSE telemetry_runs.started_at
			END,
			finished_at = CASE
				WHEN excluded.finished_at <> '' THEN excluded.finished_at
				ELSE telemetry_runs.finished_at
			END,
			last_event_at = CASE
				WHEN excluded.last_event_at <> '' THEN excluded.last_event_at
				ELSE telemetry_runs.last_event_at
			END,
			updated_at = excluded.updated_at`,
		event.RunID,
		event.AgentName,
		threadID,
		turnIndex,
		startCheckpointID,
		endCheckpointID,
		status,
		errorIncrement,
		startedAt,
		finishedAt,
		lastEventAt,
		now.Format(time.RFC3339Nano),
		now.Format(time.RFC3339Nano),
		errorIncrement,
	)
	if err != nil {
		return fmt.Errorf("upsert telemetry run %q: %w", event.RunID, err)
	}
	return nil
}

func (s *SQLiteStore) insertEvent(
	ctx context.Context,
	tx *sql.Tx,
	event runtimeclient.TelemetryEvent,
	now time.Time,
) (bool, error) {
	namespaceJSON, err := marshalRawJSON(event.Namespace)
	if err != nil {
		return false, fmt.Errorf("marshal telemetry namespace: %w", err)
	}
	publicEventJSON, err := marshalPublicEvent(event.PublicEvent)
	if err != nil {
		return false, fmt.Errorf("marshal telemetry public event: %w", err)
	}

	result, err := tx.ExecContext(
		ctx,
		`INSERT OR IGNORE INTO telemetry_events (
			event_id,
			run_id,
			agent_name,
			attempt,
			seq,
			timestamp,
			namespace_json,
			stream_mode,
			event_type,
			node_name,
			task_id,
			model_call_id,
			tool_call_id,
			interrupt_id,
			message_id,
			metadata_json,
			payload_json,
			public_event_json,
			created_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		event.EventID,
		event.RunID,
		event.AgentName,
		event.Attempt,
		event.Seq,
		isoTime(event.Timestamp),
		namespaceJSON,
		event.StreamMode,
		event.EventType,
		event.NodeName,
		event.TaskID,
		event.ModelCallID,
		event.ToolCallID,
		event.InterruptID,
		event.MessageID,
		normalizeRawJSON(event.Metadata),
		normalizeRawJSON(event.Payload),
		publicEventJSON,
		now.Format(time.RFC3339Nano),
	)
	if err != nil {
		return false, fmt.Errorf("insert telemetry event %q: %w", event.EventID, err)
	}
	rowsAffected, err := result.RowsAffected()
	if err != nil {
		return false, fmt.Errorf("read telemetry insert rows for %q: %w", event.EventID, err)
	}
	return rowsAffected > 0, nil
}

func (s *SQLiteStore) allocateTurnIndex(
	ctx context.Context,
	tx *sql.Tx,
	runID string,
	agentName string,
	threadID string,
) (int32, error) {
	if strings.TrimSpace(agentName) == "" || strings.TrimSpace(threadID) == "" {
		return 0, nil
	}

	var existing int32
	err := tx.QueryRowContext(
		ctx,
		`SELECT turn_index FROM telemetry_runs WHERE run_id = ?`,
		runID,
	).Scan(&existing)
	switch {
	case err == nil && existing > 0:
		return existing, nil
	case err != nil && !errors.Is(err, sql.ErrNoRows):
		return 0, fmt.Errorf("load telemetry turn index for run %q: %w", runID, err)
	}

	var nextIndex int32
	if err := tx.QueryRowContext(
		ctx,
		`SELECT COALESCE(MAX(turn_index), 0) + 1
		FROM telemetry_runs
		WHERE agent_name = ? AND thread_id = ? AND run_id <> ?`,
		agentName,
		threadID,
		runID,
	).Scan(&nextIndex); err != nil {
		return 0, fmt.Errorf("allocate telemetry turn index for run %q: %w", runID, err)
	}
	return nextIndex, nil
}

func (s *SQLiteStore) countRuns(
	ctx context.Context,
	filters string,
	args []any,
) (int32, error) {
	var total int32
	query := fmt.Sprintf(`SELECT COUNT(*) FROM telemetry_runs %s`, filters)
	if err := s.db.QueryRowContext(ctx, query, args...).Scan(&total); err != nil {
		return 0, fmt.Errorf("count telemetry runs: %w", err)
	}
	return total, nil
}

func (s *SQLiteStore) countEvents(ctx context.Context, runID string) (int32, error) {
	var total int32
	if err := s.db.QueryRowContext(
		ctx,
		`SELECT COUNT(*) FROM telemetry_events WHERE run_id = ?`,
		runID,
	).Scan(&total); err != nil {
		return 0, fmt.Errorf("count telemetry events for run %q: %w", runID, err)
	}
	return total, nil
}

type telemetryRunScanner interface {
	Scan(dest ...any) error
}

func scanTelemetryRun(scanner telemetryRunScanner) (domain.TelemetryRun, error) {
	var (
		run             domain.TelemetryRun
		status          string
		requestMetadata string
		traceContext    string
		startedAt       string
		finishedAt      string
		lastEventAt     string
		createdAt       string
		updatedAt       string
	)
	if err := scanner.Scan(
		&run.RunID,
		&run.AgentName,
		&run.ThreadID,
		&run.TurnIndex,
		&run.StartCheckpointID,
		&run.EndCheckpointID,
		&run.RuntimeTarget,
		&status,
		&requestMetadata,
		&traceContext,
		&run.GraphSnapshotID,
		&run.ReasoningSummary,
		&run.NodeStepCount,
		&run.ModelStepCount,
		&run.ToolStepCount,
		&run.HitlWaitCount,
		&run.ErrorCount,
		&run.EventCount,
		&startedAt,
		&finishedAt,
		&lastEventAt,
		&createdAt,
		&updatedAt,
	); err != nil {
		return domain.TelemetryRun{}, fmt.Errorf("scan telemetry run: %w", err)
	}
	run.Status = domain.TelemetryRunStatus(status)
	run.RequestMetadata = normalizeRawJSON(json.RawMessage(requestMetadata))
	run.TraceContext = normalizeRawJSON(json.RawMessage(traceContext))
	run.StartedAt = parseISOTime(startedAt)
	run.FinishedAt = parseISOTime(finishedAt)
	run.LastEventAt = parseISOTime(lastEventAt)
	run.CreatedAt = parseISOTime(createdAt)
	run.UpdatedAt = parseISOTime(updatedAt)
	return run, nil
}

type telemetryEventScanner interface {
	Scan(dest ...any) error
}

func scanTelemetryEvent(scanner telemetryEventScanner) (domain.TelemetryEventRecord, error) {
	var (
		event         domain.TelemetryEventRecord
		namespaceJSON string
		timestamp     string
		metadataJSON  string
		payloadJSON   string
		publicEvent   string
		createdAt     string
	)
	if err := scanner.Scan(
		&event.EventID,
		&event.RunID,
		&event.AgentName,
		&event.Attempt,
		&event.Seq,
		&timestamp,
		&namespaceJSON,
		&event.StreamMode,
		&event.EventType,
		&event.NodeName,
		&event.TaskID,
		&event.ModelCallID,
		&event.ToolCallID,
		&event.InterruptID,
		&event.MessageID,
		&metadataJSON,
		&payloadJSON,
		&publicEvent,
		&createdAt,
	); err != nil {
		return domain.TelemetryEventRecord{}, fmt.Errorf("scan telemetry event: %w", err)
	}
	event.Timestamp = parseISOTime(timestamp)
	event.CreatedAt = parseISOTime(createdAt)
	if len(namespaceJSON) > 0 && namespaceJSON != "null" {
		if err := json.Unmarshal([]byte(namespaceJSON), &event.Namespace); err != nil {
			return domain.TelemetryEventRecord{}, fmt.Errorf("decode telemetry namespace: %w", err)
		}
	}
	event.Metadata = normalizeRawJSON(json.RawMessage(metadataJSON))
	event.Payload = normalizeRawJSON(json.RawMessage(payloadJSON))
	event.PublicEvent = normalizeRawJSON(json.RawMessage(publicEvent))
	return event, nil
}

func telemetryRunListFilter(query domain.TelemetryRunQuery) (string, []any) {
	clauses := make([]string, 0, 2)
	args := make([]any, 0, 2)

	if agentName := strings.TrimSpace(query.AgentName); agentName != "" {
		clauses = append(clauses, "agent_name = ?")
		args = append(args, agentName)
	}
	if threadID := strings.TrimSpace(query.ThreadID); threadID != "" {
		clauses = append(clauses, "thread_id = ?")
		args = append(args, threadID)
	}
	if len(clauses) == 0 {
		return "", args
	}
	return "WHERE " + strings.Join(clauses, " AND "), args
}

func extractTelemetryRunCheckpoints(event runtimeclient.TelemetryEvent) (string, string) {
	payload := decodeRawObjectMap(event.Payload)
	if len(payload) == 0 {
		return "", ""
	}

	switch strings.TrimSpace(event.EventType) {
	case "checkpoint":
		return nestedCheckpointID(payload, "parent_config"), nestedCheckpointID(payload, "config")
	case "run_ended":
		return strings.TrimSpace(stringValueFromMap(payload, "start_checkpoint_id")), strings.TrimSpace(stringValueFromMap(payload, "end_checkpoint_id"))
	default:
		return "", ""
	}
}

func nestedCheckpointID(payload map[string]any, key string) string {
	rawConfig, ok := payload[key]
	if !ok {
		return ""
	}
	config, ok := rawConfig.(map[string]any)
	if !ok {
		return ""
	}
	rawConfigurable, ok := config["configurable"]
	if !ok {
		return ""
	}
	configurable, ok := rawConfigurable.(map[string]any)
	if !ok {
		return ""
	}
	checkpointID, _ := configurable["checkpoint_id"].(string)
	return strings.TrimSpace(checkpointID)
}

func decodeRawObjectMap(raw json.RawMessage) map[string]any {
	if len(raw) == 0 || string(raw) == "null" {
		return nil
	}
	var decoded map[string]any
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return nil
	}
	return decoded
}

func stringValueFromMap(payload map[string]any, key string) string {
	if payload == nil {
		return ""
	}
	value, _ := payload[key].(string)
	return value
}

func normalizePage(query domain.PageQuery) (int32, int32) {
	pageSize := query.PageSize
	if pageSize <= 0 {
		pageSize = 50
	}
	pageNumber := query.PageNumber
	if pageNumber <= 0 {
		pageNumber = 1
	}
	return pageSize, pageNumber
}

func totalPages(totalSize int32, pageSize int32) int32 {
	if pageSize <= 0 {
		return 0
	}
	if totalSize == 0 {
		return 0
	}
	pages := totalSize / pageSize
	if totalSize%pageSize != 0 {
		pages++
	}
	return pages
}

func runStatusFromEvent(eventType string) string {
	switch strings.TrimSpace(eventType) {
	case "run_started":
		return string(domain.TelemetryRunStatusRunning)
	case "run_ended":
		return string(domain.TelemetryRunStatusCompleted)
	case "run_canceled":
		return string(domain.TelemetryRunStatusCanceled)
	case "error":
		return string(domain.TelemetryRunStatusFailed)
	default:
		return ""
	}
}

func isTelemetryTerminalEvent(eventType string) bool {
	switch strings.TrimSpace(eventType) {
	case "run_ended", "run_canceled", "error":
		return true
	default:
		return false
	}
}

func marshalRawJSON(value any) (string, error) {
	payload, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	return string(payload), nil
}

func marshalPublicEvent(event *runtimeclient.AgentEvent) (string, error) {
	if event == nil {
		return "null", nil
	}
	actionRequests := make([]map[string]any, 0, len(event.Actions))
	for _, action := range event.Actions {
		actionRequests = append(actionRequests, map[string]any{
			"name":        action.Name,
			"description": action.Description,
			"arguments":   normalizeRawJSON(action.Arguments),
		})
	}
	reviewConfigs := make([]map[string]any, 0, len(event.ReviewConfigs))
	for _, config := range event.ReviewConfigs {
		reviewConfigs = append(reviewConfigs, map[string]any{
			"action_name":       config.ActionName,
			"allowed_decisions": config.AllowedDecisions,
			"args_schema":       normalizeRawJSON(config.ArgsSchema),
		})
	}

	body := map[string]any{
		"type":            string(event.Type),
		"run_id":          event.RunID,
		"agent_name":      event.AgentName,
		"timestamp":       isoTime(event.Timestamp),
		"thread_id":       event.ThreadID,
		"text":            event.Text,
		"tool_name":       event.ToolName,
		"tool_call_id":    event.ToolCallID,
		"interrupt_id":    event.InterruptID,
		"reason":          event.Reason,
		"error_message":   event.ErrorMessage,
		"payload":         normalizeRawJSON(event.Payload),
		"action_requests": actionRequests,
		"review_configs":  reviewConfigs,
	}
	payload, err := json.Marshal(body)
	if err != nil {
		return "", err
	}
	return string(payload), nil
}

func normalizeRawJSON(value json.RawMessage) json.RawMessage {
	if len(value) == 0 {
		return json.RawMessage("null")
	}
	return value
}

func isoTime(value time.Time) string {
	if value.IsZero() {
		return ""
	}
	return value.UTC().Format(time.RFC3339Nano)
}

func parseISOTime(value string) time.Time {
	if strings.TrimSpace(value) == "" {
		return time.Time{}
	}
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return time.Time{}
	}
	return parsed.UTC()
}
