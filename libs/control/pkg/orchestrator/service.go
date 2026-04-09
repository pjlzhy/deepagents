package orchestrator

import (
	"agentctl/pkg/domain"
	"agentctl/pkg/packager"
	registrypkg "agentctl/pkg/registry"
	resolverpkg "agentctl/pkg/resolver"
	"agentctl/pkg/runtimeclient"
	"agentctl/pkg/telemetry"
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"time"
)

var (
	ErrEmptyAgentName      = errors.New("agent name must not be empty")
	errRegistryUnavailable = errors.New("registry must not be nil")
)

// Dependencies 描述 orchestrator 需要的核心依赖。
type Dependencies struct {
	Resolver       resolverpkg.Resolver
	Packager       packager.Packager
	Registry       registrypkg.Registry
	ResourceSync   runtimeclient.ResourceSyncClient
	Executor       runtimeclient.AgentExecutorClient
	Telemetry      runtimeclient.AgentTelemetryClient
	Sessions       runtimeclient.SessionQueryClient
	TelemetryStore telemetry.Store
}

// Service 是 control layer 的编排核心。
type Service struct {
	resolver       resolverpkg.Resolver
	packager       packager.Packager
	registry       registrypkg.Registry
	resourceSync   runtimeclient.ResourceSyncClient
	executor       runtimeclient.AgentExecutorClient
	telemetry      runtimeclient.AgentTelemetryClient
	sessions       runtimeclient.SessionQueryClient
	telemetryStore telemetry.Store
	ensureMu       sync.Mutex
	ensureInflight map[string]*ensureRunnableCall
	packageCacheMu sync.Mutex
	packagedSpecs  map[string]packagedSpecCacheEntry
}

type ensureRunnableCall struct {
	done chan struct{}
	err  error
}

type packagedSpecCacheEntry struct {
	revision string
	spec     domain.RuntimeAgentSpec
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
	case deps.Telemetry == nil:
		return nil, errors.New("telemetry client must not be nil")
	case deps.Sessions == nil:
		return nil, errors.New("session query client must not be nil")
	}
	if deps.TelemetryStore == nil {
		deps.TelemetryStore = noopTelemetryStore{}
	}

	return &Service{
		resolver:       deps.Resolver,
		packager:       deps.Packager,
		registry:       deps.Registry,
		resourceSync:   deps.ResourceSync,
		executor:       deps.Executor,
		telemetry:      deps.Telemetry,
		sessions:       deps.Sessions,
		telemetryStore: deps.TelemetryStore,
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
	call, leader := s.acquireEnsureRunnableCall(agentName)
	if !leader {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-call.done:
			return call.err
		}
	}

	err := s.ensureRunnableOnce(ctx, agentName)
	s.releaseEnsureRunnableCall(agentName, call, err)
	return err
}

func (s *Service) ensureRunnableOnce(
	ctx context.Context,
	agentName string,
) error {
	if err := ctx.Err(); err != nil {
		return err
	}

	spec, err := s.packagedSpecForEnsure(ctx, agentName)
	if err != nil {
		return err
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

func (s *Service) packagedSpecForEnsure(
	ctx context.Context,
	agentName string,
) (domain.RuntimeAgentSpec, error) {
	revision, cacheable, err := s.computeEnsureRevision(ctx, agentName)
	if err != nil {
		return domain.RuntimeAgentSpec{}, err
	}
	if cacheable {
		if spec, ok := s.loadCachedPackagedSpec(agentName, revision); ok {
			return spec, nil
		}
	}

	resolved, err := s.resolver.ResolveAgent(ctx, agentName)
	if err != nil {
		return domain.RuntimeAgentSpec{}, fmt.Errorf("resolve agent %q: %w", agentName, err)
	}

	spec, err := s.packager.Package(ctx, resolved)
	if err != nil {
		return domain.RuntimeAgentSpec{}, fmt.Errorf("package agent %q: %w", agentName, err)
	}

	if cacheable {
		s.storeCachedPackagedSpec(agentName, revision, spec)
	}
	return spec, nil
}

func (s *Service) acquireEnsureRunnableCall(agentName string) (*ensureRunnableCall, bool) {
	s.ensureMu.Lock()
	defer s.ensureMu.Unlock()

	if s.ensureInflight == nil {
		s.ensureInflight = make(map[string]*ensureRunnableCall)
	}

	call, ok := s.ensureInflight[agentName]
	if ok {
		return call, false
	}

	call = &ensureRunnableCall{done: make(chan struct{})}
	s.ensureInflight[agentName] = call
	return call, true
}

func (s *Service) releaseEnsureRunnableCall(
	agentName string,
	call *ensureRunnableCall,
	err error,
) {
	call.err = err

	s.ensureMu.Lock()
	if current, ok := s.ensureInflight[agentName]; ok && current == call {
		delete(s.ensureInflight, agentName)
	}
	s.ensureMu.Unlock()

	close(call.done)
}

func (s *Service) loadCachedPackagedSpec(
	agentName string,
	revision string,
) (domain.RuntimeAgentSpec, bool) {
	s.packageCacheMu.Lock()
	defer s.packageCacheMu.Unlock()

	entry, ok := s.packagedSpecs[agentName]
	if !ok || entry.revision != revision {
		return domain.RuntimeAgentSpec{}, false
	}
	return entry.spec, true
}

func (s *Service) storeCachedPackagedSpec(
	agentName string,
	revision string,
	spec domain.RuntimeAgentSpec,
) {
	s.packageCacheMu.Lock()
	defer s.packageCacheMu.Unlock()

	if s.packagedSpecs == nil {
		s.packagedSpecs = make(map[string]packagedSpecCacheEntry)
	}
	s.packagedSpecs[agentName] = packagedSpecCacheEntry{
		revision: revision,
		spec:     spec,
	}
}

func (s *Service) computeEnsureRevision(
	ctx context.Context,
	agentName string,
) (string, bool, error) {
	if s.registry == nil {
		return "", false, nil
	}

	agent, err := s.registry.GetAgentSpec(ctx, agentName)
	if err != nil {
		return "", false, fmt.Errorf("resolve agent %q: %w", agentName, err)
	}

	var builder strings.Builder
	writeEnsureRevisionToken(&builder, "agent", agent.Name, agent.UpdatedAt)
	writeEnsureRevisionToken(&builder, "model", agent.ModelRef, time.Time{})

	modelConfig, err := s.registry.GetModelConfig(ctx, agent.ModelRef)
	if err != nil {
		return "", false, fmt.Errorf("resolve agent %q: %w", agentName, err)
	}
	writeEnsureRevisionToken(&builder, "model", modelConfig.Name, modelConfig.UpdatedAt)

	for _, name := range agent.SkillRefs {
		skill, err := s.registry.GetSkill(ctx, name)
		if err != nil {
			return "", false, fmt.Errorf("resolve agent %q: %w", agentName, err)
		}
		writeEnsureRevisionToken(&builder, "skill", skill.Name, skill.UpdatedAt)
	}

	for _, name := range agent.MCPRefs {
		config, err := s.registry.GetMCPConfig(ctx, name)
		if err != nil {
			return "", false, fmt.Errorf("resolve agent %q: %w", agentName, err)
		}
		writeEnsureRevisionToken(&builder, "mcp", config.Name, config.UpdatedAt)
	}

	if agent.SandboxRef != "" {
		config, err := s.registry.GetSandboxConfig(ctx, agent.SandboxRef)
		if err != nil {
			return "", false, fmt.Errorf("resolve agent %q: %w", agentName, err)
		}
		writeEnsureRevisionToken(&builder, "sandbox", config.Name, config.UpdatedAt)
	}

	for _, subagent := range agent.Subagents {
		writeEnsureRevisionToken(&builder, "subagent", subagent.Name, time.Time{})
		if subagent.ModelRef != "" {
			model, err := s.registry.GetModelConfig(ctx, subagent.ModelRef)
			if err != nil {
				return "", false, fmt.Errorf("resolve agent %q: %w", agentName, err)
			}
			writeEnsureRevisionToken(&builder, "subagent_model", model.Name, model.UpdatedAt)
		}
		for _, skillRef := range subagent.SkillRefs {
			skill, err := s.registry.GetSkill(ctx, skillRef)
			if err != nil {
				return "", false, fmt.Errorf("resolve agent %q: %w", agentName, err)
			}
			writeEnsureRevisionToken(&builder, "subagent_skill", skill.Name, skill.UpdatedAt)
		}
	}

	return builder.String(), true, nil
}

func writeEnsureRevisionToken(
	builder *strings.Builder,
	kind string,
	name string,
	updatedAt time.Time,
) {
	builder.WriteString(kind)
	builder.WriteByte(':')
	builder.WriteString(strings.TrimSpace(name))
	builder.WriteByte('@')
	builder.WriteString(updatedAt.UTC().Format(time.RFC3339Nano))
	builder.WriteByte('\n')
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

// RunAgentTelemetry opens one telemetry-grade run stream.
func (s *Service) RunAgentTelemetry(
	ctx context.Context,
	req domain.RunRequest,
) (runtimeclient.TelemetryStream, error) {
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

	stream, err := s.telemetry.OpenRunTelemetry(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("open run telemetry stream for agent %q: %w", agentName, err)
	}
	return stream, nil
}

// RecordTelemetryEvent persists one telemetry event into the control-side store.
func (s *Service) RecordTelemetryEvent(
	ctx context.Context,
	event runtimeclient.TelemetryEvent,
) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	return s.telemetryStore.RecordEvent(ctx, event)
}

// ListTelemetryRuns returns one page of telemetry run summaries.
func (s *Service) ListTelemetryRuns(
	ctx context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.TelemetryRun], error) {
	if err := ctx.Err(); err != nil {
		return domain.ResourcePage[domain.TelemetryRun]{}, err
	}
	return s.telemetryStore.ListRuns(ctx, query)
}

// GetTelemetryRun returns one telemetry run summary by run ID.
func (s *Service) GetTelemetryRun(
	ctx context.Context,
	runID string,
) (domain.TelemetryRun, error) {
	if err := ctx.Err(); err != nil {
		return domain.TelemetryRun{}, err
	}
	return s.telemetryStore.GetRun(ctx, runID)
}

// ListTelemetryEvents returns one page of telemetry events for one run.
func (s *Service) ListTelemetryEvents(
	ctx context.Context,
	runID string,
	query domain.PageQuery,
) (domain.ResourcePage[domain.TelemetryEventRecord], error) {
	if err := ctx.Err(); err != nil {
		return domain.ResourcePage[domain.TelemetryEventRecord]{}, err
	}
	return s.telemetryStore.ListEvents(ctx, runID, query)
}

// ListTelemetrySteps projects one telemetry run into product-facing trace steps.
func (s *Service) ListTelemetrySteps(
	ctx context.Context,
	runID string,
) ([]domain.TelemetryStep, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if _, err := s.telemetryStore.GetRun(ctx, runID); err != nil {
		return nil, err
	}
	events, err := s.telemetryStore.LoadEvents(ctx, runID)
	if err != nil {
		return nil, err
	}
	return telemetry.BuildSteps(events), nil
}

type noopTelemetryStore struct{}

func (noopTelemetryStore) RecordEvent(context.Context, runtimeclient.TelemetryEvent) error {
	return nil
}

func (noopTelemetryStore) ListRuns(
	context.Context,
	domain.PageQuery,
) (domain.ResourcePage[domain.TelemetryRun], error) {
	return domain.ResourcePage[domain.TelemetryRun]{}, nil
}

func (noopTelemetryStore) GetRun(context.Context, string) (domain.TelemetryRun, error) {
	return domain.TelemetryRun{}, telemetry.ErrRunNotFound
}

func (noopTelemetryStore) ListEvents(
	context.Context,
	string,
	domain.PageQuery,
) (domain.ResourcePage[domain.TelemetryEventRecord], error) {
	return domain.ResourcePage[domain.TelemetryEventRecord]{}, nil
}

func (noopTelemetryStore) LoadEvents(context.Context, string) ([]domain.TelemetryEventRecord, error) {
	return nil, nil
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

// DownloadWorkspaceFile streams one workspace file into the provided writer.
func (s *Service) DownloadWorkspaceFile(
	ctx context.Context,
	req domain.WorkspaceFileDownloadRequest,
	writer io.Writer,
) error {
	if err := ctx.Err(); err != nil {
		return err
	}

	agentName := strings.TrimSpace(req.AgentName)
	if agentName == "" {
		return ErrEmptyAgentName
	}
	req.AgentName = agentName

	if strings.TrimSpace(req.ThreadID) == "" {
		return fmt.Errorf("thread_id is required")
	}
	if strings.TrimSpace(req.Path) == "" {
		return fmt.Errorf("path is required")
	}

	if err := s.ensureRunnable(ctx, agentName); err != nil {
		return fmt.Errorf(
			"ensure runnable agent %q: %w",
			agentName,
			err,
		)
	}

	if err := s.resourceSync.DownloadWorkspaceFile(ctx, req, writer); err != nil {
		return fmt.Errorf(
			"download workspace file %q for agent %q: %w",
			req.Path,
			agentName,
			err,
		)
	}
	return nil
}

// ListWorkspaceFiles lists files in one agent/thread workspace directory.
func (s *Service) ListWorkspaceFiles(
	ctx context.Context,
	req domain.WorkspaceListRequest,
) (domain.WorkspaceListResponse, error) {
	if err := ctx.Err(); err != nil {
		return domain.WorkspaceListResponse{}, err
	}

	agentName := strings.TrimSpace(req.AgentName)
	if agentName == "" {
		return domain.WorkspaceListResponse{}, ErrEmptyAgentName
	}
	req.AgentName = agentName

	if err := s.ensureRunnable(ctx, agentName); err != nil {
		return domain.WorkspaceListResponse{}, fmt.Errorf(
			"ensure runnable agent %q: %w",
			agentName,
			err,
		)
	}

	response, err := s.resourceSync.ListWorkspaceFiles(ctx, req)
	if err != nil {
		return domain.WorkspaceListResponse{}, fmt.Errorf(
			"list workspace files for agent %q: %w",
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

// GetAgentGraph ensures the agent is runnable, then returns its drawable graph.
func (s *Service) GetAgentGraph(
	ctx context.Context,
	agentName string,
	xrayDepth int32,
) ([]byte, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}

	trimmedAgentName := strings.TrimSpace(agentName)
	if trimmedAgentName == "" {
		return nil, ErrEmptyAgentName
	}
	if xrayDepth < 0 {
		return nil, fmt.Errorf("xray depth must be non-negative")
	}

	if err := s.ensureRunnable(ctx, trimmedAgentName); err != nil {
		return nil, fmt.Errorf("ensure runnable agent %q: %w", trimmedAgentName, err)
	}

	graph, err := s.resourceSync.GetAgentGraph(ctx, trimmedAgentName, xrayDepth)
	if err != nil {
		return nil, fmt.Errorf("get agent graph %q: %w", trimmedAgentName, err)
	}
	return graph, nil
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

// ListThreadArtifacts queries artifact metadata for one thread from checkpoint state.
func (s *Service) ListThreadArtifacts(
	ctx context.Context,
	req domain.ListArtifactsRequest,
) (domain.ListArtifactsResponse, error) {
	resp, err := s.sessions.ListThreadArtifacts(ctx, req)
	if err != nil {
		return domain.ListArtifactsResponse{}, fmt.Errorf("list thread artifacts %q: %w", req.ThreadID, err)
	}
	return resp, nil
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
