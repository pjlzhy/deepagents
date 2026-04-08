package config

import (
	"errors"
	"strings"
)

const (
	defaultListenAddress       = ":8080"
	defaultStoragePath         = ".deepagents-control/control.db"
	defaultRuntimeTarget       = "local-runtime"
	defaultRuntimeEndpoint     = "127.0.0.1:50051"
	defaultNorthboundTransport = "http"
	defaultLogLevel            = "info"
)

// Config 是 control layer 进程级配置。
type Config struct {
	ListenAddress        string
	StoragePath          string
	DefaultRuntimeTarget string
	RuntimeEndpoint      string
	NorthboundTransport  string
	LogLevel             string
	SecretKey            string // AES-256 key (hex or raw) for encrypting secrets at rest
}

// Default 返回默认配置。
func Default() Config {
	return Config{
		ListenAddress:        defaultListenAddress,
		StoragePath:          defaultStoragePath,
		DefaultRuntimeTarget: defaultRuntimeTarget,
		RuntimeEndpoint:      defaultRuntimeEndpoint,
		NorthboundTransport:  defaultNorthboundTransport,
		LogLevel:             defaultLogLevel,
	}
}

// FromEnv 从环境变量读取配置，未设置时回退到默认值。
func FromEnv(getenv func(string) string) Config {
	cfg := Default()
	cfg.ListenAddress = firstNonEmpty(getenv("CONTROL_LISTEN"), cfg.ListenAddress)
	cfg.StoragePath = firstNonEmpty(getenv("CONTROL_STORAGE_PATH"), cfg.StoragePath)
	cfg.DefaultRuntimeTarget = firstNonEmpty(
		getenv("CONTROL_DEFAULT_RUNTIME_TARGET"),
		cfg.DefaultRuntimeTarget,
	)
	cfg.RuntimeEndpoint = firstNonEmpty(
		getenv("CONTROL_RUNTIME_ENDPOINT"),
		cfg.RuntimeEndpoint,
	)
	cfg.NorthboundTransport = firstNonEmpty(
		getenv("CONTROL_TRANSPORT"),
		cfg.NorthboundTransport,
	)
	cfg.LogLevel = firstNonEmpty(getenv("CONTROL_LOG_LEVEL"), cfg.LogLevel)
	cfg.SecretKey = getenv("CONTROL_SECRET_KEY")
	return cfg
}

// Validate 校验关键配置是否可用于启动进程。
func (c Config) Validate() error {
	if strings.TrimSpace(c.ListenAddress) == "" {
		return errors.New("listen address must not be empty")
	}
	if strings.TrimSpace(c.StoragePath) == "" {
		return errors.New("storage path must not be empty")
	}
	if strings.TrimSpace(c.DefaultRuntimeTarget) == "" {
		return errors.New("default runtime target must not be empty")
	}
	if strings.TrimSpace(c.RuntimeEndpoint) == "" {
		return errors.New("runtime endpoint must not be empty")
	}
	if strings.TrimSpace(c.NorthboundTransport) == "" {
		return errors.New("northbound transport must not be empty")
	}
	return nil
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}
