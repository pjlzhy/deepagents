package registry

import (
	"agentctl/pkg/domain"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"
)

// UpsertDeployment 持久化一个 deployment 绑定。
func (r *SQLiteRegistry) UpsertDeployment(ctx context.Context, deployment domain.Deployment) error {
	if deployment.AgentName == "" {
		return errors.New("deployment agent name must not be empty")
	}
	if deployment.TargetName == "" {
		return errors.New("deployment target name must not be empty")
	}
	if err := ensureExists(ctx, r.db, "agent_specs", deployment.AgentName, "agent spec"); err != nil {
		return err
	}
	if err := ensureExists(ctx, r.db, "runtime_targets", deployment.TargetName, "runtime target"); err != nil {
		return err
	}
	if deployment.UpdatedAt.IsZero() {
		deployment.UpdatedAt = time.Now().UTC()
	}

	_, err := r.db.ExecContext(
		ctx,
		`INSERT INTO deployments (
			agent_name, target_name, desired_state, observed_state, updated_at
		) VALUES (?, ?, ?, ?, ?)
		ON CONFLICT(agent_name) DO UPDATE SET
			target_name = excluded.target_name,
			desired_state = excluded.desired_state,
			observed_state = excluded.observed_state,
			updated_at = excluded.updated_at`,
		deployment.AgentName,
		deployment.TargetName,
		string(deployment.DesiredState),
		string(deployment.ObservedState),
		formatTime(deployment.UpdatedAt),
	)
	if err != nil {
		return fmt.Errorf("upsert deployment for agent %q: %w", deployment.AgentName, err)
	}
	return nil
}

// GetDeployment 读取一个 deployment。
func (r *SQLiteRegistry) GetDeployment(ctx context.Context, agentName string) (domain.Deployment, error) {
	row := r.db.QueryRowContext(
		ctx,
		`SELECT target_name, desired_state, observed_state, updated_at
		FROM deployments WHERE agent_name = ?`,
		agentName,
	)

	var deployment domain.Deployment
	var desiredState string
	var observedState string
	var updatedAt string
	if err := row.Scan(
		&deployment.TargetName,
		&desiredState,
		&observedState,
		&updatedAt,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return domain.Deployment{}, notFound("deployment", agentName)
		}
		return domain.Deployment{}, fmt.Errorf("scan deployment for agent %q: %w", agentName, err)
	}
	deployment.AgentName = agentName
	deployment.DesiredState = domain.DesiredDeploymentState(desiredState)
	deployment.ObservedState = domain.ObservedRuntimeState(observedState)
	var err error
	deployment.UpdatedAt, err = parseTime(updatedAt)
	if err != nil {
		return domain.Deployment{}, err
	}
	return deployment, nil
}

// UpsertRuntimeTarget 持久化一个 runtime target。
func (r *SQLiteRegistry) UpsertRuntimeTarget(ctx context.Context, target domain.RuntimeTarget) error {
	if target.Name == "" {
		return errors.New("runtime target name must not be empty")
	}
	current, err := r.GetRuntimeTarget(ctx, target.Name)
	if err != nil && !errors.Is(err, ErrNotFound) {
		return err
	}
	now := time.Now().UTC()
	if errors.Is(err, ErrNotFound) {
		if target.CreatedAt.IsZero() {
			target.CreatedAt = now
		}
	} else if target.CreatedAt.IsZero() {
		target.CreatedAt = current.CreatedAt
	}
	if target.UpdatedAt.IsZero() {
		target.UpdatedAt = now
	}
	metadataJSON, err := marshalJSON(target.Metadata)
	if err != nil {
		return fmt.Errorf("marshal runtime target metadata: %w", err)
	}

	_, err = r.db.ExecContext(
		ctx,
		`INSERT INTO runtime_targets (
			name, kind, endpoint, description, metadata_json, created_at, updated_at
		) VALUES (?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(name) DO UPDATE SET
			kind = excluded.kind,
			endpoint = excluded.endpoint,
			description = excluded.description,
			metadata_json = excluded.metadata_json,
			created_at = excluded.created_at,
			updated_at = excluded.updated_at`,
		target.Name,
		string(target.Kind),
		target.Endpoint,
		target.Description,
		metadataJSON,
		formatTime(target.CreatedAt),
		formatTime(target.UpdatedAt),
	)
	if err != nil {
		return fmt.Errorf("upsert runtime target %q: %w", target.Name, err)
	}
	return nil
}

// GetRuntimeTarget 读取一个 runtime target。
func (r *SQLiteRegistry) GetRuntimeTarget(ctx context.Context, name string) (domain.RuntimeTarget, error) {
	row := r.db.QueryRowContext(
		ctx,
		`SELECT kind, endpoint, description, metadata_json, created_at, updated_at
		FROM runtime_targets WHERE name = ?`,
		name,
	)

	var target domain.RuntimeTarget
	var kind string
	var metadataJSON string
	var createdAt string
	var updatedAt string
	if err := row.Scan(
		&kind,
		&target.Endpoint,
		&target.Description,
		&metadataJSON,
		&createdAt,
		&updatedAt,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return domain.RuntimeTarget{}, notFound("runtime target", name)
		}
		return domain.RuntimeTarget{}, fmt.Errorf("scan runtime target %q: %w", name, err)
	}
	target.Name = name
	target.Kind = domain.RuntimeTargetKind(kind)
	if err := unmarshalJSON(metadataJSON, &target.Metadata); err != nil {
		return domain.RuntimeTarget{}, fmt.Errorf("decode runtime target metadata: %w", err)
	}
	var err error
	target.CreatedAt, err = parseTime(createdAt)
	if err != nil {
		return domain.RuntimeTarget{}, err
	}
	target.UpdatedAt, err = parseTime(updatedAt)
	if err != nil {
		return domain.RuntimeTarget{}, err
	}
	return target, nil
}

// ListRuntimeTargets lists all runtime targets ordered by name.
func (r *SQLiteRegistry) ListRuntimeTargets(ctx context.Context) ([]domain.RuntimeTarget, error) {
	rows, err := r.db.QueryContext(
		ctx,
		`SELECT name, kind, endpoint, description, metadata_json, created_at, updated_at
		FROM runtime_targets
		ORDER BY name ASC`,
	)
	if err != nil {
		return nil, fmt.Errorf("query runtime targets: %w", err)
	}
	defer rows.Close()

	targets := make([]domain.RuntimeTarget, 0)
	for rows.Next() {
		var target domain.RuntimeTarget
		var kind string
		var metadataJSON string
		var createdAt string
		var updatedAt string
		if err := rows.Scan(
			&target.Name,
			&kind,
			&target.Endpoint,
			&target.Description,
			&metadataJSON,
			&createdAt,
			&updatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan runtime target row: %w", err)
		}
		target.Kind = domain.RuntimeTargetKind(kind)
		if err := unmarshalJSON(metadataJSON, &target.Metadata); err != nil {
			return nil, fmt.Errorf("decode runtime target metadata: %w", err)
		}
		target.CreatedAt, err = parseTime(createdAt)
		if err != nil {
			return nil, err
		}
		target.UpdatedAt, err = parseTime(updatedAt)
		if err != nil {
			return nil, err
		}
		targets = append(targets, target)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate runtime targets: %w", err)
	}
	return targets, nil
}

// CreateOperation 写入一条 operation 审计记录。
func (r *SQLiteRegistry) CreateOperation(ctx context.Context, operation domain.Operation) error {
	if operation.ID == "" {
		return errors.New("operation id must not be empty")
	}
	now := time.Now().UTC()
	if operation.CreatedAt.IsZero() {
		operation.CreatedAt = now
	}
	if operation.UpdatedAt.IsZero() {
		operation.UpdatedAt = now
	}

	_, err := r.db.ExecContext(
		ctx,
		`INSERT INTO operations (
			operation_id, agent_name, target_name, kind, status, error_message, created_at, updated_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		operation.ID,
		operation.AgentName,
		operation.TargetName,
		string(operation.Kind),
		string(operation.Status),
		operation.ErrorMessage,
		formatTime(operation.CreatedAt),
		formatTime(operation.UpdatedAt),
	)
	if err != nil {
		return fmt.Errorf("create operation %q: %w", operation.ID, err)
	}
	return nil
}
