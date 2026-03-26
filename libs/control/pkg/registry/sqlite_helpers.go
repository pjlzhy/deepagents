package registry

import (
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
