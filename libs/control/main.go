package main

import (
	"agentctl/pkg/config"
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	cfg := config.FromEnv(os.Getenv)
	app, err := newApp(ctx, cfg)
	if err != nil {
		log.Fatalf("initialize control app: %v", err)
	}
	defer func() {
		if err := app.cleanup(); err != nil {
			log.Printf("control app cleanup error: %v", err)
		}
	}()

	go func() {
		<-ctx.Done()

		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		if err := app.server.Shutdown(shutdownCtx); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Printf("control server shutdown error: %v", err)
		}
	}()

	log.Printf(
		"deepagents-control listening transport=%s listen=%s storage=%s runtime_target=%s runtime_endpoint=%s",
		cfg.NorthboundTransport,
		cfg.ListenAddress,
		cfg.StoragePath,
		cfg.DefaultRuntimeTarget,
		cfg.RuntimeEndpoint,
	)

	if err := app.server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatalf("serve control api: %v", err)
	}
}
