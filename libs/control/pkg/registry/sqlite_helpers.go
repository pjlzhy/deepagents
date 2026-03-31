package registry

import (
	"agentctl/pkg/domain"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"
)

func marshalJSON(value any) (string, error) {
	data, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func unmarshalJSON(data string, target any) error {
	if data == "" {
		data = "null"
	}
	return json.Unmarshal([]byte(data), target)
}

func formatTime(value time.Time) string {
	return value.UTC().Format(time.RFC3339Nano)
}

func parseTime(value string) (time.Time, error) {
	ts, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return time.Time{}, fmt.Errorf("parse timestamp %q: %w", value, err)
	}
	return ts, nil
}

func notFound(resourceType string, name string) error {
	return fmt.Errorf("%w: %s %q", ErrNotFound, resourceType, name)
}

func deleteByName(ctx context.Context, tx *sql.Tx, table string, name string, resourceType string) error {
	result, err := tx.ExecContext(ctx, fmt.Sprintf("DELETE FROM %s WHERE name = ?", table), name)
	if err != nil {
		return fmt.Errorf("delete %s %q: %w", resourceType, name, err)
	}
	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("rows affected deleting %s %q: %w", resourceType, name, err)
	}
	if rows == 0 {
		return notFound(resourceType, name)
	}
	return nil
}

func ensureSkillDeleteAllowed(ctx context.Context, tx *sql.Tx, name string) error {
	rows, err := tx.QueryContext(ctx, `SELECT name, skill_refs_json FROM agent_specs`)
	if err != nil {
		return fmt.Errorf("query skill references: %w", err)
	}
	defer rows.Close()

	for rows.Next() {
		var agentName string
		var refsJSON string
		if err := rows.Scan(&agentName, &refsJSON); err != nil {
			return fmt.Errorf("scan skill references: %w", err)
		}
		var refs []string
		if err := unmarshalJSON(refsJSON, &refs); err != nil {
			return fmt.Errorf("decode skill references: %w", err)
		}
		for _, ref := range refs {
			if ref == name {
				return fmt.Errorf("%w: skill %q is referenced by agent %q", ErrConflict, name, agentName)
			}
		}
	}
	return rows.Err()
}

func ensureMCPDeleteAllowed(ctx context.Context, tx *sql.Tx, name string) error {
	rows, err := tx.QueryContext(ctx, `SELECT name, mcp_refs_json FROM agent_specs`)
	if err != nil {
		return fmt.Errorf("query mcp references: %w", err)
	}
	defer rows.Close()

	for rows.Next() {
		var agentName string
		var refsJSON string
		if err := rows.Scan(&agentName, &refsJSON); err != nil {
			return fmt.Errorf("scan mcp references: %w", err)
		}
		var refs []string
		if err := unmarshalJSON(refsJSON, &refs); err != nil {
			return fmt.Errorf("decode mcp references: %w", err)
		}
		for _, ref := range refs {
			if ref == name {
				return fmt.Errorf("%w: mcp config %q is referenced by agent %q", ErrConflict, name, agentName)
			}
		}
	}
	return rows.Err()
}

func ensureSandboxDeleteAllowed(ctx context.Context, tx *sql.Tx, name string) error {
	rows, err := tx.QueryContext(ctx, `SELECT name, sandbox_ref FROM agent_specs`)
	if err != nil {
		return fmt.Errorf("query sandbox references: %w", err)
	}
	defer rows.Close()

	for rows.Next() {
		var agentName string
		var sandboxRef string
		if err := rows.Scan(&agentName, &sandboxRef); err != nil {
			return fmt.Errorf("scan sandbox references: %w", err)
		}
		if sandboxRef == name {
			return fmt.Errorf("%w: sandbox config %q is referenced by agent %q", ErrConflict, name, agentName)
		}
	}
	return rows.Err()
}

func ensureModelConfigDeleteAllowed(ctx context.Context, tx *sql.Tx, name string) error {
	rows, err := tx.QueryContext(ctx, `SELECT name, model_ref FROM agent_specs`)
	if err != nil {
		return fmt.Errorf("query model references: %w", err)
	}
	defer rows.Close()

	for rows.Next() {
		var agentName string
		var modelRef string
		if err := rows.Scan(&agentName, &modelRef); err != nil {
			return fmt.Errorf("scan model references: %w", err)
		}
		if modelRef == name {
			return fmt.Errorf("%w: model config %q is referenced by agent %q", ErrConflict, name, agentName)
		}
	}
	return rows.Err()
}

func ensureExists(ctx context.Context, db *sql.DB, table string, name string, resourceType string) error {
	var existing string
	err := db.QueryRowContext(
		ctx,
		fmt.Sprintf("SELECT name FROM %s WHERE name = ?", table),
		name,
	).Scan(&existing)
	if errors.Is(err, sql.ErrNoRows) {
		return notFound(resourceType, name)
	}
	if err != nil {
		return fmt.Errorf("check %s existence %q: %w", resourceType, name, err)
	}
	return nil
}

func normalizePageQuery(query domain.PageQuery) (domain.PageQuery, error) {
	if query.PageSize < 0 {
		return domain.PageQuery{}, fmt.Errorf("%w: page_size must be non-negative", ErrInvalid)
	}
	if query.PageNumber < 0 {
		return domain.PageQuery{}, fmt.Errorf("%w: page_number must be non-negative", ErrInvalid)
	}
	if query.PageSize == 0 {
		if query.PageNumber > 0 {
			return domain.PageQuery{}, fmt.Errorf("%w: page_number requires page_size", ErrInvalid)
		}
		return domain.PageQuery{}, nil
	}
	if query.PageNumber == 0 {
		query.PageNumber = 1
	}
	return query, nil
}

func countRows(ctx context.Context, db *sql.DB, table string) (int32, error) {
	var total int32
	if err := db.QueryRowContext(
		ctx,
		fmt.Sprintf("SELECT COUNT(*) FROM %s", table),
	).Scan(&total); err != nil {
		return 0, fmt.Errorf("count rows in %s: %w", table, err)
	}
	return total, nil
}

func totalPages(totalSize int32, pageSize int32) int32 {
	if totalSize <= 0 || pageSize <= 0 {
		return 0
	}
	return (totalSize + pageSize - 1) / pageSize
}

func listNamesPage(
	ctx context.Context,
	db *sql.DB,
	table string,
	query domain.PageQuery,
) ([]string, domain.PageMetadata, error) {
	normalizedQuery, err := normalizePageQuery(query)
	if err != nil {
		return nil, domain.PageMetadata{}, err
	}

	totalSize, err := countRows(ctx, db, table)
	if err != nil {
		return nil, domain.PageMetadata{}, err
	}

	metadata := domain.PageMetadata{TotalSize: totalSize}
	sqlQuery := fmt.Sprintf("SELECT name FROM %s ORDER BY name ASC", table)
	args := make([]any, 0, 2)
	if normalizedQuery.PageSize > 0 {
		metadata.PageSize = normalizedQuery.PageSize
		metadata.PageNumber = normalizedQuery.PageNumber
		metadata.TotalPages = totalPages(totalSize, normalizedQuery.PageSize)
		offset := int64(normalizedQuery.PageSize) * int64(normalizedQuery.PageNumber-1)
		sqlQuery += " LIMIT ? OFFSET ?"
		args = append(args, normalizedQuery.PageSize, offset)
	}

	rows, err := db.QueryContext(ctx, sqlQuery, args...)
	if err != nil {
		return nil, domain.PageMetadata{}, fmt.Errorf("query names from %s: %w", table, err)
	}
	defer rows.Close()

	names := make([]string, 0)
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, domain.PageMetadata{}, fmt.Errorf("scan name from %s: %w", table, err)
		}
		names = append(names, name)
	}
	if err := rows.Err(); err != nil {
		return nil, domain.PageMetadata{}, fmt.Errorf("iterate names from %s: %w", table, err)
	}
	return names, metadata, nil
}
