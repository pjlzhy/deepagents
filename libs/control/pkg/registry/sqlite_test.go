package registry

import (
	"agentctl/pkg/domain"
	"agentctl/pkg/store"
	"context"
	"errors"
	"path/filepath"
	"strings"
	"testing"
)

func TestSQLiteRegistryRoundTripsCoreResources(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	target := domain.RuntimeTarget{
		Name:        "runtime-a",
		Kind:        domain.RuntimeTargetKindLocalGRPC,
		Endpoint:    "127.0.0.1:50051",
		Description: "local runtime",
		Metadata:    map[string]string{"env": "dev"},
	}
	if err := reg.UpsertRuntimeTarget(ctx, target); err != nil {
		t.Fatalf("upsert runtime target: %v", err)
	}

	skill := domain.Skill{
		Name:        "research",
		Description: "research skill",
		Tags:        []string{"web"},
		Content:     "# SKILL",
		Files:       []domain.SkillFile{{Path: "scripts/run.sh", Content: "echo hi"}},
		Status:      domain.AuthoredStatusPublished,
	}
	if err := reg.UpsertSkill(ctx, skill); err != nil {
		t.Fatalf("upsert skill: %v", err)
	}

	config := domain.MCPConfig{
		Name:        "github",
		Command:     "npx",
		Args:        []string{"@modelcontextprotocol/server-github"},
		Env:         map[string]string{"GITHUB_TOKEN": "env:GITHUB_TOKEN"},
		Transport:   "stdio",
		Description: "github mcp",
		Status:      domain.AuthoredStatusPublished,
	}
	if err := reg.UpsertMCPConfig(ctx, config); err != nil {
		t.Fatalf("upsert mcp config: %v", err)
	}

	spec := domain.AuthoredAgentSpec{
		Name:        "demo-agent",
		Version:     "1.0.0",
		Description: "demo",
		Tags:        []string{"assistant"},
		Model:       domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		Prompt:      domain.PromptSpec{System: "You are helpful."},
		SkillRefs:   []string{"research"},
		MCPRefs:     []string{"github"},
		Subagents: []domain.SubagentSpec{{
			Name:         "helper",
			Description:  "secondary",
			SystemPrompt: "Assist the primary agent.",
		}},
		Sandbox:     domain.SandboxSpec{Image: "python:3.12", Resources: map[string]string{"backend": "docker"}},
		InterruptOn: []string{"execute"},
		Status:      domain.AuthoredStatusPublished,
	}
	if err := reg.UpsertAgentSpec(ctx, spec); err != nil {
		t.Fatalf("upsert agent spec: %v", err)
	}

	deployment := domain.Deployment{
		AgentName:     "demo-agent",
		TargetName:    "runtime-a",
		DesiredState:  domain.DesiredDeploymentStateCompiled,
		ObservedState: domain.ObservedRuntimeStateInstalled,
	}
	if err := reg.UpsertDeployment(ctx, deployment); err != nil {
		t.Fatalf("upsert deployment: %v", err)
	}

	gotSpec, err := reg.GetAgentSpec(ctx, "demo-agent")
	if err != nil {
		t.Fatalf("get agent spec: %v", err)
	}
	if len(gotSpec.SkillRefs) != 1 || gotSpec.SkillRefs[0] != "research" {
		t.Fatalf("unexpected skill refs: %#v", gotSpec.SkillRefs)
	}
	if gotSpec.Model.Model != "gpt-4o" {
		t.Fatalf("unexpected model: %#v", gotSpec.Model)
	}

	skills, err := reg.ListSkills(ctx)
	if err != nil {
		t.Fatalf("list skills: %v", err)
	}
	if len(skills) != 1 || skills[0].Name != "research" || len(skills[0].Files) != 1 {
		t.Fatalf("unexpected skill list: %#v", skills)
	}

	configs, err := reg.ListMCPConfigs(ctx)
	if err != nil {
		t.Fatalf("list mcp configs: %v", err)
	}
	if len(configs) != 1 || configs[0].Name != "github" || configs[0].Command != "npx" {
		t.Fatalf("unexpected mcp config list: %#v", configs)
	}

	list, err := reg.ListAgentSpecs(ctx)
	if err != nil {
		t.Fatalf("list agent specs: %v", err)
	}
	if len(list) != 1 || list[0].Name != "demo-agent" {
		t.Fatalf("unexpected agent spec list: %#v", list)
	}

	gotDeployment, err := reg.GetDeployment(ctx, "demo-agent")
	if err != nil {
		t.Fatalf("get deployment: %v", err)
	}
	if gotDeployment.TargetName != "runtime-a" {
		t.Fatalf("unexpected deployment target: %s", gotDeployment.TargetName)
	}

	targets, err := reg.ListRuntimeTargets(ctx)
	if err != nil {
		t.Fatalf("list runtime targets: %v", err)
	}
	if len(targets) != 1 || targets[0].Name != "runtime-a" || targets[0].Endpoint != "127.0.0.1:50051" {
		t.Fatalf("unexpected runtime target list: %#v", targets)
	}
}

func TestDeleteSkillRejectsReferencedSkill(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	if err := reg.UpsertSkill(ctx, domain.Skill{
		Name:    "research",
		Content: "# skill",
		Status:  domain.AuthoredStatusPublished,
	}); err != nil {
		t.Fatalf("upsert skill: %v", err)
	}
	if err := reg.UpsertAgentSpec(ctx, domain.AuthoredAgentSpec{
		Name:      "demo-agent",
		Prompt:    domain.PromptSpec{System: "test"},
		Model:     domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		SkillRefs: []string{"research"},
		Status:    domain.AuthoredStatusPublished,
	}); err != nil {
		t.Fatalf("upsert agent spec: %v", err)
	}

	err := reg.DeleteSkill(ctx, "research")
	if !errors.Is(err, ErrConflict) {
		t.Fatalf("expected conflict deleting referenced skill, got: %v", err)
	}
}

func TestUpsertAgentSpecRejectsMissingSkillReference(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	spec := domain.AuthoredAgentSpec{
		Name:      "demo-agent",
		Prompt:    domain.PromptSpec{System: "test"},
		Model:     domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		SkillRefs: []string{"research"},
		Status:    domain.AuthoredStatusPublished,
	}
	err := reg.UpsertAgentSpec(ctx, spec)
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected missing skill error, got: %v", err)
	}
	if !strings.Contains(err.Error(), `skill "research"`) {
		t.Fatalf("expected missing skill details in error, got: %v", err)
	}
	if _, err := reg.GetAgentSpec(ctx, spec.Name); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected agent spec to remain absent, got: %v", err)
	}
}

func TestUpsertAgentSpecRejectsMissingMCPReference(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	if err := reg.UpsertSkill(ctx, domain.Skill{
		Name:    "research",
		Content: "# skill",
		Status:  domain.AuthoredStatusPublished,
	}); err != nil {
		t.Fatalf("upsert skill: %v", err)
	}

	spec := domain.AuthoredAgentSpec{
		Name:      "demo-agent",
		Prompt:    domain.PromptSpec{System: "test"},
		Model:     domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		SkillRefs: []string{"research"},
		MCPRefs:   []string{"github"},
		Status:    domain.AuthoredStatusPublished,
	}
	err := reg.UpsertAgentSpec(ctx, spec)
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected missing mcp error, got: %v", err)
	}
	if !strings.Contains(err.Error(), `mcp config "github"`) {
		t.Fatalf("expected missing mcp details in error, got: %v", err)
	}
	if _, err := reg.GetAgentSpec(ctx, spec.Name); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected agent spec to remain absent, got: %v", err)
	}
}

func TestUpsertAgentSpecNormalizesReferenceWhitespace(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	if err := reg.UpsertSkill(ctx, domain.Skill{
		Name:    "research",
		Content: "# skill",
		Status:  domain.AuthoredStatusPublished,
	}); err != nil {
		t.Fatalf("upsert skill: %v", err)
	}
	if err := reg.UpsertMCPConfig(ctx, domain.MCPConfig{
		Name:      "github",
		Command:   "npx",
		Transport: "stdio",
		Status:    domain.AuthoredStatusPublished,
	}); err != nil {
		t.Fatalf("upsert mcp config: %v", err)
	}

	spec := domain.AuthoredAgentSpec{
		Name:      "demo-agent",
		Prompt:    domain.PromptSpec{System: "test"},
		Model:     domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		SkillRefs: []string{" research "},
		MCPRefs:   []string{" github "},
		Status:    domain.AuthoredStatusPublished,
	}
	if err := reg.UpsertAgentSpec(ctx, spec); err != nil {
		t.Fatalf("upsert agent spec: %v", err)
	}

	stored, err := reg.GetAgentSpec(ctx, "demo-agent")
	if err != nil {
		t.Fatalf("get agent spec: %v", err)
	}
	if len(stored.SkillRefs) != 1 || stored.SkillRefs[0] != "research" {
		t.Fatalf("expected normalized skill refs, got: %#v", stored.SkillRefs)
	}
	if len(stored.MCPRefs) != 1 || stored.MCPRefs[0] != "github" {
		t.Fatalf("expected normalized mcp refs, got: %#v", stored.MCPRefs)
	}
}

func TestUpsertAgentSpecRejectsEmptySkillReference(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	spec := domain.AuthoredAgentSpec{
		Name:      "demo-agent",
		Prompt:    domain.PromptSpec{System: "test"},
		Model:     domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		SkillRefs: []string{"   "},
		Status:    domain.AuthoredStatusPublished,
	}
	err := reg.UpsertAgentSpec(ctx, spec)
	if !errors.Is(err, ErrInvalid) {
		t.Fatalf("expected invalid skill ref error, got: %v", err)
	}
	if !strings.Contains(err.Error(), "skill ref must not be empty") {
		t.Fatalf("expected empty skill ref details in error, got: %v", err)
	}
}

func TestUpsertAgentSpecRejectsDuplicateMCPReference(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	spec := domain.AuthoredAgentSpec{
		Name:    "demo-agent",
		Prompt:  domain.PromptSpec{System: "test"},
		Model:   domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		MCPRefs: []string{"github", " github "},
		Status:  domain.AuthoredStatusPublished,
	}
	err := reg.UpsertAgentSpec(ctx, spec)
	if !errors.Is(err, ErrInvalid) {
		t.Fatalf("expected invalid mcp ref error, got: %v", err)
	}
	if !strings.Contains(err.Error(), `duplicate mcp ref "github"`) {
		t.Fatalf("expected duplicate mcp ref details in error, got: %v", err)
	}
}

func TestUpsertAgentSpecRejectsIncompleteModel(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	spec := domain.AuthoredAgentSpec{
		Name:   "demo-agent",
		Prompt: domain.PromptSpec{System: "test"},
		Model:  domain.ModelSpec{Provider: "openai"},
		Status: domain.AuthoredStatusPublished,
	}
	err := reg.UpsertAgentSpec(ctx, spec)
	if !errors.Is(err, ErrInvalid) {
		t.Fatalf("expected invalid model error, got: %v", err)
	}
	if !strings.Contains(err.Error(), "agent model must include both provider and model") {
		t.Fatalf("expected invalid model details in error, got: %v", err)
	}
}

func TestUpsertAgentSpecRejectsDuplicateSubagentName(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	spec := domain.AuthoredAgentSpec{
		Name:   "demo-agent",
		Prompt: domain.PromptSpec{System: "test"},
		Model:  domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		Subagents: []domain.SubagentSpec{
			{
				Name:         "helper",
				Description:  "first",
				SystemPrompt: "assist",
			},
			{
				Name:         " helper ",
				Description:  "second",
				SystemPrompt: "assist more",
			},
		},
		Status: domain.AuthoredStatusPublished,
	}
	err := reg.UpsertAgentSpec(ctx, spec)
	if !errors.Is(err, ErrInvalid) {
		t.Fatalf("expected invalid subagent error, got: %v", err)
	}
	if !strings.Contains(err.Error(), `duplicate subagent name "helper"`) {
		t.Fatalf("expected duplicate subagent details in error, got: %v", err)
	}
}

func TestUpsertAgentSpecRejectsInvalidStatus(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	spec := domain.AuthoredAgentSpec{
		Name:   "demo-agent",
		Prompt: domain.PromptSpec{System: "test"},
		Model:  domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		Status: domain.AuthoredStatus("broken"),
	}
	err := reg.UpsertAgentSpec(ctx, spec)
	if !errors.Is(err, ErrInvalid) {
		t.Fatalf("expected invalid status error, got: %v", err)
	}
	if !strings.Contains(err.Error(), `agent status "broken" is invalid`) {
		t.Fatalf("expected invalid status details in error, got: %v", err)
	}
}

func TestUpsertAgentSpecNormalizesAgentName(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	spec := domain.AuthoredAgentSpec{
		Name:   " demo-agent ",
		Prompt: domain.PromptSpec{System: "test"},
		Model:  domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		Status: domain.AuthoredStatusPublished,
	}
	if err := reg.UpsertAgentSpec(ctx, spec); err != nil {
		t.Fatalf("upsert agent spec: %v", err)
	}

	stored, err := reg.GetAgentSpec(ctx, "demo-agent")
	if err != nil {
		t.Fatalf("get normalized agent spec: %v", err)
	}
	if stored.Name != "demo-agent" {
		t.Fatalf("expected normalized agent name, got: %#v", stored.Name)
	}
	if _, err := reg.GetAgentSpec(ctx, " demo-agent "); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected raw agent name to remain absent, got: %v", err)
	}
}

func TestDeleteAgentSpecDeletesBoundDeployment(t *testing.T) {
	ctx := context.Background()
	reg := newTestRegistry(t)

	if err := reg.UpsertAgentSpec(ctx, domain.AuthoredAgentSpec{
		Name:   "demo-agent",
		Prompt: domain.PromptSpec{System: "test"},
		Model:  domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		Status: domain.AuthoredStatusPublished,
	}); err != nil {
		t.Fatalf("upsert agent spec: %v", err)
	}
	if err := reg.UpsertRuntimeTarget(ctx, domain.RuntimeTarget{
		Name:     "runtime-a",
		Kind:     domain.RuntimeTargetKindLocalGRPC,
		Endpoint: "127.0.0.1:50051",
	}); err != nil {
		t.Fatalf("upsert runtime target: %v", err)
	}
	if err := reg.UpsertDeployment(ctx, domain.Deployment{
		AgentName:     "demo-agent",
		TargetName:    "runtime-a",
		DesiredState:  domain.DesiredDeploymentStateCompiled,
		ObservedState: domain.ObservedRuntimeStateInstalled,
	}); err != nil {
		t.Fatalf("upsert deployment: %v", err)
	}

	if err := reg.DeleteAgentSpec(ctx, "demo-agent"); err != nil {
		t.Fatalf("delete agent spec: %v", err)
	}
	if _, err := reg.GetDeployment(ctx, "demo-agent"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected deployment to be deleted, got: %v", err)
	}
}

func newTestRegistry(t *testing.T) *SQLiteRegistry {
	t.Helper()

	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "registry.sqlite")
	sqliteStore, err := store.OpenSQLite(ctx, store.SQLiteConfig{Path: path})
	if err != nil {
		t.Fatalf("open sqlite store: %v", err)
	}
	t.Cleanup(func() {
		_ = sqliteStore.Close()
	})

	reg, err := NewSQLiteRegistry(sqliteStore.DB())
	if err != nil {
		t.Fatalf("new sqlite registry: %v", err)
	}
	return reg
}
