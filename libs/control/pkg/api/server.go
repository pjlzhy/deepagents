package api

import (
	"context"
	"errors"

	"agentctl/pkg/domain"
	"agentctl/pkg/runtimeclient"
)

// AgentService 定义 northbound API 依赖的 orchestrator 能力面。
type AgentService interface {
	EnsureRunnable(ctx context.Context, agentName string) error
	RunAgent(ctx context.Context, req domain.RunRequest) (runtimeclient.RunStream, error)
	Health(ctx context.Context) (runtimeclient.HealthResponse, error)
	ListSessions(ctx context.Context, agentName string, pageSize int32, pageToken string) ([]domain.SessionSummary, string, error)
	GetSession(ctx context.Context, locator domain.SessionLocator) (domain.SessionSummary, error)
	GetSessionMessagePage(ctx context.Context, query domain.SessionMessageQuery) (domain.SessionMessagePage, error)
	GetSessionMessages(ctx context.Context, query domain.SessionMessageQuery) ([]domain.SessionMessage, string, error)
	GetLatestSession(ctx context.Context, agentName string) (domain.SessionSummary, error)
	DeleteSession(ctx context.Context, locator domain.SessionLocator) error
	UpsertModelConfig(ctx context.Context, config domain.ModelConfig) (domain.ModelConfig, error)
	GetModelConfig(ctx context.Context, name string) (domain.ModelConfig, error)
	ListModelConfigs(ctx context.Context) ([]domain.ModelConfig, error)
	ListModelConfigsPage(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.ModelConfig], error)
	DeleteModelConfig(ctx context.Context, name string) error
	UpsertSkill(ctx context.Context, skill domain.Skill) (domain.Skill, error)
	GetSkill(ctx context.Context, name string) (domain.Skill, error)
	ListSkills(ctx context.Context) ([]domain.Skill, error)
	ListSkillsPage(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.Skill], error)
	DeleteSkill(ctx context.Context, name string) error
	UpsertMCPConfig(ctx context.Context, config domain.MCPConfig) (domain.MCPConfig, error)
	GetMCPConfig(ctx context.Context, name string) (domain.MCPConfig, error)
	ListMCPConfigs(ctx context.Context) ([]domain.MCPConfig, error)
	ListMCPConfigsPage(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.MCPConfig], error)
	DeleteMCPConfig(ctx context.Context, name string) error
	UpsertSandboxConfig(ctx context.Context, config domain.SandboxConfig) (domain.SandboxConfig, error)
	GetSandboxConfig(ctx context.Context, name string) (domain.SandboxConfig, error)
	ListSandboxConfigs(ctx context.Context) ([]domain.SandboxConfig, error)
	ListSandboxConfigsPage(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.SandboxConfig], error)
	DeleteSandboxConfig(ctx context.Context, name string) error
	UpsertAgentSpec(ctx context.Context, spec domain.AuthoredAgentSpec) (domain.AuthoredAgentSpec, error)
	GetAgentSpec(ctx context.Context, name string) (domain.AuthoredAgentSpec, error)
	ListAgentSpecs(ctx context.Context) ([]domain.AuthoredAgentSpec, error)
	ListAgentSpecsPage(ctx context.Context, query domain.PageQuery) (domain.ResourcePage[domain.AuthoredAgentSpec], error)
	DeleteAgentSpec(ctx context.Context, name string) error
}

// Server 是 northbound API 的最小骨架。
type Server struct {
	service AgentService
}

// NewServer 创建一个新的 northbound API server 骨架。
func NewServer(service AgentService) (*Server, error) {
	if service == nil {
		return nil, errors.New("api service must not be nil")
	}
	return &Server{service: service}, nil
}

// EnsureRunnable forwards the runnable-setup request to the backing service.
func (s *Server) EnsureRunnable(ctx context.Context, agentName string) error {
	return s.service.EnsureRunnable(ctx, agentName)
}

// RunAgent forwards one run request to the backing service.
func (s *Server) RunAgent(
	ctx context.Context,
	req domain.RunRequest,
) (runtimeclient.RunStream, error) {
	return s.service.RunAgent(ctx, req)
}

// Health forwards the runtime health query to the backing service.
func (s *Server) Health(ctx context.Context) (runtimeclient.HealthResponse, error) {
	return s.service.Health(ctx)
}

// ListSessions forwards the session listing query to the backing service.
func (s *Server) ListSessions(
	ctx context.Context,
	agentName string,
	pageSize int32,
	pageToken string,
) ([]domain.SessionSummary, string, error) {
	return s.service.ListSessions(ctx, agentName, pageSize, pageToken)
}

// GetSession forwards one agent-scoped session lookup to the backing service.
func (s *Server) GetSession(ctx context.Context, locator domain.SessionLocator) (domain.SessionSummary, error) {
	return s.service.GetSession(ctx, locator)
}

// GetSessionMessagePage forwards one paged session-history query to the backing service.
func (s *Server) GetSessionMessagePage(
	ctx context.Context,
	query domain.SessionMessageQuery,
) (domain.SessionMessagePage, error) {
	return s.service.GetSessionMessagePage(ctx, query)
}

// GetSessionMessages forwards the agent-scoped session-message convenience query.
func (s *Server) GetSessionMessages(
	ctx context.Context,
	query domain.SessionMessageQuery,
) ([]domain.SessionMessage, string, error) {
	return s.service.GetSessionMessages(ctx, query)
}

// GetLatestSession forwards the latest-session lookup to the backing service.
func (s *Server) GetLatestSession(ctx context.Context, agentName string) (domain.SessionSummary, error) {
	return s.service.GetLatestSession(ctx, agentName)
}

// DeleteSession forwards one runtime-local agent-scoped session delete request.
func (s *Server) DeleteSession(ctx context.Context, locator domain.SessionLocator) error {
	return s.service.DeleteSession(ctx, locator)
}

// UpsertModelConfig forwards one model config upsert request.
func (s *Server) UpsertModelConfig(
	ctx context.Context,
	config domain.ModelConfig,
) (domain.ModelConfig, error) {
	return s.service.UpsertModelConfig(ctx, config)
}

// GetModelConfig forwards one model config lookup.
func (s *Server) GetModelConfig(ctx context.Context, name string) (domain.ModelConfig, error) {
	return s.service.GetModelConfig(ctx, name)
}

// ListModelConfigs forwards the model config list query.
func (s *Server) ListModelConfigs(ctx context.Context) ([]domain.ModelConfig, error) {
	return s.service.ListModelConfigs(ctx)
}

// ListModelConfigsPage forwards the model config page query.
func (s *Server) ListModelConfigsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.ModelConfig], error) {
	return s.service.ListModelConfigsPage(ctx, query)
}

// DeleteModelConfig forwards one model config delete request.
func (s *Server) DeleteModelConfig(ctx context.Context, name string) error {
	return s.service.DeleteModelConfig(ctx, name)
}

// UpsertSkill forwards one skill upsert request.
func (s *Server) UpsertSkill(ctx context.Context, skill domain.Skill) (domain.Skill, error) {
	return s.service.UpsertSkill(ctx, skill)
}

// GetSkill forwards one skill lookup.
func (s *Server) GetSkill(ctx context.Context, name string) (domain.Skill, error) {
	return s.service.GetSkill(ctx, name)
}

// ListSkills forwards the skill list query.
func (s *Server) ListSkills(ctx context.Context) ([]domain.Skill, error) {
	return s.service.ListSkills(ctx)
}

// ListSkillsPage forwards the skill page query.
func (s *Server) ListSkillsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.Skill], error) {
	return s.service.ListSkillsPage(ctx, query)
}

// DeleteSkill forwards one skill delete request.
func (s *Server) DeleteSkill(ctx context.Context, name string) error {
	return s.service.DeleteSkill(ctx, name)
}

// UpsertMCPConfig forwards one MCP config upsert request.
func (s *Server) UpsertMCPConfig(ctx context.Context, config domain.MCPConfig) (domain.MCPConfig, error) {
	return s.service.UpsertMCPConfig(ctx, config)
}

// GetMCPConfig forwards one MCP config lookup.
func (s *Server) GetMCPConfig(ctx context.Context, name string) (domain.MCPConfig, error) {
	return s.service.GetMCPConfig(ctx, name)
}

// ListMCPConfigs forwards the MCP config list query.
func (s *Server) ListMCPConfigs(ctx context.Context) ([]domain.MCPConfig, error) {
	return s.service.ListMCPConfigs(ctx)
}

// ListMCPConfigsPage forwards the MCP config page query.
func (s *Server) ListMCPConfigsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.MCPConfig], error) {
	return s.service.ListMCPConfigsPage(ctx, query)
}

// DeleteMCPConfig forwards one MCP config delete request.
func (s *Server) DeleteMCPConfig(ctx context.Context, name string) error {
	return s.service.DeleteMCPConfig(ctx, name)
}

// UpsertSandboxConfig forwards one sandbox config upsert request.
func (s *Server) UpsertSandboxConfig(
	ctx context.Context,
	config domain.SandboxConfig,
) (domain.SandboxConfig, error) {
	return s.service.UpsertSandboxConfig(ctx, config)
}

// GetSandboxConfig forwards one sandbox config lookup.
func (s *Server) GetSandboxConfig(ctx context.Context, name string) (domain.SandboxConfig, error) {
	return s.service.GetSandboxConfig(ctx, name)
}

// ListSandboxConfigs forwards the sandbox config list query.
func (s *Server) ListSandboxConfigs(ctx context.Context) ([]domain.SandboxConfig, error) {
	return s.service.ListSandboxConfigs(ctx)
}

// ListSandboxConfigsPage forwards the sandbox config page query.
func (s *Server) ListSandboxConfigsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.SandboxConfig], error) {
	return s.service.ListSandboxConfigsPage(ctx, query)
}

// DeleteSandboxConfig forwards one sandbox config delete request.
func (s *Server) DeleteSandboxConfig(ctx context.Context, name string) error {
	return s.service.DeleteSandboxConfig(ctx, name)
}

// UpsertAgentSpec forwards one agent spec upsert request.
func (s *Server) UpsertAgentSpec(
	ctx context.Context,
	spec domain.AuthoredAgentSpec,
) (domain.AuthoredAgentSpec, error) {
	return s.service.UpsertAgentSpec(ctx, spec)
}

// GetAgentSpec forwards one agent spec lookup.
func (s *Server) GetAgentSpec(ctx context.Context, name string) (domain.AuthoredAgentSpec, error) {
	return s.service.GetAgentSpec(ctx, name)
}

// ListAgentSpecs forwards the agent spec list query.
func (s *Server) ListAgentSpecs(ctx context.Context) ([]domain.AuthoredAgentSpec, error) {
	return s.service.ListAgentSpecs(ctx)
}

// ListAgentSpecsPage forwards the agent spec page query.
func (s *Server) ListAgentSpecsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.AuthoredAgentSpec], error) {
	return s.service.ListAgentSpecsPage(ctx, query)
}

// DeleteAgentSpec forwards one agent spec delete request.
func (s *Server) DeleteAgentSpec(ctx context.Context, name string) error {
	return s.service.DeleteAgentSpec(ctx, name)
}
