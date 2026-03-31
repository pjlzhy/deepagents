package registry

import (
	"agentctl/pkg/domain"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"
)

// UpsertSandboxConfig persists one reusable sandbox configuration snapshot.
func (r *SQLiteRegistry) UpsertSandboxConfig(ctx context.Context, config domain.SandboxConfig) error {
	if err := validateRequiredSimpleName(config.Name, "sandbox config name"); err != nil {
		return err
	}

	var err error
	config.Spec, err = domain.NormalizeSandboxSpec(config.Spec)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrInvalid, err)
	}
	if config.Spec.Empty() {
		return fmt.Errorf("%w: sandbox config spec must define one backend", ErrInvalid)
	}

	current, err := r.GetSandboxConfig(ctx, config.Name)
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
		return fmt.Errorf("marshal sandbox config spec: %w", err)
	}

	_, err = r.db.ExecContext(
		ctx,
		`INSERT INTO sandbox_configs (
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
		return fmt.Errorf("upsert sandbox config %q: %w", config.Name, err)
	}
	return nil
}

// GetSandboxConfig reads one reusable sandbox configuration.
func (r *SQLiteRegistry) GetSandboxConfig(ctx context.Context, name string) (domain.SandboxConfig, error) {
	row := r.db.QueryRowContext(
		ctx,
		`SELECT description, spec_json, status, created_at, updated_at
		FROM sandbox_configs WHERE name = ?`,
		name,
	)

	var config domain.SandboxConfig
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
			return domain.SandboxConfig{}, notFound("sandbox config", name)
		}
		return domain.SandboxConfig{}, fmt.Errorf("scan sandbox config %q: %w", name, err)
	}

	config.Name = name
	config.Status = domain.AuthoredStatus(status)
	if err := unmarshalJSON(specJSON, &config.Spec); err != nil {
		return domain.SandboxConfig{}, fmt.Errorf("decode sandbox config spec: %w", err)
	}
	var err error
	config.Spec, err = domain.NormalizeSandboxSpec(config.Spec)
	if err != nil {
		return domain.SandboxConfig{}, fmt.Errorf("normalize sandbox config spec: %w", err)
	}
	config.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.SandboxConfig{}, err
	}
	config.UpdatedAt, err = parseTime(updatedAt)
	if err != nil {
		return domain.SandboxConfig{}, err
	}
	return config, nil
}

// ListSandboxConfigs lists all sandbox configs ordered by name.
func (r *SQLiteRegistry) ListSandboxConfigs(ctx context.Context) ([]domain.SandboxConfig, error) {
	page, err := r.ListSandboxConfigsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

// ListSandboxConfigsPage lists one page of sandbox configs ordered by name.
func (r *SQLiteRegistry) ListSandboxConfigsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.SandboxConfig], error) {
	names, metadata, err := listNamesPage(ctx, r.db, "sandbox_configs", query)
	if err != nil {
		return domain.ResourcePage[domain.SandboxConfig]{}, err
	}

	configs := make([]domain.SandboxConfig, 0, len(names))
	for _, name := range names {
		config, err := r.GetSandboxConfig(ctx, name)
		if err != nil {
			return domain.ResourcePage[domain.SandboxConfig]{}, err
		}
		configs = append(configs, config)
	}

	return domain.ResourcePage[domain.SandboxConfig]{
		Items:        configs,
		PageMetadata: metadata,
	}, nil
}

// DeleteSandboxConfig removes one reusable sandbox configuration.
func (r *SQLiteRegistry) DeleteSandboxConfig(ctx context.Context, name string) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin delete sandbox config tx: %w", err)
	}
	defer func() {
		_ = tx.Rollback()
	}()

	if err := ensureSandboxDeleteAllowed(ctx, tx, name); err != nil {
		return err
	}
	if err := deleteByName(ctx, tx, "sandbox_configs", name, "sandbox config"); err != nil {
		return err
	}
	return tx.Commit()
}
