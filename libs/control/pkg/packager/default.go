package packager

import (
	"agentctl/pkg/domain"
	"context"
	"fmt"
	"maps"
	"path"
	"slices"
	"strings"
)

var _ Packager = (*DefaultPackager)(nil)

var supportedMCPTransports = map[string]struct{}{
	"stdio":           {},
	"sse":             {},
	"http":            {},
	"streamable_http": {},
}

var supportedSandboxBackends = map[string]struct{}{
	"local":  {},
	"docker": {},
	"k8s":    {},
}

var sandboxBackendAliases = map[string]string{
	"filesystem": "local",
	"kubernetes": "k8s",
	"shell":      "local",
}

// DefaultPackager 将 resolved authored input 打包为 runtime-ready spec。
type DefaultPackager struct{}

// NewDefaultPackager 创建默认的纯转换型 packager。
func NewDefaultPackager() *DefaultPackager {
	return &DefaultPackager{}
}

// Package 将 authored resources 聚合成运行时规格。
func (p *DefaultPackager) Package(
	ctx context.Context,
	input domain.ResolvedAgentInput,
) (domain.RuntimeAgentSpec, error) {
	if err := ctx.Err(); err != nil {
		return domain.RuntimeAgentSpec{}, err
	}

	agent := input.Agent
	if err := validateRequiredSimpleName(agent.Name, "agent name"); err != nil {
		return domain.RuntimeAgentSpec{}, err
	}
	model := cloneModelSpec(input.ModelConfig.Spec)
	if err := validateModelSpec(model, "resolved agent model", true); err != nil {
		return domain.RuntimeAgentSpec{}, err
	}

	skills, err := packageSkills(agent.SkillRefs, input.Skills)
	if err != nil {
		return domain.RuntimeAgentSpec{}, err
	}

	mcpServers, err := packageMCPConfigs(agent.MCPRefs, input.MCPConfigs)
	if err != nil {
		return domain.RuntimeAgentSpec{}, err
	}

	subagents, err := packageSubagents(agent.Subagents)
	if err != nil {
		return domain.RuntimeAgentSpec{}, err
	}

	sandbox, err := packageSandbox(domain.SandboxSpec{})
	if input.SandboxConfig != nil {
		sandbox, err = packageSandbox(input.SandboxConfig.Spec)
	}
	if err != nil {
		return domain.RuntimeAgentSpec{}, err
	}

	interruptOn, err := packageInterrupts(agent.InterruptOn)
	if err != nil {
		return domain.RuntimeAgentSpec{}, err
	}

	return domain.RuntimeAgentSpec{
		Name:        agent.Name,
		Version:     agent.Version,
		Description: agent.Description,
		Tags:        slices.Clone(agent.Tags),
		Model:       model,
		Prompt:      domain.PromptSpec{System: agent.Prompt.System},
		Skills:      skills,
		MCPServers:  mcpServers,
		Subagents:   subagents,
		Sandbox:     sandbox,
		InterruptOn: interruptOn,
	}, nil
}

func packageSkills(refs []string, resolved []domain.Skill) ([]domain.Skill, error) {
	if len(refs) != len(resolved) {
		return nil, fmt.Errorf(
			"resolved skill count mismatch: refs=%d resolved=%d",
			len(refs),
			len(resolved),
		)
	}

	seenRefs := make(map[string]struct{}, len(refs))
	byName := make(map[string]domain.Skill, len(resolved))
	for _, skill := range resolved {
		if err := validateRequiredSimpleName(skill.Name, "skill name"); err != nil {
			return nil, err
		}
		if _, exists := byName[skill.Name]; exists {
			return nil, fmt.Errorf("duplicate resolved skill: %s", skill.Name)
		}

		files, err := cloneSkillFiles(skill.Name, skill.Files)
		if err != nil {
			return nil, err
		}

		cloned := skill
		cloned.Tags = slices.Clone(skill.Tags)
		cloned.Files = files
		byName[skill.Name] = cloned
	}

	packaged := make([]domain.Skill, 0, len(refs))
	for _, ref := range refs {
		name := strings.TrimSpace(ref)
		if err := validateRequiredSimpleName(name, "skill ref"); err != nil {
			return nil, err
		}
		if _, exists := seenRefs[name]; exists {
			return nil, fmt.Errorf("duplicate skill ref: %s", name)
		}
		seenRefs[name] = struct{}{}

		skill, ok := byName[name]
		if !ok {
			return nil, fmt.Errorf("skill ref %q was not resolved", name)
		}
		packaged = append(packaged, skill)
	}
	return packaged, nil
}

func cloneSkillFiles(skillName string, files []domain.SkillFile) ([]domain.SkillFile, error) {
	cloned := make([]domain.SkillFile, 0, len(files))
	seenPaths := make(map[string]struct{}, len(files))
	for _, file := range files {
		normalizedPath, err := normalizeSkillFilePath(file.Path)
		if err != nil {
			return nil, fmt.Errorf("skill %q: %w", skillName, err)
		}
		if _, exists := seenPaths[normalizedPath]; exists {
			return nil, fmt.Errorf("skill %q has duplicate file path %q", skillName, normalizedPath)
		}
		seenPaths[normalizedPath] = struct{}{}

		cloned = append(cloned, domain.SkillFile{
			Path:    normalizedPath,
			Content: file.Content,
		})
	}
	return cloned, nil
}

func packageMCPConfigs(refs []string, resolved []domain.MCPConfig) ([]domain.MCPConfig, error) {
	if len(refs) != len(resolved) {
		return nil, fmt.Errorf(
			"resolved mcp config count mismatch: refs=%d resolved=%d",
			len(refs),
			len(resolved),
		)
	}

	seenRefs := make(map[string]struct{}, len(refs))
	byName := make(map[string]domain.MCPConfig, len(resolved))
	for _, cfg := range resolved {
		name := strings.TrimSpace(cfg.Name)
		if err := validateRequiredNonEmpty(name, "mcp server name"); err != nil {
			return nil, err
		}
		if _, exists := byName[name]; exists {
			return nil, fmt.Errorf("duplicate resolved mcp config: %s", name)
		}
		transport := strings.ToLower(strings.TrimSpace(cfg.Transport))
		if err := validateMCPTransport(name, transport); err != nil {
			return nil, err
		}
		if err := validateRequiredNonEmpty(cfg.Command, fmt.Sprintf("mcp server %q command", name)); err != nil {
			return nil, err
		}

		cloned := cfg
		cloned.Name = name
		cloned.Transport = transport
		cloned.Args = slices.Clone(cfg.Args)
		cloned.Env = maps.Clone(cfg.Env)
		byName[name] = cloned
	}

	packaged := make([]domain.MCPConfig, 0, len(refs))
	for _, ref := range refs {
		name := strings.TrimSpace(ref)
		if err := validateRequiredNonEmpty(name, "mcp ref"); err != nil {
			return nil, err
		}
		if _, exists := seenRefs[name]; exists {
			return nil, fmt.Errorf("duplicate mcp ref: %s", name)
		}
		seenRefs[name] = struct{}{}

		cfg, ok := byName[name]
		if !ok {
			return nil, fmt.Errorf("mcp ref %q was not resolved", name)
		}
		packaged = append(packaged, cfg)
	}
	return packaged, nil
}

func packageSubagents(subagents []domain.SubagentSpec) ([]domain.SubagentSpec, error) {
	cloned := make([]domain.SubagentSpec, 0, len(subagents))
	seen := make(map[string]struct{}, len(subagents))
	for _, subagent := range subagents {
		name := strings.TrimSpace(subagent.Name)
		if err := validateRequiredNonEmpty(name, "subagent name"); err != nil {
			return nil, err
		}
		if _, exists := seen[name]; exists {
			return nil, fmt.Errorf("duplicate subagent name: %s", name)
		}
		seen[name] = struct{}{}

		if err := validateRequiredNonEmpty(
			subagent.Description,
			fmt.Sprintf("subagent %q description", name),
		); err != nil {
			return nil, err
		}
		if err := validateRequiredNonEmpty(
			subagent.SystemPrompt,
			fmt.Sprintf("subagent %q system_prompt", name),
		); err != nil {
			return nil, err
		}
		if err := validateModelSpec(subagent.Model, fmt.Sprintf("subagent %q model", name), false); err != nil {
			return nil, err
		}

		cloned = append(cloned, domain.SubagentSpec{
			Name:         name,
			Description:  subagent.Description,
			SystemPrompt: subagent.SystemPrompt,
			Model:        cloneModelSpec(subagent.Model),
		})
	}
	return cloned, nil
}

func packageSandbox(spec domain.SandboxSpec) (domain.SandboxSpec, error) {
	normalized, err := domain.NormalizeSandboxSpec(spec)
	if err != nil {
		return domain.SandboxSpec{}, err
	}
	return domain.CloneSandboxSpec(normalized), nil
}

func packageInterrupts(interrupts []string) ([]string, error) {
	cloned := make([]string, 0, len(interrupts))
	seen := make(map[string]struct{}, len(interrupts))
	for _, interrupt := range interrupts {
		name := strings.TrimSpace(interrupt)
		if err := validateRequiredNonEmpty(name, "interrupt_on entry"); err != nil {
			return nil, err
		}
		if _, exists := seen[name]; exists {
			return nil, fmt.Errorf("duplicate interrupt_on entry: %s", name)
		}
		seen[name] = struct{}{}
		cloned = append(cloned, name)
	}
	return cloned, nil
}

func cloneModelSpec(spec domain.ModelSpec) domain.ModelSpec {
	return domain.ModelSpec{
		Provider:    spec.Provider,
		Model:       spec.Model,
		BaseURL:     spec.BaseURL,
		APIKeyEnv:   spec.APIKeyEnv,
		ExtraParams: maps.Clone(spec.ExtraParams),
	}
}

func validateModelSpec(spec domain.ModelSpec, fieldName string, required bool) error {
	provider := strings.TrimSpace(spec.Provider)
	model := strings.TrimSpace(spec.Model)
	if !required && provider == "" && model == "" {
		return nil
	}
	if provider == "" || model == "" {
		return fmt.Errorf("%s must include both provider and model", fieldName)
	}
	return nil
}

func validateMCPTransport(name string, transport string) error {
	if transport == "" {
		return fmt.Errorf("mcp server %q transport cannot be empty", name)
	}
	if _, ok := supportedMCPTransports[transport]; !ok {
		return fmt.Errorf("mcp server %q transport %q is not supported", name, transport)
	}
	return nil
}

func validateSandboxBackend(image string, resources map[string]string) error {
	backend := ""
	for _, key := range []string{"backend", "kind", "provider"} {
		if value, ok := resources[key]; ok {
			backend = strings.ToLower(strings.TrimSpace(value))
			break
		}
	}
	if backend == "" {
		if strings.TrimSpace(image) != "" {
			backend = "docker"
		} else {
			backend = "local"
		}
	}

	if alias, ok := sandboxBackendAliases[backend]; ok {
		backend = alias
	}
	if _, ok := supportedSandboxBackends[backend]; !ok {
		return fmt.Errorf("sandbox backend %q is not supported", backend)
	}
	return nil
}

func normalizeSkillFilePath(raw string) (string, error) {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return "", fmt.Errorf("skill file path cannot be empty")
	}
	if strings.HasPrefix(trimmed, "/") || strings.HasPrefix(trimmed, "\\") {
		return "", fmt.Errorf("skill file path must be relative: %s", raw)
	}
	if len(trimmed) >= 2 && trimmed[1] == ':' {
		return "", fmt.Errorf("skill file path must be relative: %s", raw)
	}
	if strings.HasSuffix(trimmed, "/") || strings.HasSuffix(trimmed, "\\") {
		return "", fmt.Errorf("skill file path must point to a file: %s", raw)
	}

	normalized := strings.ReplaceAll(trimmed, "\\", "/")
	cleaned := path.Clean(normalized)
	switch {
	case cleaned == ".":
		return "", fmt.Errorf("skill file path must point to a file: %s", raw)
	case cleaned == "..":
		return "", fmt.Errorf("skill file path escapes skill directory: %s", raw)
	case strings.HasPrefix(cleaned, "../"):
		return "", fmt.Errorf("skill file path escapes skill directory: %s", raw)
	case cleaned == "SKILL.md":
		return "", fmt.Errorf("skill file path 'SKILL.md' is reserved")
	}
	return cleaned, nil
}

func validateRequiredSimpleName(value string, fieldName string) error {
	name := strings.TrimSpace(value)
	if err := validateRequiredNonEmpty(name, fieldName); err != nil {
		return err
	}
	if name == "." || name == ".." {
		return fmt.Errorf("%s must be a simple name without path separators", fieldName)
	}
	if strings.ContainsAny(name, "/\\") {
		return fmt.Errorf("%s must be a simple name without path separators", fieldName)
	}
	return nil
}

func validateRequiredNonEmpty(value string, fieldName string) error {
	if strings.TrimSpace(value) == "" {
		return fmt.Errorf("%s cannot be empty", fieldName)
	}
	return nil
}
