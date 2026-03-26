package router

import (
	"agentctl/pkg/domain"
	"agentctl/pkg/registry"
	"agentctl/pkg/store"
	"context"
	"path/filepath"
	"testing"
)

func TestNewRegistryRouterRejectsNilRegistry(t *testing.T) {
	if _, err := NewRegistryRouter(nil); err == nil {
		t.Fatal("expected constructor to reject nil registry")
	}
}

func TestRegistryRouterResolvesTargetFromDeployment(t *testing.T) {
	ctx := context.Background()
	reg := newRouterRegistry(t)

	if err := reg.UpsertAgentSpec(ctx, domain.AuthoredAgentSpec{
		Name:   "demo-agent",
		Model:  domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
		Prompt: domain.PromptSpec{System: "You are helpful."},
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

	router, err := NewRegistryRouter(reg)
	if err != nil {
		t.Fatalf("new router: %v", err)
	}

	target, err := router.ResolveTarget(ctx, "demo-agent")
	if err != nil {
		t.Fatalf("resolve target: %v", err)
	}
	if target.Name != "runtime-a" || target.Endpoint != "127.0.0.1:50051" {
		t.Fatalf("unexpected target: %#v", target)
	}
}

func newRouterRegistry(t *testing.T) *registry.SQLiteRegistry {
	t.Helper()

	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "router.sqlite")
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
