package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestBuildProtocArgsUseRepoLevelProtoAndControlOutput(t *testing.T) {
	cfg := generatorConfig{
		ProtoRoot:        filepath.Clean("D:/repo/proto"),
		ControlModuleDir: filepath.Clean("D:/repo/libs/control"),
		RuntimeProject:   filepath.Clean("D:/repo/libs/runtime/deepagents-runtime"),
		GoPluginPath:     filepath.Clean("C:/Users/test/go/bin/protoc-gen-go.exe"),
		GoGRPCPluginPath: filepath.Clean("C:/Users/test/go/bin/protoc-gen-go-grpc.exe"),
	}

	args := buildProtocArgs(cfg, filepath.Clean("D:/venv/grpc_tools/_proto"))

	if args[0] != "run" || args[1] != "--project" {
		t.Fatalf("unexpected uv args prefix: %#v", args[:2])
	}
	if args[2] != cfg.RuntimeProject {
		t.Fatalf("unexpected runtime project: %s", args[2])
	}
	if args[5] != "grpc_tools.protoc" {
		t.Fatalf("unexpected protoc launcher: %s", args[5])
	}
	if args[6] != "-I"+cfg.ProtoRoot {
		t.Fatalf("unexpected proto include: %s", args[6])
	}
	if args[7] != "-I"+filepath.Clean("D:/venv/grpc_tools/_proto") {
		t.Fatalf("unexpected grpc tools include: %s", args[7])
	}
	if args[10] != "--go_out=module=agentctl:"+cfg.ControlModuleDir {
		t.Fatalf("unexpected go_out: %s", args[10])
	}
	if args[11] != "--go-grpc_out=module=agentctl:"+cfg.ControlModuleDir {
		t.Fatalf("unexpected go_grpc_out: %s", args[11])
	}
	if args[12] != protoFileName {
		t.Fatalf("unexpected proto file name: %s", args[12])
	}
}

func TestFindRepoRootFromUsesProtoFileInsteadOfAnyProtoDirectory(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "proto"), 0o755); err != nil {
		t.Fatalf("mkdir proto root: %v", err)
	}
	if err := os.WriteFile(filepath.Join(root, "proto", protoFileName), []byte("syntax = \"proto3\";"), 0o644); err != nil {
		t.Fatalf("write runtime proto: %v", err)
	}
	nested := filepath.Join(root, "libs", "control", "pkg", "proto")
	if err := os.MkdirAll(nested, 0o755); err != nil {
		t.Fatalf("mkdir nested proto dir: %v", err)
	}

	got, err := findRepoRootFrom(nested)
	if err != nil {
		t.Fatalf("find repo root: %v", err)
	}
	if got != root {
		t.Fatalf("unexpected repo root: got=%s want=%s", got, root)
	}
}
