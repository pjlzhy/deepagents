package registry

import (
	"agentctl/pkg/domain"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"
)

// SQLiteRegistry 提供 SQLite-backed registry 实现。
type SQLiteRegistry struct {
	db *sql.DB
}

// NewSQLiteRegistry 创建一个新的 SQLite registry。
func NewSQLiteRegistry(db *sql.DB) (*SQLiteRegistry, error) {
	if db == nil {
		return nil, errors.New("db must not be nil")
	}
	return &SQLiteRegistry{db: db}, nil
}

// UpsertSkill 持久化一个技能目录快照。
func (r *SQLiteRegistry) UpsertSkill(ctx context.Context, skill domain.Skill) error {
	if skill.Name == "" {
		return errors.New("skill name must not be empty")
	}
	current, err := r.GetSkill(ctx, skill.Name)
	if err != nil && !errors.Is(err, ErrNotFound) {
		return err
	}
	now := time.Now().UTC()
	if errors.Is(err, ErrNotFound) {
		if skill.CreatedAt.IsZero() {
			skill.CreatedAt = now
		}
	} else if skill.CreatedAt.IsZero() {
		skill.CreatedAt = current.CreatedAt
	}
	if skill.UpdatedAt.IsZero() {
		skill.UpdatedAt = now
	}

	tagsJSON, err := marshalJSON(skill.Tags)
	if err != nil {
		return fmt.Errorf("marshal skill tags: %w", err)
	}
	filesJSON, err := marshalJSON(skill.Files)
	if err != nil {
		return fmt.Errorf("marshal skill files: %w", err)
	}

	_, err = r.db.ExecContext(
		ctx,
		`INSERT INTO skills (
			name, description, tags_json, content, files_json, status, created_at, updated_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(name) DO UPDATE SET
			description = excluded.description,
			tags_json = excluded.tags_json,
			content = excluded.content,
			files_json = excluded.files_json,
			status = excluded.status,
			created_at = excluded.created_at,
			updated_at = excluded.updated_at`,
		skill.Name,
		skill.Description,
		tagsJSON,
		skill.Content,
		filesJSON,
		string(skill.Status),
		formatTime(skill.CreatedAt),
		formatTime(skill.UpdatedAt),
	)
	if err != nil {
		return fmt.Errorf("upsert skill %q: %w", skill.Name, err)
	}
	return nil
}

// GetSkill 读取一个技能定义。
func (r *SQLiteRegistry) GetSkill(ctx context.Context, name string) (domain.Skill, error) {
	row := r.db.QueryRowContext(
		ctx,
		`SELECT description, tags_json, content, files_json, status, created_at, updated_at
		FROM skills WHERE name = ?`,
		name,
	)

	var skill domain.Skill
	var tagsJSON string
	var filesJSON string
	var status string
	var createdAt string
	var updatedAt string
	if err := row.Scan(
		&skill.Description,
		&tagsJSON,
		&skill.Content,
		&filesJSON,
		&status,
		&createdAt,
		&updatedAt,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return domain.Skill{}, notFound("skill", name)
		}
		return domain.Skill{}, fmt.Errorf("scan skill %q: %w", name, err)
	}
	skill.Name = name
	skill.Status = domain.AuthoredStatus(status)
	if err := unmarshalJSON(tagsJSON, &skill.Tags); err != nil {
		return domain.Skill{}, fmt.Errorf("decode skill tags: %w", err)
	}
	if err := unmarshalJSON(filesJSON, &skill.Files); err != nil {
		return domain.Skill{}, fmt.Errorf("decode skill files: %w", err)
	}
	var err error
	skill.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.Skill{}, err
	}
	skill.UpdatedAt, err = parseTime(updatedAt)
	if err != nil {
		return domain.Skill{}, err
	}
	return skill, nil
}

// ListSkills lists all skills ordered by name.
func (r *SQLiteRegistry) ListSkills(ctx context.Context) ([]domain.Skill, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT name FROM skills ORDER BY name ASC`)
	if err != nil {
		return nil, fmt.Errorf("query skill names: %w", err)
	}
	defer rows.Close()

	skills := make([]domain.Skill, 0)
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, fmt.Errorf("scan skill name: %w", err)
		}
		skill, err := r.GetSkill(ctx, name)
		if err != nil {
			return nil, err
		}
		skills = append(skills, skill)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate skill names: %w", err)
	}
	return skills, nil
}

// DeleteSkill 删除一个技能。若仍被 agent spec 引用则返回冲突错误。
func (r *SQLiteRegistry) DeleteSkill(ctx context.Context, name string) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin delete skill tx: %w", err)
	}
	defer func() {
		_ = tx.Rollback()
	}()

	if err := ensureSkillDeleteAllowed(ctx, tx, name); err != nil {
		return err
	}
	if err := deleteByName(ctx, tx, "skills", name, "skill"); err != nil {
		return err
	}
	return tx.Commit()
}

// UpsertMCPConfig 持久化一个 MCP 配置。
func (r *SQLiteRegistry) UpsertMCPConfig(ctx context.Context, config domain.MCPConfig) error {
	if config.Name == "" {
		return errors.New("mcp config name must not be empty")
	}
	current, err := r.GetMCPConfig(ctx, config.Name)
	if err != nil && !errors.Is(err, ErrNotFound) {
		return err
	}
	now := time.Now().UTC()
	if errors.Is(err, ErrNotFound) {
		if config.CreatedAt.IsZero() {
			config.CreatedAt = now
		}
	} else if config.CreatedAt.IsZero() {
		config.CreatedAt = current.CreatedAt
	}
	if config.UpdatedAt.IsZero() {
		config.UpdatedAt = now
	}

	argsJSON, err := marshalJSON(config.Args)
	if err != nil {
		return fmt.Errorf("marshal mcp args: %w", err)
	}
	envJSON, err := marshalJSON(config.Env)
	if err != nil {
		return fmt.Errorf("marshal mcp env: %w", err)
	}

	_, err = r.db.ExecContext(
		ctx,
		`INSERT INTO mcp_configs (
			name, command, args_json, env_json, transport, description, status, created_at, updated_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(name) DO UPDATE SET
			command = excluded.command,
			args_json = excluded.args_json,
			env_json = excluded.env_json,
			transport = excluded.transport,
			description = excluded.description,
			status = excluded.status,
			created_at = excluded.created_at,
			updated_at = excluded.updated_at`,
		config.Name,
		config.Command,
		argsJSON,
		envJSON,
		config.Transport,
		config.Description,
		string(config.Status),
		formatTime(config.CreatedAt),
		formatTime(config.UpdatedAt),
	)
	if err != nil {
		return fmt.Errorf("upsert mcp config %q: %w", config.Name, err)
	}
	return nil
}

// GetMCPConfig 读取一个 MCP 配置。
func (r *SQLiteRegistry) GetMCPConfig(ctx context.Context, name string) (domain.MCPConfig, error) {
	row := r.db.QueryRowContext(
		ctx,
		`SELECT command, args_json, env_json, transport, description, status, created_at, updated_at
		FROM mcp_configs WHERE name = ?`,
		name,
	)

	var config domain.MCPConfig
	var argsJSON string
	var envJSON string
	var status string
	var createdAt string
	var updatedAt string
	if err := row.Scan(
		&config.Command,
		&argsJSON,
		&envJSON,
		&config.Transport,
		&config.Description,
		&status,
		&createdAt,
		&updatedAt,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return domain.MCPConfig{}, notFound("mcp config", name)
		}
		return domain.MCPConfig{}, fmt.Errorf("scan mcp config %q: %w", name, err)
	}
	config.Name = name
	config.Status = domain.AuthoredStatus(status)
	if err := unmarshalJSON(argsJSON, &config.Args); err != nil {
		return domain.MCPConfig{}, fmt.Errorf("decode mcp args: %w", err)
	}
	if err := unmarshalJSON(envJSON, &config.Env); err != nil {
		return domain.MCPConfig{}, fmt.Errorf("decode mcp env: %w", err)
	}
	var err error
	config.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.MCPConfig{}, err
	}
	config.UpdatedAt, err = parseTime(updatedAt)
	if err != nil {
		return domain.MCPConfig{}, err
	}
	return config, nil
}

// ListMCPConfigs lists all MCP configs ordered by name.
func (r *SQLiteRegistry) ListMCPConfigs(ctx context.Context) ([]domain.MCPConfig, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT name FROM mcp_configs ORDER BY name ASC`)
	if err != nil {
		return nil, fmt.Errorf("query mcp config names: %w", err)
	}
	defer rows.Close()

	configs := make([]domain.MCPConfig, 0)
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, fmt.Errorf("scan mcp config name: %w", err)
		}
		config, err := r.GetMCPConfig(ctx, name)
		if err != nil {
			return nil, err
		}
		configs = append(configs, config)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate mcp config names: %w", err)
	}
	return configs, nil
}

// DeleteMCPConfig 删除一个 MCP 配置。若仍被引用则返回冲突错误。
func (r *SQLiteRegistry) DeleteMCPConfig(ctx context.Context, name string) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin delete mcp tx: %w", err)
	}
	defer func() {
		_ = tx.Rollback()
	}()

	if err := ensureMCPDeleteAllowed(ctx, tx, name); err != nil {
		return err
	}
	if err := deleteByName(ctx, tx, "mcp_configs", name, "mcp config"); err != nil {
		return err
	}
	return tx.Commit()
}
