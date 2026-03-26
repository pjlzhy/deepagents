package domain

import "time"

// ResourceKind identifies one control-plane resource kind.
type ResourceKind string

const (
	ResourceKindSkill         ResourceKind = "skill"
	ResourceKindMCPConfig     ResourceKind = "mcp_config"
	ResourceKindAgentSpec     ResourceKind = "agent_spec"
	ResourceKindDeployment    ResourceKind = "deployment"
	ResourceKindRuntimeTarget ResourceKind = "runtime_target"
)

// SkillFile describes one extra file in a skill directory.
type SkillFile struct {
	Path    string
	Content string
}

// Skill is the authoritative control-plane snapshot of one skill.
type Skill struct {
	Name        string
	Description string
	Tags        []string
	Content     string
	Files       []SkillFile
	Status      AuthoredStatus
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// MCPConfig describes one reusable MCP server configuration.
type MCPConfig struct {
	Name        string
	Command     string
	Args        []string
	Env         map[string]string
	Transport   string
	Description string
	Status      AuthoredStatus
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// PromptSpec describes one authored prompt configuration.
type PromptSpec struct {
	System string
}

// ModelSpec describes one authored model configuration.
type ModelSpec struct {
	Provider    string
	Model       string
	BaseURL     string
	APIKeyEnv   string
	ExtraParams map[string]string
}

// SubagentSpec describes one authored subagent definition.
type SubagentSpec struct {
	Name         string
	Description  string
	SystemPrompt string
	Model        ModelSpec
}

// SandboxSpec describes one authored sandbox configuration.
type SandboxSpec struct {
	Image     string
	Resources map[string]string
	Init      []string
}

// AuthoredAgentSpec is the authoritative control-plane agent definition.
type AuthoredAgentSpec struct {
	Name        string
	Version     string
	Description string
	Tags        []string
	Model       ModelSpec
	Prompt      PromptSpec
	SkillRefs   []string
	MCPRefs     []string
	Subagents   []SubagentSpec
	Sandbox     SandboxSpec
	InterruptOn []string
	Status      AuthoredStatus
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// RuntimeAgentSpec is the packaged runtime-ready agent specification.
type RuntimeAgentSpec struct {
	Name        string
	Version     string
	Description string
	Tags        []string
	Model       ModelSpec
	Prompt      PromptSpec
	Skills      []Skill
	MCPServers  []MCPConfig
	Subagents   []SubagentSpec
	Sandbox     SandboxSpec
	InterruptOn []string
}
