package packager

import (
	"agentctl/pkg/domain"
	"context"
	"testing"
)

func TestDefaultPackagerPackagesResolvedAgentInput(t *testing.T) {
	p := NewDefaultPackager()
	input := domain.ResolvedAgentInput{
		Agent: domain.AuthoredAgentSpec{
			Name:        "demo-agent",
			Version:     "1.2.3",
			Description: "demo agent",
			Tags:        []string{"assistant", "demo"},
			ModelRef:    "default-openai",
			Prompt:      domain.PromptSpec{System: "You are helpful."},
			SkillRefs:   []string{"research", "ops"},
			MCPRefs:     []string{"github", "docs"},
			SandboxRef:  "python-slim",
			Subagents: []domain.SubagentSpec{
				{
					Name:         "planner",
					Description:  "handles planning",
					SystemPrompt: "Plan first.",
				},
				{
					Name:         "coder",
					Description:  "handles code changes",
					SystemPrompt: "Write code.",
					Model: domain.ModelSpec{
						Provider: "openai",
						Model:    "gpt-5-mini",
					},
				},
			},
			InterruptOn: []string{"approval"},
		},
		ModelConfig: domain.ModelConfig{
			Name: "default-openai",
			Spec: domain.ModelSpec{
				Provider:    "openai",
				Model:       "gpt-5",
				BaseURL:     "https://api.example.com",
				APIKeyEnv:   "OPENAI_API_KEY",
				ExtraParams: map[string]string{"temperature": "0.2"},
			},
		},
		Skills: []domain.Skill{
			{
				Name:    "research",
				Content: "# Research",
				Files: []domain.SkillFile{
					{Path: "scripts/search.py", Content: "print('search')\n"},
				},
			},
			{
				Name:    "ops",
				Content: "# Ops",
				Files: []domain.SkillFile{
					{Path: "references/runbook.md", Content: "runbook"},
				},
			},
		},
		MCPConfigs: []domain.MCPConfig{
			{
				Name:      "github",
				Command:   "npx",
				Args:      []string{"@modelcontextprotocol/server-github"},
				Env:       map[string]string{"GITHUB_TOKEN": "env:GITHUB_TOKEN"},
				Transport: "stdio",
			},
			{
				Name:      "docs",
				Command:   "https://docs.example.com/sse",
				Transport: "sse",
			},
		},
		SandboxConfig: &domain.SandboxConfig{
			Name: "python-slim",
			Spec: domain.SandboxSpec{
				Docker: &domain.DockerSandboxSpec{
					Image: domain.ImageReference{Reference: "python:3.12"},
					Resources: domain.DockerResourceSpec{
						CPU: "2",
					},
				},
				SetupCommands: []string{"echo ready"},
			},
		},
		Target: domain.RuntimeTarget{
			Name:     "runtime-a",
			Endpoint: "127.0.0.1:50051",
		},
	}

	got, err := p.Package(context.Background(), input)
	if err != nil {
		t.Fatalf("package: %v", err)
	}

	if got.Name != "demo-agent" || got.Version != "1.2.3" {
		t.Fatalf("unexpected metadata: %#v", got)
	}
	if got.Model.Provider != "openai" || got.Model.Model != "gpt-5" {
		t.Fatalf("unexpected model: %#v", got.Model)
	}
	if got.Prompt.System != "You are helpful." {
		t.Fatalf("unexpected prompt: %#v", got.Prompt)
	}
	if len(got.Skills) != 2 || got.Skills[0].Name != "research" || got.Skills[1].Name != "ops" {
		t.Fatalf("unexpected skills: %#v", got.Skills)
	}
	if len(got.MCPServers) != 2 || got.MCPServers[0].Name != "github" || got.MCPServers[1].Name != "docs" {
		t.Fatalf("unexpected mcp servers: %#v", got.MCPServers)
	}
	if len(got.Subagents) != 2 || got.Subagents[1].Model.Model != "gpt-5-mini" {
		t.Fatalf("unexpected subagents: %#v", got.Subagents)
	}
	if got.Sandbox.Docker == nil || got.Sandbox.Docker.Resources.CPU != "2" || len(got.Sandbox.SetupCommands) != 1 {
		t.Fatalf("unexpected sandbox: %#v", got.Sandbox)
	}
	if len(got.InterruptOn) != 1 || got.InterruptOn[0] != "approval" {
		t.Fatalf("unexpected interrupt_on: %#v", got.InterruptOn)
	}

	input.Agent.Tags[0] = "changed"
	input.ModelConfig.Spec.ExtraParams["temperature"] = "0.9"
	input.Skills[0].Files[0].Content = "mutated"
	input.MCPConfigs[0].Env["GITHUB_TOKEN"] = "mutated"
	input.SandboxConfig.Spec.Docker.Resources.CPU = "4"

	if got.Tags[0] != "assistant" {
		t.Fatalf("expected tags to be cloned, got: %#v", got.Tags)
	}
	if got.Model.ExtraParams["temperature"] != "0.2" {
		t.Fatalf("expected model extra params to be cloned, got: %#v", got.Model)
	}
	if got.Skills[0].Files[0].Content != "print('search')\n" {
		t.Fatalf("expected skill files to be cloned, got: %#v", got.Skills[0].Files)
	}
	if got.MCPServers[0].Env["GITHUB_TOKEN"] != "env:GITHUB_TOKEN" {
		t.Fatalf("expected mcp env to be cloned, got: %#v", got.MCPServers[0].Env)
	}
	if got.Sandbox.Docker == nil || got.Sandbox.Docker.Resources.CPU != "2" {
		t.Fatalf("expected sandbox spec to be cloned, got: %#v", got.Sandbox)
	}
}

func TestDefaultPackagerOrdersResolvedResourcesByRefs(t *testing.T) {
	p := NewDefaultPackager()
	input := domain.ResolvedAgentInput{
		Agent: domain.AuthoredAgentSpec{
			Name:      "demo-agent",
			ModelRef:  "default-openai",
			SkillRefs: []string{"ops", "research"},
			MCPRefs:   []string{"docs", "github"},
		},
		ModelConfig: domain.ModelConfig{Name: "default-openai", Spec: domain.ModelSpec{Provider: "openai", Model: "gpt-5"}},
		Skills: []domain.Skill{
			{Name: "research", Content: "# Research"},
			{Name: "ops", Content: "# Ops"},
		},
		MCPConfigs: []domain.MCPConfig{
			{Name: "github", Command: "npx", Transport: "stdio"},
			{Name: "docs", Command: "https://docs.example.com/sse", Transport: "sse"},
		},
	}

	got, err := p.Package(context.Background(), input)
	if err != nil {
		t.Fatalf("package: %v", err)
	}

	if got.Skills[0].Name != "ops" || got.Skills[1].Name != "research" {
		t.Fatalf("expected skills to follow refs order, got: %#v", got.Skills)
	}
	if got.MCPServers[0].Name != "docs" || got.MCPServers[1].Name != "github" {
		t.Fatalf("expected mcp servers to follow refs order, got: %#v", got.MCPServers)
	}
}

func TestDefaultPackagerRejectsUnresolvedSkillRef(t *testing.T) {
	p := NewDefaultPackager()
	input := domain.ResolvedAgentInput{
		Agent: domain.AuthoredAgentSpec{
			Name:      "demo-agent",
			ModelRef:  "default-openai",
			SkillRefs: []string{"research"},
		},
		ModelConfig: domain.ModelConfig{Name: "default-openai", Spec: domain.ModelSpec{Provider: "openai", Model: "gpt-5"}},
	}

	if _, err := p.Package(context.Background(), input); err == nil {
		t.Fatal("expected unresolved skill ref error")
	}
}

func TestDefaultPackagerRejectsEscapingSkillFilePath(t *testing.T) {
	p := NewDefaultPackager()
	input := domain.ResolvedAgentInput{
		Agent: domain.AuthoredAgentSpec{
			Name:      "demo-agent",
			ModelRef:  "default-openai",
			SkillRefs: []string{"research"},
		},
		ModelConfig: domain.ModelConfig{Name: "default-openai", Spec: domain.ModelSpec{Provider: "openai", Model: "gpt-5"}},
		Skills: []domain.Skill{
			{
				Name:    "research",
				Content: "# Research",
				Files: []domain.SkillFile{
					{Path: "../escape.sh", Content: "echo nope"},
				},
			},
		},
	}

	if _, err := p.Package(context.Background(), input); err == nil {
		t.Fatal("expected invalid skill file path error")
	}
}
