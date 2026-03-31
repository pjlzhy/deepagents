package orchestrator

import (
	"agentctl/pkg/domain"
	"agentctl/pkg/packager"
	registrypkg "agentctl/pkg/registry"
	resolverpkg "agentctl/pkg/resolver"
	"agentctl/pkg/runtimeclient"
	"context"
	"errors"
	"fmt"
	"strings"
)

var (
	ErrEmptyAgentName      = errors.New("agent name must not be empty")
	errRegistryUnavailable = errors.New("registry must not be nil")
)

// Dependencies 描述 orchestrator 需要的核心依赖。
type Dependencies struct {
	Resolver     resolverpkg.Resolver
	Packager     packager.Packager
	Registry     registrypkg.Registry
	ResourceSync runtimeclient.ResourceSyncClient
	Executor     runtimeclient.AgentExecutorClient
	Sessions     runtimeclient.SessionQueryClient
}

// Service 是 control layer 的编排核心。
type Service struct {
	resolver     resolverpkg.Resolver
	packager     packager.Packager
	registry     registrypkg.Registry
	resourceSync runtimeclient.ResourceSyncClient
	executor     runtimeclient.AgentExecutorClient
	sessions     runtimeclient.SessionQueryClient
}

// NewService 创建一个新的 orchestrator service。
func NewService(deps Dependencies) (*Service, error) {
	switch {
	case deps.Resolver == nil:
		return nil, errors.New("resolver must not be nil")
	case deps.Packager == nil:
		return nil, errors.New("packager must not be nil")
	case deps.ResourceSync == nil:
		return nil, errors.New("resource sync client must not be nil")
	case deps.Executor == nil:
		return nil, errors.New("executor client must not be nil")
	case deps.Sessions == nil:
		return nil, errors.New("session query client must not be nil")
	}

	return &Service{
		resolver:     deps.Resolver,
		packager:     deps.Packager,
		registry:     deps.Registry,
		resourceSync: deps.ResourceSync,
		executor:     deps.Executor,
		sessions:     deps.Sessions,
	}, nil
}

// EnsureRunnable 预留 install + compile 的统一编排入口。
func (s *Service) EnsureRunnable(ctx context.Context, agentName string) error {
	return s.ensureRunnable(ctx, agentName)
}

func (s *Service) ensureRunnable(
	ctx context.Context,
	agentName string,
) error {
	if err := ctx.Err(); err != nil {
		return err
	}

	resolved, err := s.resolver.ResolveAgent(ctx, agentName)
	if err != nil {
		return fmt.Errorf("resolve agent %q: %w", agentName, err)
	}

	spec, err := s.packager.Package(ctx, resolved)
	if err != nil {
		return fmt.Errorf("package agent %q: %w", agentName, err)
	}

	syncResp, err := s.resourceSync.SyncAgentSpec(ctx, spec)
	if err != nil {
		return fmt.Errorf("sync agent spec %q: %w", spec.Name, err)
	}
	if !syncResp.OK {
		return fmt.Errorf(
			"sync agent spec %q failed: %s",
			spec.Name,
			normalizeErrorMessage(syncResp.Message),
		)
	}

	assembleResp, err := s.resourceSync.Assemble(ctx, spec.Name)
	if err != nil {
		return fmt.Errorf("assemble agent %q: %w", spec.Name, err)
	}
	if !assembleResp.OK {
		msg := normalizeErrorMessage(assembleResp.Message)
		if status := strings.TrimSpace(assembleResp.Status); status != "" {
			msg = fmt.Sprintf("%s (status=%s)", msg, status)
		}
		return fmt.Errorf("assemble agent %q failed: %s", spec.Name, msg)
	}

	return nil
}

// RunAgent 预留 northbound run stream 的统一入口。
func (s *Service) RunAgent(
	ctx context.Context,
	req domain.RunRequest,
) (runtimeclient.RunStream, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}

	agentName := strings.TrimSpace(req.AgentName)
	if agentName == "" {
		return nil, ErrEmptyAgentName
	}
	req.AgentName = agentName

	if err := s.ensureRunnable(ctx, agentName); err != nil {
		return nil, fmt.Errorf("ensure runnable agent %q: %w", agentName, err)
	}

	stream, err := s.executor.OpenRun(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("open run stream for agent %q: %w", agentName, err)
	}
	return stream, nil
}

// UploadWorkspaceFiles stages files into one agent/thread workspace before execution.
func (s *Service) UploadWorkspaceFiles(
	ctx context.Context,
	req domain.WorkspaceUploadRequest,
) (domain.WorkspaceUploadResponse, error) {
	if err := ctx.Err(); err != nil {
		return domain.WorkspaceUploadResponse{}, err
	}

	agentName := strings.TrimSpace(req.AgentName)
	if agentName == "" {
		return domain.WorkspaceUploadResponse{}, ErrEmptyAgentName
	}
	req.AgentName = agentName

	if err := s.ensureRunnable(ctx, agentName); err != nil {
		return domain.WorkspaceUploadResponse{}, fmt.Errorf(
			"ensure runnable agent %q: %w",
			agentName,
			err,
		)
	}

	response, err := s.resourceSync.UploadWorkspaceFiles(ctx, req)
	if err != nil {
		return domain.WorkspaceUploadResponse{}, fmt.Errorf(
			"upload workspace files for agent %q: %w",
			agentName,
			err,
		)
	}
	return response, nil
}

// Health 预留 data plane health 的 northbound 聚合入口。
func (s *Service) Health(ctx context.Context) (runtimeclient.HealthResponse, error) {
	resp, err := s.resourceSync.Health(ctx)
	if err != nil {
		return runtimeclient.HealthResponse{}, fmt.Errorf("query runtime health: %w", err)
	}
	return resp, nil
}

// ListSessions queries recent runtime sessions, optionally filtered by agent.
func (s *Service) ListSessions(
	ctx context.Context,
	agentName string,
	pageSize int32,
	pageToken string,
) ([]domain.SessionSummary, string, error) {
	sessions, nextPageToken, err := s.sessions.ListSessions(ctx, agentName, pageSize, pageToken)
	if err != nil {
		return nil, "", fmt.Errorf("list sessions: %w", err)
	}
	return sessions, nextPageToken, nil
}

// GetSession returns one session summary and checkpoint count by agent-scoped thread ID.
func (s *Service) GetSession(
	ctx context.Context,
	locator domain.SessionLocator,
) (domain.SessionSummary, error) {
	session, err := s.sessions.GetSession(ctx, locator)
	if err != nil {
		return domain.SessionSummary{}, fmt.Errorf(
			"get session %q/%q: %w",
			locator.AgentName,
			locator.ThreadID,
			err,
		)
	}
	return session, nil
}

// GetSessionMessagePage returns one full page of checkpoint-backed session history.
func (s *Service) GetSessionMessagePage(
	ctx context.Context,
	query domain.SessionMessageQuery,
) (domain.SessionMessagePage, error) {
	page, err := s.sessions.GetSessionMessagePage(ctx, query)
	if err != nil {
		return domain.SessionMessagePage{}, fmt.Errorf(
			"get session message page for agent %q thread %q: %w",
			query.AgentName,
			query.ThreadID,
			err,
		)
	}
	return page, nil
}

// GetSessionMessages keeps the legacy convenience view for callers that only need messages.
func (s *Service) GetSessionMessages(
	ctx context.Context,
	query domain.SessionMessageQuery,
) ([]domain.SessionMessage, string, error) {
	messages, nextPageToken, err := s.sessions.GetSessionMessages(ctx, query)
	if err != nil {
		return nil, "", fmt.Errorf(
			"get session messages for agent %q thread %q: %w",
			query.AgentName,
			query.ThreadID,
			err,
		)
	}
	return messages, nextPageToken, nil
}

// GetLatestSession returns the newest runtime session, optionally filtered by agent.
func (s *Service) GetLatestSession(ctx context.Context, agentName string) (domain.SessionSummary, error) {
	session, err := s.sessions.GetLatestSession(ctx, agentName)
	if err != nil {
		return domain.SessionSummary{}, fmt.Errorf("get latest session for agent %q: %w", agentName, err)
	}
	return session, nil
}

// DeleteSession removes one runtime-local session by agent-scoped thread ID.
func (s *Service) DeleteSession(ctx context.Context, locator domain.SessionLocator) error {
	if err := s.sessions.DeleteSession(ctx, locator); err != nil {
		return fmt.Errorf("delete session %q/%q: %w", locator.AgentName, locator.ThreadID, err)
	}
	return nil
}

// UpsertModelConfig persists one reusable model config and returns the stored value.
func (s *Service) UpsertModelConfig(
	ctx context.Context,
	config domain.ModelConfig,
) (domain.ModelConfig, error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.ModelConfig{}, err
	}
	if err := reg.UpsertModelConfig(ctx, config); err != nil {
		return domain.ModelConfig{}, fmt.Errorf("upsert model config %q: %w", config.Name, err)
	}
	stored, err := reg.GetModelConfig(ctx, config.Name)
	if err != nil {
		return domain.ModelConfig{}, fmt.Errorf("get model config %q after upsert: %w", config.Name, err)
	}
	return stored, nil
}

// GetModelConfig returns one model config by name.
func (s *Service) GetModelConfig(ctx context.Context, name string) (domain.ModelConfig, error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.ModelConfig{}, err
	}
	config, err := reg.GetModelConfig(ctx, name)
	if err != nil {
		return domain.ModelConfig{}, fmt.Errorf("get model config %q: %w", name, err)
	}
	return config, nil
}

// ListModelConfigs returns all model configs ordered by name.
func (s *Service) ListModelConfigs(ctx context.Context) ([]domain.ModelConfig, error) {
	page, err := s.ListModelConfigsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

// ListModelConfigsPage returns one page of model configs ordered by name.
func (s *Service) ListModelConfigsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.ModelConfig], error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.ResourcePage[domain.ModelConfig]{}, err
	}
	page, err := reg.ListModelConfigsPage(ctx, query)
	if err != nil {
		return domain.ResourcePage[domain.ModelConfig]{}, fmt.Errorf("list model config page: %w", err)
	}
	return page, nil
}

// DeleteModelConfig removes one model config.
func (s *Service) DeleteModelConfig(ctx context.Context, name string) error {
	reg, err := s.registryOrError()
	if err != nil {
		return err
	}
	if err := reg.DeleteModelConfig(ctx, name); err != nil {
		return fmt.Errorf("delete model config %q: %w", name, err)
	}
	return nil
}

// UpsertSkill persists one skill snapshot and returns the stored value.
func (s *Service) UpsertSkill(ctx context.Context, skill domain.Skill) (domain.Skill, error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.Skill{}, err
	}
	if err := reg.UpsertSkill(ctx, skill); err != nil {
		return domain.Skill{}, fmt.Errorf("upsert skill %q: %w", skill.Name, err)
	}
	stored, err := reg.GetSkill(ctx, skill.Name)
	if err != nil {
		return domain.Skill{}, fmt.Errorf("get skill %q after upsert: %w", skill.Name, err)
	}
	return stored, nil
}

// GetSkill returns one skill by name.
func (s *Service) GetSkill(ctx context.Context, name string) (domain.Skill, error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.Skill{}, err
	}
	skill, err := reg.GetSkill(ctx, name)
	if err != nil {
		return domain.Skill{}, fmt.Errorf("get skill %q: %w", name, err)
	}
	return skill, nil
}

// ListSkills returns all skills ordered by name.
func (s *Service) ListSkills(ctx context.Context) ([]domain.Skill, error) {
	page, err := s.ListSkillsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

// ListSkillsPage returns one page of skills ordered by name.
func (s *Service) ListSkillsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.Skill], error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.ResourcePage[domain.Skill]{}, err
	}
	page, err := reg.ListSkillsPage(ctx, query)
	if err != nil {
		return domain.ResourcePage[domain.Skill]{}, fmt.Errorf("list skill page: %w", err)
	}
	return page, nil
}

// DeleteSkill removes one skill.
func (s *Service) DeleteSkill(ctx context.Context, name string) error {
	reg, err := s.registryOrError()
	if err != nil {
		return err
	}
	if err := reg.DeleteSkill(ctx, name); err != nil {
		return fmt.Errorf("delete skill %q: %w", name, err)
	}
	return nil
}

// UpsertMCPConfig persists one MCP config and returns the stored value.
func (s *Service) UpsertMCPConfig(ctx context.Context, config domain.MCPConfig) (domain.MCPConfig, error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.MCPConfig{}, err
	}
	if err := reg.UpsertMCPConfig(ctx, config); err != nil {
		return domain.MCPConfig{}, fmt.Errorf("upsert mcp config %q: %w", config.Name, err)
	}
	stored, err := reg.GetMCPConfig(ctx, config.Name)
	if err != nil {
		return domain.MCPConfig{}, fmt.Errorf("get mcp config %q after upsert: %w", config.Name, err)
	}
	return stored, nil
}

// GetMCPConfig returns one MCP config by name.
func (s *Service) GetMCPConfig(ctx context.Context, name string) (domain.MCPConfig, error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.MCPConfig{}, err
	}
	config, err := reg.GetMCPConfig(ctx, name)
	if err != nil {
		return domain.MCPConfig{}, fmt.Errorf("get mcp config %q: %w", name, err)
	}
	return config, nil
}

// ListMCPConfigs returns all MCP configs ordered by name.
func (s *Service) ListMCPConfigs(ctx context.Context) ([]domain.MCPConfig, error) {
	page, err := s.ListMCPConfigsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

// ListMCPConfigsPage returns one page of MCP configs ordered by name.
func (s *Service) ListMCPConfigsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.MCPConfig], error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.ResourcePage[domain.MCPConfig]{}, err
	}
	page, err := reg.ListMCPConfigsPage(ctx, query)
	if err != nil {
		return domain.ResourcePage[domain.MCPConfig]{}, fmt.Errorf("list mcp config page: %w", err)
	}
	return page, nil
}

// DeleteMCPConfig removes one MCP config.
func (s *Service) DeleteMCPConfig(ctx context.Context, name string) error {
	reg, err := s.registryOrError()
	if err != nil {
		return err
	}
	if err := reg.DeleteMCPConfig(ctx, name); err != nil {
		return fmt.Errorf("delete mcp config %q: %w", name, err)
	}
	return nil
}

// UpsertSandboxConfig persists one sandbox config and returns the stored value.
func (s *Service) UpsertSandboxConfig(
	ctx context.Context,
	config domain.SandboxConfig,
) (domain.SandboxConfig, error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.SandboxConfig{}, err
	}
	if err := reg.UpsertSandboxConfig(ctx, config); err != nil {
		return domain.SandboxConfig{}, fmt.Errorf("upsert sandbox config %q: %w", config.Name, err)
	}
	stored, err := reg.GetSandboxConfig(ctx, config.Name)
	if err != nil {
		return domain.SandboxConfig{}, fmt.Errorf("get sandbox config %q after upsert: %w", config.Name, err)
	}
	return stored, nil
}

// GetSandboxConfig returns one sandbox config by name.
func (s *Service) GetSandboxConfig(ctx context.Context, name string) (domain.SandboxConfig, error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.SandboxConfig{}, err
	}
	config, err := reg.GetSandboxConfig(ctx, name)
	if err != nil {
		return domain.SandboxConfig{}, fmt.Errorf("get sandbox config %q: %w", name, err)
	}
	return config, nil
}

// ListSandboxConfigs returns all sandbox configs ordered by name.
func (s *Service) ListSandboxConfigs(ctx context.Context) ([]domain.SandboxConfig, error) {
	page, err := s.ListSandboxConfigsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

// ListSandboxConfigsPage returns one page of sandbox configs ordered by name.
func (s *Service) ListSandboxConfigsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.SandboxConfig], error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.ResourcePage[domain.SandboxConfig]{}, err
	}
	page, err := reg.ListSandboxConfigsPage(ctx, query)
	if err != nil {
		return domain.ResourcePage[domain.SandboxConfig]{}, fmt.Errorf("list sandbox config page: %w", err)
	}
	return page, nil
}

// DeleteSandboxConfig removes one sandbox config.
func (s *Service) DeleteSandboxConfig(ctx context.Context, name string) error {
	reg, err := s.registryOrError()
	if err != nil {
		return err
	}
	if err := reg.DeleteSandboxConfig(ctx, name); err != nil {
		return fmt.Errorf("delete sandbox config %q: %w", name, err)
	}
	return nil
}

// UpsertAgentSpec persists one authored agent spec and returns the stored value.
func (s *Service) UpsertAgentSpec(
	ctx context.Context,
	spec domain.AuthoredAgentSpec,
) (domain.AuthoredAgentSpec, error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.AuthoredAgentSpec{}, err
	}
	if err := reg.UpsertAgentSpec(ctx, spec); err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf("upsert agent spec %q: %w", spec.Name, err)
	}
	stored, err := reg.GetAgentSpec(ctx, spec.Name)
	if err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf("get agent spec %q after upsert: %w", spec.Name, err)
	}
	return stored, nil
}

// GetAgentSpec returns one authored agent spec by name.
func (s *Service) GetAgentSpec(ctx context.Context, name string) (domain.AuthoredAgentSpec, error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.AuthoredAgentSpec{}, err
	}
	spec, err := reg.GetAgentSpec(ctx, name)
	if err != nil {
		return domain.AuthoredAgentSpec{}, fmt.Errorf("get agent spec %q: %w", name, err)
	}
	return spec, nil
}

// ListAgentSpecs returns all authored agent specs ordered by name.
func (s *Service) ListAgentSpecs(ctx context.Context) ([]domain.AuthoredAgentSpec, error) {
	page, err := s.ListAgentSpecsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

// ListAgentSpecsPage returns one page of authored agent specs ordered by name.
func (s *Service) ListAgentSpecsPage(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.AuthoredAgentSpec], error) {
	reg, err := s.registryOrError()
	if err != nil {
		return domain.ResourcePage[domain.AuthoredAgentSpec]{}, err
	}
	page, err := reg.ListAgentSpecsPage(ctx, query)
	if err != nil {
		return domain.ResourcePage[domain.AuthoredAgentSpec]{}, fmt.Errorf("list agent spec page: %w", err)
	}
	return page, nil
}

// DeleteAgentSpec removes one authored agent spec.
func (s *Service) DeleteAgentSpec(ctx context.Context, name string) error {
	reg, err := s.registryOrError()
	if err != nil {
		return err
	}
	if err := reg.DeleteAgentSpec(ctx, name); err != nil {
		return fmt.Errorf("delete agent spec %q: %w", name, err)
	}
	return nil
}

func (s *Service) registryOrError() (registrypkg.Registry, error) {
	if s.registry == nil {
		return nil, errRegistryUnavailable
	}
	return s.registry, nil
}

func normalizeErrorMessage(msg string) string {
	normalized := strings.TrimSpace(msg)
	if normalized == "" {
		return "unknown error"
	}
	return normalized
}
