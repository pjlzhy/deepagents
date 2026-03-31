package registry

import (
	"agentctl/pkg/domain"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"
)

// UpsertAgentSpec persists one authored agent spec.
func (r *SQLiteRegistry) UpsertAgentSpec(ctx context.Context, spec domain.AuthoredAgentSpec) error {
	var err error
	spec, err = normalizeAuthoredAgentSpec(spec)
	if err != nil {
		return err
	}
	if err := r.ensureAgentSpecReferencesExist(ctx, spec); err != nil {
		return err
	}

	current, err := r.GetAgentSpec(ctx, spec.Name)
	if err != nil && !errors.Is(err, ErrNotFound) {
		return err
	}
	now := time.Now().UTC()
	if errors.Is(err, ErrNotFound) {
		if spec.CreatedAt.IsZero() {
			spec.CreatedAt = now
		}
	} else if spec.CreatedAt.IsZero() {
		spec.CreatedAt = current.CreatedAt
	}
	if spec.UpdatedAt.IsZero() {
		spec.UpdatedAt = now
	}

	tagsJSON, err := marshalJSON(spec.Tags)
	if err != nil {
		return fmt.Errorf("marshal agent spec tags: %w", err)
	}
	promptJSON, err := marshalJSON(spec.Prompt)
	if err != nil {
		return fmt.Errorf("marshal agent spec prompt: %w", err)
	}
	skillRefsJSON, err := marshalJSON(spec.SkillRefs)
	if err != nil {
		return fmt.Errorf("marshal agent spec skill refs: %w", err)
	}
	mcpRefsJSON, err := marshalJSON(spec.MCPRefs)
	if err != nil {
		return fmt.Errorf("marshal agent spec mcp refs: %w", err)
	}
	subagentsJSON, err := marshalJSON(spec.Subagents)
	if err != nil {
		return fmt.Errorf("marshal agent spec subagents: %w", err)
	}
	interruptOnJSON, err := marshalJSON(spec.InterruptOn)
	if err != nil {
		return fmt.Errorf("marshal agent spec interrupt_on: %w", err)
	}

	_, err = r.db.ExecContext(
		ctx,
		`INSERT INTO agent_specs (
            name, version, description, tags_json, model_ref, prompt_json,
            skill_refs_json, mcp_refs_json, sandbox_ref, subagents_json,
            interrupt_on_json, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            version = excluded.version,
            description = excluded.description,
            tags_json = excluded.tags_json,
            model_ref = excluded.model_ref,
            prompt_json = excluded.prompt_json,
            skill_refs_json = excluded.skill_refs_json,
            mcp_refs_json = excluded.mcp_refs_json,
            sandbox_ref = excluded.sandbox_ref,
            subagents_json = excluded.subagents_json,
            interrupt_on_json = excluded.interrupt_on_json,
            status = excluded.status,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at`,
		spec.Name,
		spec.Version,
		spec.Description,
		tagsJSON,
		spec.ModelRef,
		promptJSON,
		skillRefsJSON,
		mcpRefsJSON,
		spec.SandboxRef,
		subagentsJSON,
		interruptOnJSON,
		string(spec.Status),
		formatTime(spec.CreatedAt),
		formatTime(spec.UpdatedAt),
	)
	if err != nil {
		return fmt.Errorf("upsert agent spec %q: %w", spec.Name, err)
	}
	return nil
}

func normalizeAuthoredAgentSpec(spec domain.AuthoredAgentSpec) (domain.AuthoredAgentSpec, error) {
	spec.Name = strings.TrimSpace(spec.Name)
	if err := validateRequiredSimpleName(spec.Name, "agent spec name"); err != nil {
		return domain.AuthoredAgentSpec{}, err
	}
	spec.Version = strings.TrimSpace(spec.Version)
	spec.ModelRef = strings.TrimSpace(spec.ModelRef)
	if err := validateRequiredSimpleName(spec.ModelRef, "agent model_ref"); err != nil {
		return domain.AuthoredAgentSpec{}, err
	}
	spec.SandboxRef = strings.TrimSpace(spec.SandboxRef)
	if spec.SandboxRef != "" {
		if err := validateRequiredSimpleName(spec.SandboxRef, "agent sandbox_ref"); err != nil {
			return domain.AuthoredAgentSpec{}, err
		}
	}

	var err error
	spec.SkillRefs, err = normalizeNamedRefs(spec.SkillRefs, "skill ref")
	if err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf(
			"validate agent spec %q skill refs: %w",
			spec.Name,
			err,
		)
	}
	spec.MCPRefs, err = normalizeNamedRefs(spec.MCPRefs, "mcp ref")
	if err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf(
			"validate agent spec %q mcp refs: %w",
			spec.Name,
			err,
		)
	}
	spec.Subagents, err = normalizeSubagents(spec.Subagents)
	if err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf(
			"validate agent spec %q subagents: %w",
			spec.Name,
			err,
		)
	}
	spec.InterruptOn, err = normalizeUniqueEntries(spec.InterruptOn, "interrupt_on entry")
	if err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf(
			"validate agent spec %q interrupt_on: %w",
			spec.Name,
			err,
		)
	}

	status := domain.AuthoredStatus(strings.TrimSpace(string(spec.Status)))
	if status != "" && !status.Valid() {
		return domain.AuthoredAgentSpec{}, fmt.Errorf(
			"%w: agent status %q is invalid",
			ErrInvalid,
			status,
		)
	}
	spec.Status = status
	return spec, nil
}

func (r *SQLiteRegistry) ensureAgentSpecReferencesExist(
	ctx context.Context,
	spec domain.AuthoredAgentSpec,
) error {
	if err := ensureExists(ctx, r.db, "model_configs", spec.ModelRef, "model config"); err != nil {
		return fmt.Errorf(
			"validate agent spec %q model ref %q: %w",
			spec.Name,
			spec.ModelRef,
			err,
		)
	}
	for _, name := range spec.SkillRefs {
		if err := ensureExists(ctx, r.db, "skills", name, "skill"); err != nil {
			return fmt.Errorf(
				"validate agent spec %q skill ref %q: %w",
				spec.Name,
				name,
				err,
			)
		}
	}
	for _, name := range spec.MCPRefs {
		if err := ensureExists(ctx, r.db, "mcp_configs", name, "mcp config"); err != nil {
			return fmt.Errorf(
				"validate agent spec %q mcp ref %q: %w",
				spec.Name,
				name,
				err,
			)
		}
	}
	if spec.SandboxRef != "" {
		if err := ensureExists(ctx, r.db, "sandbox_configs", spec.SandboxRef, "sandbox config"); err != nil {
			return fmt.Errorf(
				"validate agent spec %q sandbox ref %q: %w",
				spec.Name,
				spec.SandboxRef,
				err,
			)
		}
	}
	return nil
}

func normalizeNamedRefs(refs []string, label string) ([]string, error) {
	return normalizeSimpleNamedEntries(refs, label)
}

func normalizeSimpleNamedEntries(values []string, label string) ([]string, error) {
	normalized := make([]string, 0, len(values))
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		name := strings.TrimSpace(value)
		if err := validateRequiredSimpleName(name, label); err != nil {
			return nil, err
		}
		if _, exists := seen[name]; exists {
			return nil, fmt.Errorf("%w: duplicate %s %q", ErrInvalid, label, name)
		}
		seen[name] = struct{}{}
		normalized = append(normalized, name)
	}
	return normalized, nil
}

func normalizeUniqueEntries(values []string, label string) ([]string, error) {
	normalized := make([]string, 0, len(values))
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		name := strings.TrimSpace(value)
		if err := validateRequiredNonEmpty(name, label); err != nil {
			return nil, err
		}
		if _, exists := seen[name]; exists {
			return nil, fmt.Errorf("%w: duplicate %s %q", ErrInvalid, label, name)
		}
		seen[name] = struct{}{}
		normalized = append(normalized, name)
	}
	return normalized, nil
}

func normalizeSubagents(subagents []domain.SubagentSpec) ([]domain.SubagentSpec, error) {
	normalized := make([]domain.SubagentSpec, 0, len(subagents))
	seen := make(map[string]struct{}, len(subagents))
	for _, subagent := range subagents {
		name := strings.TrimSpace(subagent.Name)
		if err := validateRequiredSimpleName(name, "subagent name"); err != nil {
			return nil, err
		}
		if _, exists := seen[name]; exists {
			return nil, fmt.Errorf("%w: duplicate subagent name %q", ErrInvalid, name)
		}
		seen[name] = struct{}{}

		description := strings.TrimSpace(subagent.Description)
		if err := validateRequiredNonEmpty(
			description,
			fmt.Sprintf("subagent %q description", name),
		); err != nil {
			return nil, err
		}
		systemPrompt := strings.TrimSpace(subagent.SystemPrompt)
		if err := validateRequiredNonEmpty(
			systemPrompt,
			fmt.Sprintf("subagent %q system_prompt", name),
		); err != nil {
			return nil, err
		}

		model := normalizeModelSpec(subagent.Model)
		if err := validateModelSpec(model, fmt.Sprintf("subagent %q model", name), false); err != nil {
			return nil, err
		}

		normalized = append(normalized, domain.SubagentSpec{
			Name:         name,
			Description:  description,
			SystemPrompt: systemPrompt,
			Model:        model,
		})
	}
	return normalized, nil
}

func normalizeModelSpec(spec domain.ModelSpec) domain.ModelSpec {
	spec.Provider = strings.TrimSpace(spec.Provider)
	spec.Model = strings.TrimSpace(spec.Model)
	spec.BaseURL = strings.TrimSpace(spec.BaseURL)
	spec.APIKeyEnv = strings.TrimSpace(spec.APIKeyEnv)
	return spec
}

func validateModelSpec(spec domain.ModelSpec, fieldName string, required bool) error {
	if !required && spec.Provider == "" && spec.Model == "" {
		return nil
	}
	if spec.Provider == "" || spec.Model == "" {
		return fmt.Errorf("%w: %s must include both provider and model", ErrInvalid, fieldName)
	}
	return nil
}

func validateRequiredSimpleName(value string, fieldName string) error {
	if err := validateRequiredNonEmpty(value, fieldName); err != nil {
		return err
	}
	if value == "." || value == ".." || strings.ContainsAny(value, `/\`) {
		return fmt.Errorf(
			"%w: %s must be a simple name without path separators",
			ErrInvalid,
			fieldName,
		)
	}
	return nil
}

func validateRequiredNonEmpty(value string, fieldName string) error {
	if strings.TrimSpace(value) == "" {
		return fmt.Errorf("%w: %s must not be empty", ErrInvalid, fieldName)
	}
	return nil
}

// GetAgentSpec reads one authored agent spec.
func (r *SQLiteRegistry) GetAgentSpec(ctx context.Context, name string) (domain.AuthoredAgentSpec, error) {
	row := r.db.QueryRowContext(
		ctx,
		`SELECT version, description, tags_json, model_ref, prompt_json, skill_refs_json,
        mcp_refs_json, sandbox_ref, subagents_json, interrupt_on_json, status,
        created_at, updated_at
        FROM agent_specs WHERE name = ?`,
		name,
	)

	var spec domain.AuthoredAgentSpec
	var tagsJSON string
	var modelRef string
	var promptJSON string
	var skillRefsJSON string
	var mcpRefsJSON string
	var sandboxRef string
	var subagentsJSON string
	var interruptOnJSON string
	var status string
	var createdAt string
	var updatedAt string
	if err := row.Scan(
		&spec.Version,
		&spec.Description,
		&tagsJSON,
		&modelRef,
		&promptJSON,
		&skillRefsJSON,
		&mcpRefsJSON,
		&sandboxRef,
		&subagentsJSON,
		&interruptOnJSON,
		&status,
		&createdAt,
		&updatedAt,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return domain.AuthoredAgentSpec{}, notFound("agent spec", name)
		}
		return domain.AuthoredAgentSpec{}, fmt.Errorf("scan agent spec %q: %w", name, err)
	}
	spec.Name = name
	spec.ModelRef = strings.TrimSpace(modelRef)
	spec.SandboxRef = strings.TrimSpace(sandboxRef)
	spec.Status = domain.AuthoredStatus(status)
	if err := unmarshalJSON(tagsJSON, &spec.Tags); err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf("decode agent tags: %w", err)
	}
	if err := unmarshalJSON(promptJSON, &spec.Prompt); err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf("decode agent prompt: %w", err)
	}
	if err := unmarshalJSON(skillRefsJSON, &spec.SkillRefs); err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf("decode agent skill refs: %w", err)
	}
	if err := unmarshalJSON(mcpRefsJSON, &spec.MCPRefs); err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf("decode agent mcp refs: %w", err)
	}
	if err := unmarshalJSON(subagentsJSON, &spec.Subagents); err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf("decode agent subagents: %w", err)
	}
	if err := unmarshalJSON(interruptOnJSON, &spec.InterruptOn); err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf("decode agent interrupt_on: %w", err)
	}
	parsedCreatedAt, err := parseTime(createdAt)
	if err != nil {
		return domain.AuthoredAgentSpec{}, err
	}
	parsedUpdatedAt, err := parseTime(updatedAt)
	if err != nil {
		return domain.AuthoredAgentSpec{}, err
	}
	spec.CreatedAt = parsedCreatedAt
	spec.UpdatedAt = parsedUpdatedAt
	return spec, nil
}

// ListAgentSpecs lists all authored agent specs ordered by name.
func (r *SQLiteRegistry) ListAgentSpecs(ctx context.Context) ([]domain.AuthoredAgentSpec, error) {
	page, err := r.ListAgentSpecsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

// ListAgentSpecsPage lists one page of authored agent specs ordered by name.
func (r *SQLiteRegistry) ListAgentSpecsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.AuthoredAgentSpec], error) {
	names, metadata, err := listNamesPage(ctx, r.db, "agent_specs", query)
	if err != nil {
		return domain.ResourcePage[domain.AuthoredAgentSpec]{}, err
	}

	specs := make([]domain.AuthoredAgentSpec, 0, len(names))
	for _, name := range names {
		spec, err := r.GetAgentSpec(ctx, name)
		if err != nil {
			return domain.ResourcePage[domain.AuthoredAgentSpec]{}, err
		}
		specs = append(specs, spec)
	}

	return domain.ResourcePage[domain.AuthoredAgentSpec]{
		Items:        specs,
		PageMetadata: metadata,
	}, nil
}

// DeleteAgentSpec deletes one authored agent spec and the bound deployment.
func (r *SQLiteRegistry) DeleteAgentSpec(ctx context.Context, name string) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin delete agent spec tx: %w", err)
	}
	defer func() {
		_ = tx.Rollback()
	}()

	if err := deleteByName(ctx, tx, "agent_specs", name, "agent spec"); err != nil {
		return err
	}
	if _, err := tx.ExecContext(ctx, `DELETE FROM deployments WHERE agent_name = ?`, name); err != nil {
		return fmt.Errorf("delete deployment for agent %q: %w", name, err)
	}
	return tx.Commit()
}
