package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	_ "modernc.org/sqlite"
)

const sqliteDriverName = "sqlite"

const sqliteTablesSchema = `
CREATE TABLE IF NOT EXISTS model_configs (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT NOT NULL,
	description TEXT NOT NULL,
	spec_json TEXT NOT NULL,
	status TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT NOT NULL,
	description TEXT NOT NULL,
	tags_json TEXT NOT NULL,
	content TEXT NOT NULL,
	files_json TEXT NOT NULL,
	status TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_configs (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT NOT NULL,
	command TEXT NOT NULL,
	args_json TEXT NOT NULL,
	env_json TEXT NOT NULL,
	transport TEXT NOT NULL,
	description TEXT NOT NULL,
	status TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sandbox_configs (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT NOT NULL,
	description TEXT NOT NULL,
	spec_json TEXT NOT NULL,
	status TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_specs (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT NOT NULL,
	version TEXT NOT NULL,
	description TEXT NOT NULL,
	tags_json TEXT NOT NULL,
	model_ref TEXT NOT NULL,
	prompt_json TEXT NOT NULL,
	skill_refs_json TEXT NOT NULL,
	mcp_refs_json TEXT NOT NULL,
	sandbox_ref TEXT NOT NULL,
	subagents_json TEXT NOT NULL,
	interrupt_on_json TEXT NOT NULL,
	status TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_targets (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT NOT NULL,
	kind TEXT NOT NULL,
	endpoint TEXT NOT NULL,
	description TEXT NOT NULL,
	metadata_json TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deployments (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	agent_name TEXT NOT NULL,
	target_name TEXT NOT NULL,
	desired_state TEXT NOT NULL,
	observed_state TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operations (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	operation_id TEXT NOT NULL,
	agent_name TEXT NOT NULL,
	target_name TEXT NOT NULL,
	kind TEXT NOT NULL,
	status TEXT NOT NULL,
	error_message TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);
`

const sqliteIndexesSchema = `
CREATE UNIQUE INDEX IF NOT EXISTS idx_model_configs_name ON model_configs(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_configs_name ON mcp_configs(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sandbox_configs_name ON sandbox_configs(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_specs_name ON agent_specs(name);
CREATE INDEX IF NOT EXISTS idx_agent_specs_model_ref ON agent_specs(model_ref);
CREATE INDEX IF NOT EXISTS idx_agent_specs_sandbox_ref ON agent_specs(sandbox_ref);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_targets_name ON runtime_targets(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_deployments_agent_name ON deployments(agent_name);
CREATE INDEX IF NOT EXISTS idx_deployments_target_name ON deployments(target_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_operation_id ON operations(operation_id);
CREATE INDEX IF NOT EXISTS idx_operations_agent_name ON operations(agent_name);
CREATE INDEX IF NOT EXISTS idx_operations_target_name ON operations(target_name);
CREATE INDEX IF NOT EXISTS idx_operations_kind ON operations(kind);
CREATE INDEX IF NOT EXISTS idx_operations_status ON operations(status);
`

// SQLite 提供 SQLite-backed store。
type SQLite struct {
	db *sql.DB
}

// OpenSQLite 打开并初始化一个 SQLite store。
func OpenSQLite(ctx context.Context, cfg SQLiteConfig) (*SQLite, error) {
	path := strings.TrimSpace(cfg.Path)
	if path == "" {
		return nil, errors.New("sqlite path must not be empty")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, fmt.Errorf("create sqlite dir: %w", err)
	}

	dsn := fmt.Sprintf("%s?_pragma=foreign_keys(1)&_pragma=busy_timeout(5000)", filepath.ToSlash(path))
	db, err := sql.Open(sqliteDriverName, dsn)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}

	store := &SQLite{db: db}
	if err := store.init(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}
	if err := store.Ping(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}
	return store, nil
}

// DB 暴露底层 *sql.DB 供上层仓储实现使用。
func (s *SQLite) DB() *sql.DB {
	return s.db
}

// Ping 检查 store 是否可用。
func (s *SQLite) Ping(ctx context.Context) error {
	if s == nil || s.db == nil {
		return errors.New("sqlite store is not initialized")
	}
	if err := s.db.PingContext(ctx); err != nil {
		return fmt.Errorf("ping sqlite: %w", err)
	}
	return nil
}

// Close 关闭底层数据库连接。
func (s *SQLite) Close() error {
	if s == nil || s.db == nil {
		return nil
	}
	return s.db.Close()
}

func (s *SQLite) init(ctx context.Context) error {
	if _, err := s.db.ExecContext(ctx, sqliteTablesSchema); err != nil {
		return fmt.Errorf("init sqlite schema: %w", err)
	}
	if err := ensureSQLiteColumn(ctx, s.db, "agent_specs", "model_ref", "TEXT NOT NULL DEFAULT ''"); err != nil {
		return fmt.Errorf("migrate sqlite schema: %w", err)
	}
	if err := ensureSQLiteColumn(ctx, s.db, "agent_specs", "sandbox_ref", "TEXT NOT NULL DEFAULT ''"); err != nil {
		return fmt.Errorf("migrate sqlite schema: %w", err)
	}
	if err := ensureSQLiteSurrogatePrimaryKeys(ctx, s.db); err != nil {
		return fmt.Errorf("migrate sqlite surrogate keys: %w", err)
	}
	if _, err := s.db.ExecContext(ctx, sqliteIndexesSchema); err != nil {
		return fmt.Errorf("init sqlite indexes: %w", err)
	}
	return nil
}

type sqliteColumnInfo struct {
	cid          int
	name         string
	dataType     string
	notNull      int
	defaultValue sql.NullString
	primaryKey   int
}

func ensureSQLiteColumn(
	ctx context.Context,
	db *sql.DB,
	table string,
	column string,
	definition string,
) error {
	rows, err := db.QueryContext(ctx, fmt.Sprintf("PRAGMA table_info(%s)", table))
	if err != nil {
		return fmt.Errorf("query sqlite table info for %s: %w", table, err)
	}
	defer rows.Close()

	for rows.Next() {
		var cid int
		var name string
		var dataType string
		var notNull int
		var defaultValue sql.NullString
		var primaryKey int
		if err := rows.Scan(&cid, &name, &dataType, &notNull, &defaultValue, &primaryKey); err != nil {
			return fmt.Errorf("scan sqlite table info for %s: %w", table, err)
		}
		if name == column {
			return nil
		}
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("iterate sqlite table info for %s: %w", table, err)
	}

	if _, err := db.ExecContext(
		ctx,
		fmt.Sprintf("ALTER TABLE %s ADD COLUMN %s %s", table, column, definition),
	); err != nil {
		return fmt.Errorf("add column %s to %s: %w", column, table, err)
	}
	return nil
}

func readSQLiteTableInfo(ctx context.Context, db *sql.DB, table string) ([]sqliteColumnInfo, error) {
	rows, err := db.QueryContext(ctx, fmt.Sprintf("PRAGMA table_info(%s)", quoteSQLiteIdentifier(table)))
	if err != nil {
		return nil, fmt.Errorf("query sqlite table info for %s: %w", table, err)
	}
	defer rows.Close()

	columns := make([]sqliteColumnInfo, 0)
	for rows.Next() {
		var column sqliteColumnInfo
		if err := rows.Scan(
			&column.cid,
			&column.name,
			&column.dataType,
			&column.notNull,
			&column.defaultValue,
			&column.primaryKey,
		); err != nil {
			return nil, fmt.Errorf("scan sqlite table info for %s: %w", table, err)
		}
		columns = append(columns, column)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate sqlite table info for %s: %w", table, err)
	}
	return columns, nil
}

func ensureSQLiteSurrogatePrimaryKeys(ctx context.Context, db *sql.DB) error {
	migrations := []sqliteTableMigration{
		{
			table: "model_configs",
			createSQL: `CREATE TABLE %s (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				description TEXT NOT NULL,
				spec_json TEXT NOT NULL,
				status TEXT NOT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
			copySQL: `INSERT INTO %s (
				name, description, spec_json, status, created_at, updated_at
			) SELECT
				name, description, spec_json, status, created_at, updated_at
			FROM %s`,
		},
		{
			table: "skills",
			createSQL: `CREATE TABLE %s (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				description TEXT NOT NULL,
				tags_json TEXT NOT NULL,
				content TEXT NOT NULL,
				files_json TEXT NOT NULL,
				status TEXT NOT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
			copySQL: `INSERT INTO %s (
				name, description, tags_json, content, files_json, status, created_at, updated_at
			) SELECT
				name, description, tags_json, content, files_json, status, created_at, updated_at
			FROM %s`,
		},
		{
			table: "mcp_configs",
			createSQL: `CREATE TABLE %s (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				command TEXT NOT NULL,
				args_json TEXT NOT NULL,
				env_json TEXT NOT NULL,
				transport TEXT NOT NULL,
				description TEXT NOT NULL,
				status TEXT NOT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
			copySQL: `INSERT INTO %s (
				name, command, args_json, env_json, transport, description, status, created_at, updated_at
			) SELECT
				name, command, args_json, env_json, transport, description, status, created_at, updated_at
			FROM %s`,
		},
		{
			table: "agent_specs",
			createSQL: `CREATE TABLE %s (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				version TEXT NOT NULL,
				description TEXT NOT NULL,
				tags_json TEXT NOT NULL,
				model_ref TEXT NOT NULL,
				prompt_json TEXT NOT NULL,
				skill_refs_json TEXT NOT NULL,
				mcp_refs_json TEXT NOT NULL,
				sandbox_ref TEXT NOT NULL,
				subagents_json TEXT NOT NULL,
				interrupt_on_json TEXT NOT NULL,
				status TEXT NOT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
			copySQL: `INSERT INTO %s (
				name, version, description, tags_json, model_ref, prompt_json,
				skill_refs_json, mcp_refs_json, sandbox_ref, subagents_json,
				interrupt_on_json, status, created_at, updated_at
			) SELECT
				name, version, description, tags_json, model_ref, prompt_json,
				skill_refs_json, mcp_refs_json, sandbox_ref, subagents_json,
				interrupt_on_json, status, created_at, updated_at
			FROM %s`,
		},
		{
			table: "runtime_targets",
			createSQL: `CREATE TABLE %s (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				kind TEXT NOT NULL,
				endpoint TEXT NOT NULL,
				description TEXT NOT NULL,
				metadata_json TEXT NOT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
			copySQL: `INSERT INTO %s (
				name, kind, endpoint, description, metadata_json, created_at, updated_at
			) SELECT
				name, kind, endpoint, description, metadata_json, created_at, updated_at
			FROM %s`,
		},
		{
			table: "deployments",
			createSQL: `CREATE TABLE %s (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				agent_name TEXT NOT NULL,
				target_name TEXT NOT NULL,
				desired_state TEXT NOT NULL,
				observed_state TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
			copySQL: `INSERT INTO %s (
				agent_name, target_name, desired_state, observed_state, updated_at
			) SELECT
				agent_name, target_name, desired_state, observed_state, updated_at
			FROM %s`,
		},
		{
			table: "operations",
			createSQL: `CREATE TABLE %s (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				operation_id TEXT NOT NULL,
				agent_name TEXT NOT NULL,
				target_name TEXT NOT NULL,
				kind TEXT NOT NULL,
				status TEXT NOT NULL,
				error_message TEXT NOT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL
			)`,
			copySQL: `INSERT INTO %s (
				operation_id, agent_name, target_name, kind, status, error_message, created_at, updated_at
			) SELECT
				id, agent_name, target_name, kind, status, error_message, created_at, updated_at
			FROM %s`,
			needsMigration: func(columns []sqliteColumnInfo) bool {
				return !hasSQLiteIntegerPrimaryKey(columns) || !hasSQLiteColumn(columns, "operation_id")
			},
		},
	}

	for _, migration := range migrations {
		if err := ensureSQLiteTableUsesSurrogatePrimaryKey(ctx, db, migration); err != nil {
			return err
		}
	}
	return nil
}

type sqliteTableMigration struct {
	table          string
	createSQL      string
	copySQL        string
	needsMigration func(columns []sqliteColumnInfo) bool
}

func ensureSQLiteTableUsesSurrogatePrimaryKey(
	ctx context.Context,
	db *sql.DB,
	migration sqliteTableMigration,
) error {
	columns, err := readSQLiteTableInfo(ctx, db, migration.table)
	if err != nil {
		return err
	}

	needsMigration := !hasSQLiteIntegerPrimaryKey(columns)
	if migration.needsMigration != nil {
		needsMigration = migration.needsMigration(columns)
	}
	if !needsMigration {
		return nil
	}

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin sqlite table migration for %s: %w", migration.table, err)
	}
	defer func() {
		_ = tx.Rollback()
	}()

	tempTable := migration.table + "_new"
	if _, err := tx.ExecContext(ctx, fmt.Sprintf("DROP TABLE IF EXISTS %s", quoteSQLiteIdentifier(tempTable))); err != nil {
		return fmt.Errorf("drop temp sqlite table for %s: %w", migration.table, err)
	}
	if _, err := tx.ExecContext(ctx, fmt.Sprintf(migration.createSQL, quoteSQLiteIdentifier(tempTable))); err != nil {
		return fmt.Errorf("create temp sqlite table for %s: %w", migration.table, err)
	}
	if _, err := tx.ExecContext(
		ctx,
		fmt.Sprintf(
			migration.copySQL,
			quoteSQLiteIdentifier(tempTable),
			quoteSQLiteIdentifier(migration.table),
		),
	); err != nil {
		return fmt.Errorf("copy sqlite rows for %s: %w", migration.table, err)
	}
	if _, err := tx.ExecContext(ctx, fmt.Sprintf("DROP TABLE %s", quoteSQLiteIdentifier(migration.table))); err != nil {
		return fmt.Errorf("drop legacy sqlite table for %s: %w", migration.table, err)
	}
	if _, err := tx.ExecContext(
		ctx,
		fmt.Sprintf(
			"ALTER TABLE %s RENAME TO %s",
			quoteSQLiteIdentifier(tempTable),
			quoteSQLiteIdentifier(migration.table),
		),
	); err != nil {
		return fmt.Errorf("rename sqlite table for %s: %w", migration.table, err)
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit sqlite table migration for %s: %w", migration.table, err)
	}
	return nil
}

func hasSQLiteColumn(columns []sqliteColumnInfo, name string) bool {
	for _, column := range columns {
		if strings.EqualFold(column.name, name) {
			return true
		}
	}
	return false
}

func hasSQLiteIntegerPrimaryKey(columns []sqliteColumnInfo) bool {
	for _, column := range columns {
		if strings.EqualFold(column.name, "id") &&
			column.primaryKey == 1 &&
			strings.Contains(strings.ToUpper(column.dataType), "INT") {
			return true
		}
	}
	return false
}

func quoteSQLiteIdentifier(value string) string {
	return `"` + strings.ReplaceAll(value, `"`, `""`) + `"`
}
