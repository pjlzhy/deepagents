package main

import (
	"agentctl/pkg/api"
	"agentctl/pkg/config"
	"agentctl/pkg/domain"
	"agentctl/pkg/orchestrator"
	"agentctl/pkg/packager"
	"agentctl/pkg/registry"
	resolverpkg "agentctl/pkg/resolver"
	"agentctl/pkg/runtimeclient"
	"agentctl/pkg/store"
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
)

type runtimeControlClient interface {
	runtimeclient.ResourceSyncClient
	runtimeclient.AgentExecutorClient
	runtimeclient.SessionQueryClient
	Close() error
}

type controlApp struct {
	server  *http.Server
	cleanup func() error
}

var newRuntimeClient = func(ctx context.Context, endpoint string) (runtimeControlClient, error) {
	return runtimeclient.NewGRPCClient(ctx, endpoint)
}

func newApp(ctx context.Context, cfg config.Config) (*controlApp, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("validate config: %w", err)
	}

	transport := strings.ToLower(strings.TrimSpace(cfg.NorthboundTransport))
	if transport != "http" {
		return nil, fmt.Errorf("unsupported northbound transport %q", cfg.NorthboundTransport)
	}

	sqliteStore, err := store.OpenSQLite(ctx, store.SQLiteConfig{Path: cfg.StoragePath})
	if err != nil {
		return nil, fmt.Errorf("open sqlite store: %w", err)
	}

	closeWithStore := func(runErr error) (*controlApp, error) {
		if closeErr := sqliteStore.Close(); closeErr != nil {
			runErr = errors.Join(runErr, fmt.Errorf("close sqlite store: %w", closeErr))
		}
		return nil, runErr
	}

	reg, err := registry.NewSQLiteRegistry(sqliteStore.DB())
	if err != nil {
		return closeWithStore(fmt.Errorf("create registry: %w", err))
	}

	if err := ensureDefaultRuntimeTarget(ctx, reg, cfg); err != nil {
		return closeWithStore(err)
	}

	resolver, err := resolverpkg.NewRegistryResolver(reg)
	if err != nil {
		return closeWithStore(fmt.Errorf("create resolver: %w", err))
	}

	runtimeClient, err := newRuntimeClient(ctx, cfg.RuntimeEndpoint)
	if err != nil {
		return closeWithStore(fmt.Errorf("create runtime client: %w", err))
	}

	closeAll := func() error {
		return errors.Join(
			runtimeClient.Close(),
			sqliteStore.Close(),
		)
	}

	service, err := orchestrator.NewService(orchestrator.Dependencies{
		Registry:     reg,
		Resolver:     resolver,
		Packager:     packager.NewDefaultPackager(),
		ResourceSync: runtimeClient,
		Executor:     runtimeClient,
		Sessions:     runtimeClient,
	})
	if err != nil {
		_ = closeAll()
		return nil, fmt.Errorf("create orchestrator service: %w", err)
	}

	handler, err := api.NewHTTPHandler(service, nil)
	if err != nil {
		_ = closeAll()
		return nil, fmt.Errorf("create http handler: %w", err)
	}

	return &controlApp{
		server: &http.Server{
			Addr:    cfg.ListenAddress,
			Handler: handler,
		},
		cleanup: closeAll,
	}, nil
}

func ensureDefaultRuntimeTarget(
	ctx context.Context,
	reg registry.Registry,
	cfg config.Config,
) error {
	target := defaultRuntimeTargetFromConfig(cfg)
	if err := reg.UpsertRuntimeTarget(ctx, target); err != nil {
		return fmt.Errorf("upsert default runtime target %q: %w", target.Name, err)
	}
	return nil
}

func defaultRuntimeTargetFromConfig(cfg config.Config) domain.RuntimeTarget {
	return domain.RuntimeTarget{
		Name:        strings.TrimSpace(cfg.DefaultRuntimeTarget),
		Kind:        domain.RuntimeTargetKindLocalGRPC,
		Endpoint:    strings.TrimSpace(cfg.RuntimeEndpoint),
		Description: "bootstrap default runtime target",
	}
}
