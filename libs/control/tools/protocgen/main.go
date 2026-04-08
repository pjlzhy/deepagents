package main

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

const (
	modulePath             = "agentctl"
	protoFileName          = "runtime.proto"
	protocGenGoVersion     = "v1.36.11"
	protocGenGoGRPCVersion = "v1.5.1"
	runtimeProjectRelPath  = "libs/runtime/agents-runtime"
	controlModuleRelPath   = "libs/control"
)

type generatorConfig struct {
	RepoRoot         string
	ProtoRoot        string
	ControlModuleDir string
	RuntimeProject   string
	GoPluginPath     string
	GoGRPCPluginPath string
}

func main() {
	cfg, err := loadGeneratorConfig()
	if err != nil {
		fatal(err)
	}

	grpcToolsInclude, err := detectGrpcToolsInclude(cfg.RuntimeProject)
	if err != nil {
		fatal(err)
	}

	args := buildProtocArgs(cfg, grpcToolsInclude)
	cmd := exec.Command("uv", args...)
	cmd.Dir = cfg.RepoRoot
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		fatal(fmt.Errorf("generate Go protobuf stubs: %w", err))
	}
}

func loadGeneratorConfig() (generatorConfig, error) {
	repoRoot, err := resolveRepoRoot()
	if err != nil {
		return generatorConfig{}, err
	}

	goPluginPath, err := resolvePluginBinary("protoc-gen-go")
	if err != nil {
		return generatorConfig{}, err
	}
	goGRPCPluginPath, err := resolvePluginBinary("protoc-gen-go-grpc")
	if err != nil {
		return generatorConfig{}, err
	}

	return generatorConfig{
		RepoRoot:         repoRoot,
		ProtoRoot:        filepath.Join(repoRoot, "proto"),
		ControlModuleDir: filepath.Join(repoRoot, controlModuleRelPath),
		RuntimeProject:   filepath.Join(repoRoot, runtimeProjectRelPath),
		GoPluginPath:     goPluginPath,
		GoGRPCPluginPath: goGRPCPluginPath,
	}, nil
}

func resolveRepoRoot() (string, error) {
	start, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("get working directory: %w", err)
	}
	return findRepoRootFrom(start)
}

func findRepoRootFrom(start string) (string, error) {
	dir := start
	for {
		if fileExists(filepath.Join(dir, ".git")) || fileExists(filepath.Join(dir, "proto", protoFileName)) {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", errors.New("could not locate repository root")
		}
		dir = parent
	}
}

func resolvePluginBinary(name string) (string, error) {
	candidates := make([]string, 0, 2)
	if gobin, err := goEnv("GOBIN"); err == nil && strings.TrimSpace(gobin) != "" {
		candidates = append(candidates, filepath.Join(gobin, platformBinary(name)))
	}
	if gopath, err := goEnv("GOPATH"); err == nil && strings.TrimSpace(gopath) != "" {
		candidates = append(candidates, filepath.Join(gopath, "bin", platformBinary(name)))
	}

	for _, candidate := range candidates {
		if fileExists(candidate) {
			return candidate, nil
		}
	}

	return "", fmt.Errorf(
		"missing %s; install it with `%s`",
		name,
		pluginInstallCommand(name),
	)
}

func detectGrpcToolsInclude(runtimeProject string) (string, error) {
	cmd := exec.Command(
		"uv",
		"run",
		"--project",
		runtimeProject,
		"python",
		"-c",
		"import grpc_tools, pathlib; print(pathlib.Path(grpc_tools.__file__).resolve().parent / '_proto')",
	)
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		return "", fmt.Errorf("detect grpc_tools include dir: %s", msg)
	}

	includeDir := strings.TrimSpace(stdout.String())
	if includeDir == "" {
		return "", errors.New("detect grpc_tools include dir: empty output")
	}
	return includeDir, nil
}

func buildProtocArgs(cfg generatorConfig, grpcToolsInclude string) []string {
	return []string{
		"run",
		"--project",
		cfg.RuntimeProject,
		"python",
		"-m",
		"grpc_tools.protoc",
		fmt.Sprintf("-I%s", cfg.ProtoRoot),
		fmt.Sprintf("-I%s", grpcToolsInclude),
		fmt.Sprintf("--plugin=protoc-gen-go=%s", cfg.GoPluginPath),
		fmt.Sprintf("--plugin=protoc-gen-go-grpc=%s", cfg.GoGRPCPluginPath),
		fmt.Sprintf("--go_out=module=%s:%s", modulePath, cfg.ControlModuleDir),
		fmt.Sprintf("--go-grpc_out=module=%s:%s", modulePath, cfg.ControlModuleDir),
		protoFileName,
	}
}

func goEnv(key string) (string, error) {
	cmd := exec.Command("go", "env", key)
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		return "", fmt.Errorf("go env %s: %s", key, msg)
	}
	return strings.TrimSpace(stdout.String()), nil
}

func pluginInstallCommand(name string) string {
	switch name {
	case "protoc-gen-go":
		return "go install google.golang.org/protobuf/cmd/protoc-gen-go@" + protocGenGoVersion
	case "protoc-gen-go-grpc":
		return "go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@" + protocGenGoGRPCVersion
	default:
		return "go install " + name
	}
}

func platformBinary(name string) string {
	if runtime.GOOS == "windows" {
		return name + ".exe"
	}
	return name
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
