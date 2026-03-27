package store

import (
	"context"
	"database/sql"
	"path/filepath"
	"strings"
	"testing"
)

func TestOpenSQLiteInitializesSchema(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "control.sqlite")

	db, err := OpenSQLite(ctx, SQLiteConfig{Path: path})
	if err != nil {
		t.Fatalf("open sqlite store: %v", err)
	}
	defer func() {
		_ = db.Close()
	}()

	if err := db.Ping(ctx); err != nil {
		t.Fatalf("ping sqlite store: %v", err)
	}
	if db.DB() == nil {
		t.Fatal("expected underlying sql.DB")
	}

	assertTableSQLContains(t, ctx, db.DB(), "model_configs", `id INTEGER PRIMARY KEY AUTOINCREMENT`)
	assertTableSQLContains(t, ctx, db.DB(), "skills", `id INTEGER PRIMARY KEY AUTOINCREMENT`)
	assertTableSQLContains(t, ctx, db.DB(), "mcp_configs", `id INTEGER PRIMARY KEY AUTOINCREMENT`)
	assertTableSQLContains(t, ctx, db.DB(), "agent_specs", `id INTEGER PRIMARY KEY AUTOINCREMENT`)
	assertTableSQLContains(t, ctx, db.DB(), "runtime_targets", `id INTEGER PRIMARY KEY AUTOINCREMENT`)
	assertTableSQLContains(t, ctx, db.DB(), "deployments", `id INTEGER PRIMARY KEY AUTOINCREMENT`)
	assertTableSQLContains(t, ctx, db.DB(), "operations", `id INTEGER PRIMARY KEY AUTOINCREMENT`)
	assertTableSQLContains(t, ctx, db.DB(), "operations", `operation_id TEXT NOT NULL`)

	assertIndexExists(t, ctx, db.DB(), "idx_model_configs_name")
	assertIndexExists(t, ctx, db.DB(), "idx_skills_name")
	assertIndexExists(t, ctx, db.DB(), "idx_mcp_configs_name")
	assertIndexExists(t, ctx, db.DB(), "idx_agent_specs_name")
	assertIndexExists(t, ctx, db.DB(), "idx_agent_specs_model_ref")
	assertIndexExists(t, ctx, db.DB(), "idx_runtime_targets_name")
	assertIndexExists(t, ctx, db.DB(), "idx_deployments_agent_name")
	assertIndexExists(t, ctx, db.DB(), "idx_deployments_target_name")
	assertIndexExists(t, ctx, db.DB(), "idx_operations_operation_id")
	assertIndexExists(t, ctx, db.DB(), "idx_operations_agent_name")
	assertIndexExists(t, ctx, db.DB(), "idx_operations_target_name")
	assertIndexExists(t, ctx, db.DB(), "idx_operations_kind")
	assertIndexExists(t, ctx, db.DB(), "idx_operations_status")
}

func TestOpenSQLiteMigratesAgentSpecModelRefColumn(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "control.sqlite")

	rawDB, err := sql.Open(sqliteDriverName, path)
	if err != nil {
		t.Fatalf("open raw sqlite db: %v", err)
	}
	if _, err := rawDB.ExecContext(ctx, `
CREATE TABLE agent_specs (
	name TEXT PRIMARY KEY,
	version TEXT NOT NULL,
	description TEXT NOT NULL,
	tags_json TEXT NOT NULL,
	prompt_json TEXT NOT NULL,
	skill_refs_json TEXT NOT NULL,
	mcp_refs_json TEXT NOT NULL,
	subagents_json TEXT NOT NULL,
	sandbox_json TEXT NOT NULL,
	interrupt_on_json TEXT NOT NULL,
	status TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
)`); err != nil {
		_ = rawDB.Close()
		t.Fatalf("create legacy agent_specs table: %v", err)
	}
	if err := rawDB.Close(); err != nil {
		t.Fatalf("close raw sqlite db: %v", err)
	}

	db, err := OpenSQLite(ctx, SQLiteConfig{Path: path})
	if err != nil {
		t.Fatalf("open sqlite store with migration: %v", err)
	}
	defer func() {
		_ = db.Close()
	}()

	rows, err := db.DB().QueryContext(ctx, `PRAGMA table_info(agent_specs)`)
	if err != nil {
		t.Fatalf("query table info: %v", err)
	}
	defer rows.Close()

	found := false
	foundID := false
	for rows.Next() {
		var cid int
		var name string
		var dataType string
		var notNull int
		var defaultValue sql.NullString
		var primaryKey int
		if err := rows.Scan(&cid, &name, &dataType, &notNull, &defaultValue, &primaryKey); err != nil {
			t.Fatalf("scan table info: %v", err)
		}
		if name == "model_ref" {
			found = true
		}
		if name == "id" {
			foundID = true
		}
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("iterate table info: %v", err)
	}
	if !found {
		t.Fatal("expected migrated agent_specs.model_ref column")
	}
	if !foundID {
		t.Fatal("expected migrated agent_specs.id column")
	}
	assertIndexExists(t, ctx, db.DB(), "idx_agent_specs_name")
}

func TestOpenSQLiteMigratesOperationTableToSurrogatePrimaryKey(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "control.sqlite")

	rawDB, err := sql.Open(sqliteDriverName, path)
	if err != nil {
		t.Fatalf("open raw sqlite db: %v", err)
	}
	if _, err := rawDB.ExecContext(ctx, `
CREATE TABLE operations (
	id TEXT PRIMARY KEY,
	agent_name TEXT NOT NULL,
	target_name TEXT NOT NULL,
	kind TEXT NOT NULL,
	status TEXT NOT NULL,
	error_message TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
)`); err != nil {
		_ = rawDB.Close()
		t.Fatalf("create legacy operations table: %v", err)
	}
	if _, err := rawDB.ExecContext(
		ctx,
		`INSERT INTO operations (id, agent_name, target_name, kind, status, error_message, created_at, updated_at)
		VALUES ('op-1', 'assistant', 'runtime-a', 'compile', 'pending', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')`,
	); err != nil {
		_ = rawDB.Close()
		t.Fatalf("seed legacy operations table: %v", err)
	}
	if err := rawDB.Close(); err != nil {
		t.Fatalf("close raw sqlite db: %v", err)
	}

	db, err := OpenSQLite(ctx, SQLiteConfig{Path: path})
	if err != nil {
		t.Fatalf("open sqlite store with migration: %v", err)
	}
	defer func() {
		_ = db.Close()
	}()

	assertTableSQLContains(t, ctx, db.DB(), "operations", `id INTEGER PRIMARY KEY AUTOINCREMENT`)
	assertTableSQLContains(t, ctx, db.DB(), "operations", `operation_id TEXT NOT NULL`)
	assertIndexExists(t, ctx, db.DB(), "idx_operations_operation_id")

	var operationID string
	var agentName string
	if err := db.DB().QueryRowContext(
		ctx,
		`SELECT operation_id, agent_name FROM operations WHERE operation_id = ?`,
		"op-1",
	).Scan(&operationID, &agentName); err != nil {
		t.Fatalf("query migrated operation: %v", err)
	}
	if operationID != "op-1" || agentName != "assistant" {
		t.Fatalf("unexpected migrated operation row: operation_id=%q agent_name=%q", operationID, agentName)
	}
}

func assertTableSQLContains(
	t *testing.T,
	ctx context.Context,
	db *sql.DB,
	table string,
	substring string,
) {
	t.Helper()

	var createSQL string
	if err := db.QueryRowContext(
		ctx,
		`SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?`,
		table,
	).Scan(&createSQL); err != nil {
		t.Fatalf("query sqlite_master for %s: %v", table, err)
	}
	if !strings.Contains(strings.ToUpper(createSQL), strings.ToUpper(substring)) {
		t.Fatalf("expected table %s SQL to contain %q, got: %s", table, substring, createSQL)
	}
}

func assertIndexExists(t *testing.T, ctx context.Context, db *sql.DB, indexName string) {
	t.Helper()

	var found string
	if err := db.QueryRowContext(
		ctx,
		`SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?`,
		indexName,
	).Scan(&found); err != nil {
		t.Fatalf("query sqlite index %s: %v", indexName, err)
	}
	if found != indexName {
		t.Fatalf("expected index %s, got %q", indexName, found)
	}
}
