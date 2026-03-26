package main

import (
	"agentctl/pkg/config"
	"agentctl/pkg/domain"
	"agentctl/pkg/registry"
	"agentctl/pkg/runtimeclient"
	"agentctl/pkg/store"
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

type stubBootstrapRuntimeClient struct {
	closed bool
}

func (*stubBootstrapRuntimeClient) SyncAgentSpec(
	context.Context,
	domain.RuntimeAgentSpec,
) (runtimeclient.SyncResponse, error) {
	return runtimeclient.SyncResponse{OK: true}, nil
}

func (*stubBootstrapRuntimeClient) Assemble(
	context.Context,
	string,
) (runtimeclient.AssembleResponse, error) {
	return runtimeclient.AssembleResponse{OK: true, Status: "compiled"}, nil
}

func (*stubBootstrapRuntimeClient) RemoveAgent(
	context.Context,
	string,
) (runtimeclient.SyncResponse, error) {
	return runtimeclient.SyncResponse{OK: true}, nil
}

func (*stubBootstrapRuntimeClient) Health(context.Context) (runtimeclient.HealthResponse, error) {
	return runtimeclient.HealthResponse{Ready: true, Status: "ok"}, nil
}

func (*stubBootstrapRuntimeClient) OpenRun(context.Context, domain.RunRequest) (runtimeclient.RunStream, error) {
	return nil, errors.New("not implemented in bootstrap test")
}

func (*stubBootstrapRuntimeClient) ListSessions(
	context.Context,
	string,
	int32,
	string,
) ([]domain.SessionSummary, string, error) {
	return nil, "", nil
}

func (*stubBootstrapRuntimeClient) GetSession(context.Context, string) (domain.SessionSummary, error) {
	return domain.SessionSummary{}, nil
}

func (*stubBootstrapRuntimeClient) GetSessionMessagePage(
	context.Context,
	domain.SessionMessageQuery,
) (domain.SessionMessagePage, error) {
	return domain.SessionMessagePage{}, nil
}

func (*stubBootstrapRuntimeClient) GetSessionMessages(
	context.Context,
	string,
	domain.SessionHistoryMode,
	int32,
	string,
) ([]domain.SessionMessage, string, error) {
	return nil, "", nil
}

func (*stubBootstrapRuntimeClient) GetLatestSession(
	context.Context,
	string,
) (domain.SessionSummary, error) {
	return domain.SessionSummary{}, nil
}

func (*stubBootstrapRuntimeClient) DeleteSession(context.Context, string) error {
	return nil
}

func (s *stubBootstrapRuntimeClient) Close() error {
	s.closed = true
	return nil
}

func TestNewAppBuildsHTTPServerAndSeedsDefaultRuntimeTarget(t *testing.T) {
	runtimeClient := &stubBootstrapRuntimeClient{}
	originalFactory := newRuntimeClient
	newRuntimeClient = func(context.Context, string) (runtimeControlClient, error) {
		return runtimeClient, nil
	}
	t.Cleanup(func() {
		newRuntimeClient = originalFactory
	})

	cfg := config.Default()
	cfg.StoragePath = filepath.Join(t.TempDir(), "control.db")
	cfg.ListenAddress = "127.0.0.1:0"
	cfg.RuntimeEndpoint = "127.0.0.1:60051"

	app, err := newApp(context.Background(), cfg)
	if err != nil {
		t.Fatalf("newApp: %v", err)
	}

	server := httptest.NewServer(app.server.Handler)
	defer server.Close()

	response, err := http.Post(
		server.URL+"/api/v1/run_sessions/missing/cancel",
		"application/json",
		strings.NewReader(`{"reason":"user canceled"}`),
	)
	if err != nil {
		t.Fatalf("POST cancel request: %v", err)
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusNotFound {
		t.Fatalf("unexpected status code: %d", response.StatusCode)
	}

	if err := app.cleanup(); err != nil {
		t.Fatalf("cleanup: %v", err)
	}
	if !runtimeClient.closed {
		t.Fatal("expected runtime client to be closed")
	}

	sqliteStore, err := store.OpenSQLite(context.Background(), store.SQLiteConfig{Path: cfg.StoragePath})
	if err != nil {
		t.Fatalf("reopen sqlite store: %v", err)
	}
	defer sqliteStore.Close()

	reg, err := registry.NewSQLiteRegistry(sqliteStore.DB())
	if err != nil {
		t.Fatalf("NewSQLiteRegistry: %v", err)
	}
	target, err := reg.GetRuntimeTarget(context.Background(), cfg.DefaultRuntimeTarget)
	if err != nil {
		t.Fatalf("GetRuntimeTarget: %v", err)
	}
	if target.Name != cfg.DefaultRuntimeTarget ||
		target.Endpoint != cfg.RuntimeEndpoint ||
		target.Kind != domain.RuntimeTargetKindLocalGRPC {
		t.Fatalf("unexpected runtime target: %#v", target)
	}
}

func TestNewAppRejectsUnsupportedTransport(t *testing.T) {
	cfg := config.Default()
	cfg.StoragePath = filepath.Join(t.TempDir(), "control.db")
	cfg.NorthboundTransport = "grpc"

	if _, err := newApp(context.Background(), cfg); err == nil {
		t.Fatal("expected unsupported transport error")
	}
}
