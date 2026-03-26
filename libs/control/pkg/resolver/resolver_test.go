package resolver

import (
	"agentctl/pkg/domain"
	"agentctl/pkg/registry"
	"agentctl/pkg/store"
	"context"
	"path/filepath"
	"testing"
)

func TestRegistryResolverAggregatesAgentInput(t *testing.T) {
	ctx := context.Background()
	reg := newResolverRegistry(t)

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
	if err := reg.UpsertAgentSpec(ctx, domain.AuthoredAgentSpec{
		Name:      "demo-agent",
		Prompt:    domain.PromptSpec{System: "You are helpful."},
		Model:     domain.ModelSpec{Provider: "openai", Model: "gpt-4o"},
		SkillRefs: []string{"research"},
		MCPRefs:   []string{"github"},
		Status:    domain.AuthoredStatusPublished,
	}); err != nil {
		t.Fatalf("upsert agent spec: %v", err)
	}

	resolver, err := NewRegistryResolver(reg)
	if err != nil {
		t.Fatalf("new resolver: %v", err)
	}

	resolved, err := resolver.ResolveAgent(ctx, "demo-agent")
	if err != nil {
		t.Fatalf("resolve agent: %v", err)
	}
	if resolved.Agent.Name != "demo-agent" {
		t.Fatalf("unexpected agent: %#v", resolved.Agent)
	}
	if len(resolved.Skills) != 1 || resolved.Skills[0].Name != "research" {
		t.Fatalf("unexpected skills: %#v", resolved.Skills)
	}
	if len(resolved.MCPConfigs) != 1 || resolved.MCPConfigs[0].Name != "github" {
		t.Fatalf("unexpected mcp configs: %#v", resolved.MCPConfigs)
	}
}

func newResolverRegistry(t *testing.T) *registry.SQLiteRegistry {
	t.Helper()

	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "resolver.sqlite")
	sqliteStore, err := store.OpenSQLite(ctx, store.SQLiteConfig{Path: path})
	if err != nil {
		t.Fatalf("open sqlite store: %v", err)
	}
	t.Cleanup(func() {
		_ = sqliteStore.Close()
	})

	reg, err := registry.NewSQLiteRegistry(sqliteStore.DB())
	if err != nil {
		t.Fatalf("new sqlite registry: %v", err)
	}
	return reg
}
