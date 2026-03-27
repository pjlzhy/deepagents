package registry

import (
	"agentctl/pkg/domain"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"
)

// UpsertModelConfig persists one reusable model configuration snapshot.
func (r *SQLiteRegistry) UpsertModelConfig(ctx context.Context, config domain.ModelConfig) error {
	if config.Name == "" {
		return errors.New("model config name must not be empty")
	}

	config.Spec = normalizeModelSpec(config.Spec)
	if err := validateModelSpec(config.Spec, "model config", true); err != nil {
		return err
	}

	current, err := r.GetModelConfig(ctx, config.Name)
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

	specJSON, err := marshalJSON(config.Spec)
	if err != nil {
		return fmt.Errorf("marshal model config spec: %w", err)
	}

	_, err = r.db.ExecContext(
		ctx,
		`INSERT INTO model_configs (
			name, description, spec_json, status, created_at, updated_at
		) VALUES (?, ?, ?, ?, ?, ?)
		ON CONFLICT(name) DO UPDATE SET
			description = excluded.description,
			spec_json = excluded.spec_json,
			status = excluded.status,
			created_at = excluded.created_at,
			updated_at = excluded.updated_at`,
		config.Name,
		config.Description,
		specJSON,
		string(config.Status),
		formatTime(config.CreatedAt),
		formatTime(config.UpdatedAt),
	)
	if err != nil {
		return fmt.Errorf("upsert model config %q: %w", config.Name, err)
	}
	return nil
}

// GetModelConfig reads one reusable model configuration.
func (r *SQLiteRegistry) GetModelConfig(ctx context.Context, name string) (domain.ModelConfig, error) {
	row := r.db.QueryRowContext(
		ctx,
		`SELECT description, spec_json, status, created_at, updated_at
		FROM model_configs WHERE name = ?`,
		name,
	)

	var config domain.ModelConfig
	var specJSON string
	var status string
	var createdAt string
	var updatedAt string
	if err := row.Scan(
		&config.Description,
		&specJSON,
		&status,
		&createdAt,
		&updatedAt,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return domain.ModelConfig{}, notFound("model config", name)
		}
		return domain.ModelConfig{}, fmt.Errorf("scan model config %q: %w", name, err)
	}

	config.Name = name
	config.Status = domain.AuthoredStatus(status)
	if err := unmarshalJSON(specJSON, &config.Spec); err != nil {
		return domain.ModelConfig{}, fmt.Errorf("decode model config spec: %w", err)
	}
	config.Spec = normalizeModelSpec(config.Spec)

	var err error
	config.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.ModelConfig{}, err
	}
	config.UpdatedAt, err = parseTime(updatedAt)
	if err != nil {
		return domain.ModelConfig{}, err
	}
	return config, nil
}

// ListModelConfigs lists all reusable model configurations ordered by name.
func (r *SQLiteRegistry) ListModelConfigs(ctx context.Context) ([]domain.ModelConfig, error) {
	page, err := r.ListModelConfigsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

// ListModelConfigsPage lists one page of reusable model configurations ordered by name.
func (r *SQLiteRegistry) ListModelConfigsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.ModelConfig], error) {
	names, metadata, err := listNamesPage(ctx, r.db, "model_configs", query)
	if err != nil {
		return domain.ResourcePage[domain.ModelConfig]{}, err
	}

	configs := make([]domain.ModelConfig, 0, len(names))
	for _, name := range names {
		config, err := r.GetModelConfig(ctx, name)
		if err != nil {
			return domain.ResourcePage[domain.ModelConfig]{}, err
		}
		configs = append(configs, config)
	}

	return domain.ResourcePage[domain.ModelConfig]{
		Items:        configs,
		PageMetadata: metadata,
	}, nil
}

// DeleteModelConfig removes one reusable model configuration.
func (r *SQLiteRegistry) DeleteModelConfig(ctx context.Context, name string) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin delete model config tx: %w", err)
	}
	defer func() {
		_ = tx.Rollback()
	}()

	if err := ensureModelConfigDeleteAllowed(ctx, tx, name); err != nil {
		return err
	}
	if err := deleteByName(ctx, tx, "model_configs", name, "model config"); err != nil {
		return err
	}
	return tx.Commit()
}
