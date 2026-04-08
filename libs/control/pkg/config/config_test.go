package config

import "testing"

func TestDefaultConfigIsValid(t *testing.T) {
	cfg := Default()
	if err := cfg.Validate(); err != nil {
		t.Fatalf("default config should be valid: %v", err)
	}
}

func TestFromEnvOverridesDefaults(t *testing.T) {
	env := map[string]string{
		"CONTROL_LISTEN":                 ":9090",
		"CONTROL_STORAGE_PATH":           "control.sqlite",
		"CONTROL_DEFAULT_RUNTIME_TARGET": "runtime-a",
		"CONTROL_RUNTIME_ENDPOINT":       "127.0.0.1:60051",
		"CONTROL_TRANSPORT":              "grpc",
		"CONTROL_LOG_LEVEL":              "debug",
	}

	cfg := FromEnv(func(key string) string {
		return env[key]
	})

	if cfg.ListenAddress != ":9090" {
		t.Fatalf("unexpected listen address: %s", cfg.ListenAddress)
	}
	if cfg.StoragePath != "control.sqlite" {
		t.Fatalf("unexpected storage path: %s", cfg.StoragePath)
	}
	if cfg.DefaultRuntimeTarget != "runtime-a" {
		t.Fatalf("unexpected default runtime target: %s", cfg.DefaultRuntimeTarget)
	}
	if cfg.RuntimeEndpoint != "127.0.0.1:60051" {
		t.Fatalf("unexpected runtime endpoint: %s", cfg.RuntimeEndpoint)
	}
	if cfg.NorthboundTransport != "grpc" {
		t.Fatalf("unexpected transport: %s", cfg.NorthboundTransport)
	}
	if cfg.LogLevel != "debug" {
		t.Fatalf("unexpected log level: %s", cfg.LogLevel)
	}
}

func TestValidateRejectsMissingStoragePath(t *testing.T) {
	cfg := Default()
	cfg.StoragePath = ""

	if err := cfg.Validate(); err == nil {
		t.Fatal("expected validation error")
	}
}

func TestValidateRejectsMissingRuntimeEndpoint(t *testing.T) {
	cfg := Default()
	cfg.RuntimeEndpoint = ""

	if err := cfg.Validate(); err == nil {
		t.Fatal("expected validation error")
	}
}
