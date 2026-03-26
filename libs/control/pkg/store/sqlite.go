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

const sqliteSchema = `
CREATE TABLE IF NOT EXISTS skills (
	name TEXT PRIMARY KEY,
	description TEXT NOT NULL,
	tags_json TEXT NOT NULL,
	content TEXT NOT NULL,
	files_json TEXT NOT NULL,
	status TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_configs (
	name TEXT PRIMARY KEY,
	command TEXT NOT NULL,
	args_json TEXT NOT NULL,
	env_json TEXT NOT NULL,
	transport TEXT NOT NULL,
	description TEXT NOT NULL,
	status TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_specs (
	name TEXT PRIMARY KEY,
	version TEXT NOT NULL,
	description TEXT NOT NULL,
	tags_json TEXT NOT NULL,
	model_json TEXT NOT NULL,
	prompt_json TEXT NOT NULL,
	skill_refs_json TEXT NOT NULL,
	mcp_refs_json TEXT NOT NULL,
	subagents_json TEXT NOT NULL,
	sandbox_json TEXT NOT NULL,
	interrupt_on_json TEXT NOT NULL,
	status TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_targets (
	name TEXT PRIMARY KEY,
	kind TEXT NOT NULL,
	endpoint TEXT NOT NULL,
	description TEXT NOT NULL,
	metadata_json TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deployments (
	agent_name TEXT PRIMARY KEY,
	target_name TEXT NOT NULL,
	desired_state TEXT NOT NULL,
	observed_state TEXT NOT NULL,
	updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operations (
	id TEXT PRIMARY KEY,
	agent_name TEXT NOT NULL,
	target_name TEXT NOT NULL,
	kind TEXT NOT NULL,
	status TEXT NOT NULL,
	error_message TEXT NOT NULL,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);
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
	if _, err := s.db.ExecContext(ctx, sqliteSchema); err != nil {
		return fmt.Errorf("init sqlite schema: %w", err)
	}
	return nil
}
