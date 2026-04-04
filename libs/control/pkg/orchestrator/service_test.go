package orchestrator

import (
	"agentctl/pkg/domain"
	registrypkg "agentctl/pkg/registry"
	"agentctl/pkg/runtimeclient"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"testing"
)

type fakeResolver struct {
	result       domain.ResolvedAgentInput
	err          error
	callLog      *[]string
	gotAgentName string
}

func (f *fakeResolver) ResolveAgent(_ context.Context, agentName string) (domain.ResolvedAgentInput, error) {
	if f.callLog != nil {
		*f.callLog = append(*f.callLog, "resolve")
	}
	f.gotAgentName = agentName
	return f.result, f.err
}

type fakePackager struct {
	result        domain.RuntimeAgentSpec
	err           error
	gotInput      domain.ResolvedAgentInput
	receivedInput bool
	callLog       *[]string
}

func (f *fakePackager) Package(
	_ context.Context,
	input domain.ResolvedAgentInput,
) (domain.RuntimeAgentSpec, error) {
	if f.callLog != nil {
		*f.callLog = append(*f.callLog, "package")
	}
	f.gotInput = input
	f.receivedInput = true
	return f.result, f.err
}

type stubRegistry struct {
	models    map[string]domain.ModelConfig
	skills    map[string]domain.Skill
	mcps      map[string]domain.MCPConfig
	sandboxes map[string]domain.SandboxConfig
	agents    map[string]domain.AuthoredAgentSpec
}

func paginateNamedMap[T any](
	items map[string]T,
	query domain.PageQuery,
) (domain.ResourcePage[T], error) {
	if query.PageSize < 0 {
		return domain.ResourcePage[T]{}, fmt.Errorf("%w: page_size must be non-negative", registrypkg.ErrInvalid)
	}
	if query.PageNumber < 0 {
		return domain.ResourcePage[T]{}, fmt.Errorf("%w: page_number must be non-negative", registrypkg.ErrInvalid)
	}
	if query.PageSize == 0 && query.PageNumber > 0 {
		return domain.ResourcePage[T]{}, fmt.Errorf("%w: page_number requires page_size", registrypkg.ErrInvalid)
	}
	if query.PageSize > 0 && query.PageNumber == 0 {
		query.PageNumber = 1
	}

	keys := make([]string, 0, len(items))
	for name := range items {
		keys = append(keys, name)
	}
	sort.Strings(keys)

	totalSize := int32(len(keys))
	start := 0
	end := len(keys)
	metadata := domain.PageMetadata{TotalSize: totalSize}
	if query.PageSize > 0 {
		metadata.PageSize = query.PageSize
		metadata.PageNumber = query.PageNumber
		metadata.TotalPages = (totalSize + query.PageSize - 1) / query.PageSize

		start = int(query.PageSize * (query.PageNumber - 1))
		if start > len(keys) {
			start = len(keys)
		}
		end = start + int(query.PageSize)
		if end > len(keys) {
			end = len(keys)
		}
	}

	pageItems := make([]T, 0, end-start)
	for _, name := range keys[start:end] {
		pageItems = append(pageItems, items[name])
	}

	return domain.ResourcePage[T]{
		Items:        pageItems,
		PageMetadata: metadata,
	}, nil
}

func (s *stubRegistry) UpsertModelConfig(_ context.Context, config domain.ModelConfig) error {
	if s.models == nil {
		s.models = make(map[string]domain.ModelConfig)
	}
	s.models[config.Name] = config
	return nil
}

func (s *stubRegistry) GetModelConfig(_ context.Context, name string) (domain.ModelConfig, error) {
	config, ok := s.models[name]
	if !ok {
		return domain.ModelConfig{}, registrypkg.ErrNotFound
	}
	return config, nil
}

func (s *stubRegistry) ListModelConfigs(ctx context.Context) ([]domain.ModelConfig, error) {
	page, err := s.ListModelConfigsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

func (s *stubRegistry) ListModelConfigsPage(
	_ context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.ModelConfig], error) {
	return paginateNamedMap(s.models, query)
}

func (s *stubRegistry) DeleteModelConfig(_ context.Context, name string) error {
	delete(s.models, name)
	return nil
}

func (s *stubRegistry) UpsertSkill(_ context.Context, skill domain.Skill) error {
	if s.skills == nil {
		s.skills = make(map[string]domain.Skill)
	}
	s.skills[skill.Name] = skill
	return nil
}

func (s *stubRegistry) GetSkill(_ context.Context, name string) (domain.Skill, error) {
	skill, ok := s.skills[name]
	if !ok {
		return domain.Skill{}, registrypkg.ErrNotFound
	}
	return skill, nil
}

func (s *stubRegistry) ListSkills(ctx context.Context) ([]domain.Skill, error) {
	page, err := s.ListSkillsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

func (s *stubRegistry) ListSkillsPage(
	_ context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.Skill], error) {
	return paginateNamedMap(s.skills, query)
}

func (s *stubRegistry) DeleteSkill(_ context.Context, name string) error {
	delete(s.skills, name)
	return nil
}

func (s *stubRegistry) UpsertMCPConfig(_ context.Context, config domain.MCPConfig) error {
	if s.mcps == nil {
		s.mcps = make(map[string]domain.MCPConfig)
	}
	s.mcps[config.Name] = config
	return nil
}

func (s *stubRegistry) GetMCPConfig(_ context.Context, name string) (domain.MCPConfig, error) {
	config, ok := s.mcps[name]
	if !ok {
		return domain.MCPConfig{}, registrypkg.ErrNotFound
	}
	return config, nil
}

func (s *stubRegistry) ListMCPConfigs(ctx context.Context) ([]domain.MCPConfig, error) {
	page, err := s.ListMCPConfigsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

func (s *stubRegistry) ListMCPConfigsPage(
	_ context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.MCPConfig], error) {
	return paginateNamedMap(s.mcps, query)
}

func (s *stubRegistry) DeleteMCPConfig(_ context.Context, name string) error {
	delete(s.mcps, name)
	return nil
}

func (s *stubRegistry) UpsertSandboxConfig(_ context.Context, config domain.SandboxConfig) error {
	if s.sandboxes == nil {
		s.sandboxes = make(map[string]domain.SandboxConfig)
	}
	s.sandboxes[config.Name] = config
	return nil
}

func (s *stubRegistry) GetSandboxConfig(_ context.Context, name string) (domain.SandboxConfig, error) {
	config, ok := s.sandboxes[name]
	if !ok {
		return domain.SandboxConfig{}, registrypkg.ErrNotFound
	}
	return config, nil
}

func (s *stubRegistry) ListSandboxConfigs(ctx context.Context) ([]domain.SandboxConfig, error) {
	page, err := s.ListSandboxConfigsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

func (s *stubRegistry) ListSandboxConfigsPage(
	_ context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.SandboxConfig], error) {
	return paginateNamedMap(s.sandboxes, query)
}

func (s *stubRegistry) DeleteSandboxConfig(_ context.Context, name string) error {
	delete(s.sandboxes, name)
	return nil
}

func (s *stubRegistry) UpsertAgentSpec(_ context.Context, spec domain.AuthoredAgentSpec) error {
	if s.agents == nil {
		s.agents = make(map[string]domain.AuthoredAgentSpec)
	}
	s.agents[spec.Name] = spec
	return nil
}

func (s *stubRegistry) GetAgentSpec(_ context.Context, name string) (domain.AuthoredAgentSpec, error) {
	spec, ok := s.agents[name]
	if !ok {
		return domain.AuthoredAgentSpec{}, registrypkg.ErrNotFound
	}
	return spec, nil
}

func (s *stubRegistry) ListAgentSpecs(ctx context.Context) ([]domain.AuthoredAgentSpec, error) {
	page, err := s.ListAgentSpecsPage(ctx, domain.PageQuery{})
	if err != nil {
		return nil, err
	}
	return page.Items, nil
}

func (s *stubRegistry) ListAgentSpecsPage(
	_ context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.AuthoredAgentSpec], error) {
	return paginateNamedMap(s.agents, query)
}

func (s *stubRegistry) DeleteAgentSpec(_ context.Context, name string) error {
	delete(s.agents, name)
	return nil
}

func (*stubRegistry) UpsertDeployment(context.Context, domain.Deployment) error { return nil }
func (*stubRegistry) GetDeployment(context.Context, string) (domain.Deployment, error) {
	return domain.Deployment{}, nil
}
func (*stubRegistry) UpsertRuntimeTarget(context.Context, domain.RuntimeTarget) error { return nil }
func (*stubRegistry) GetRuntimeTarget(context.Context, string) (domain.RuntimeTarget, error) {
	return domain.RuntimeTarget{}, nil
}
func (*stubRegistry) ListRuntimeTargets(context.Context) ([]domain.RuntimeTarget, error) {
	return nil, nil
}
func (*stubRegistry) CreateOperation(context.Context, domain.Operation) error { return nil }

type fakeResourceSyncClient struct {
	syncResp       runtimeclient.SyncResponse
	syncErr        error
	assembleResp   runtimeclient.AssembleResponse
	assembleErr    error
	graphResp      json.RawMessage
	graphErr       error
	graphAgentName string
	graphXrayDepth int32
	uploadResp     domain.WorkspaceUploadResponse
	uploadErr      error
	downloadResp   domain.WorkspaceDownloadResponse
	downloadErr    error
	downloadReq    domain.WorkspaceDownloadRequest
	listResp       domain.WorkspaceListResponse
	listErr        error
	listReq        domain.WorkspaceListRequest
	healthResp     runtimeclient.HealthResponse
	healthErr      error
	syncedSpec     domain.RuntimeAgentSpec
	assembledAgent string
	uploadReq      domain.WorkspaceUploadRequest
	callLog        *[]string
}

func (f *fakeResourceSyncClient) SyncAgentSpec(
	_ context.Context,
	spec domain.RuntimeAgentSpec,
) (runtimeclient.SyncResponse, error) {
	if f.callLog != nil {
		*f.callLog = append(*f.callLog, "sync")
	}
	f.syncedSpec = spec
	return f.syncResp, f.syncErr
}

func (f *fakeResourceSyncClient) Assemble(
	_ context.Context,
	agentName string,
) (runtimeclient.AssembleResponse, error) {
	if f.callLog != nil {
		*f.callLog = append(*f.callLog, "assemble")
	}
	f.assembledAgent = agentName
	return f.assembleResp, f.assembleErr
}

func (f *fakeResourceSyncClient) UploadWorkspaceFiles(
	_ context.Context,
	req domain.WorkspaceUploadRequest,
) (domain.WorkspaceUploadResponse, error) {
	f.uploadReq = req
	return f.uploadResp, f.uploadErr
}

func (f *fakeResourceSyncClient) DownloadWorkspaceFiles(
	_ context.Context,
	req domain.WorkspaceDownloadRequest,
) (domain.WorkspaceDownloadResponse, error) {
	f.downloadReq = req
	return f.downloadResp, f.downloadErr
}

func (f *fakeResourceSyncClient) ListWorkspaceFiles(
	_ context.Context,
	req domain.WorkspaceListRequest,
) (domain.WorkspaceListResponse, error) {
	f.listReq = req
	return f.listResp, f.listErr
}

func (f *fakeResourceSyncClient) RemoveAgent(
	context.Context,
	string,
) (runtimeclient.SyncResponse, error) {
	return runtimeclient.SyncResponse{}, nil
}

func (f *fakeResourceSyncClient) Health(context.Context) (runtimeclient.HealthResponse, error) {
	return f.healthResp, f.healthErr
}

func (f *fakeResourceSyncClient) GetAgentGraph(
	_ context.Context,
	agentName string,
	xrayDepth int32,
) (json.RawMessage, error) {
	f.graphAgentName = agentName
	f.graphXrayDepth = xrayDepth
	return f.graphResp, f.graphErr
}

type fakeExecutorClient struct{}

func (fakeExecutorClient) OpenRun(context.Context, domain.RunRequest) (runtimeclient.RunStream, error) {
	return nil, errors.New("unused in constructor tests")
}

func (fakeExecutorClient) OpenRunTelemetry(context.Context, domain.RunRequest) (runtimeclient.TelemetryStream, error) {
	return nil, errors.New("unused in constructor tests")
}

type stubRunStream struct {
	events chan runtimeclient.AgentEvent
}

func newStubRunStream() *stubRunStream {
	return &stubRunStream{events: make(chan runtimeclient.AgentEvent)}
}

func (s *stubRunStream) Events() <-chan runtimeclient.AgentEvent {
	return s.events
}

func (*stubRunStream) SendHITLDecision(context.Context, string, []runtimeclient.ToolDecision) error {
	return nil
}

func (*stubRunStream) SendCancel(context.Context, string) error {
	return nil
}

func (*stubRunStream) Close() error {
	return nil
}

type stubTelemetryStream struct {
	events chan runtimeclient.TelemetryEvent
}

func newStubTelemetryStream() *stubTelemetryStream {
	return &stubTelemetryStream{events: make(chan runtimeclient.TelemetryEvent)}
}

func (s *stubTelemetryStream) Events() <-chan runtimeclient.TelemetryEvent {
	return s.events
}

func (*stubTelemetryStream) SendHITLDecision(context.Context, string, []runtimeclient.ToolDecision) error {
	return nil
}

func (*stubTelemetryStream) SendCancel(context.Context, string) error {
	return nil
}

func (*stubTelemetryStream) Close() error {
	return nil
}

type stubExecutorClient struct {
	stream          runtimeclient.RunStream
	err             error
	gotReq          domain.RunRequest
	calls           int
	callLog         *[]string
	telemetryStream runtimeclient.TelemetryStream
	telemetryErr    error
	gotTelemetryReq domain.RunRequest
	telemetryCalls  int
}

func (s *stubExecutorClient) OpenRun(
	_ context.Context,
	req domain.RunRequest,
) (runtimeclient.RunStream, error) {
	if s.callLog != nil {
		*s.callLog = append(*s.callLog, "open_run")
	}
	s.gotReq = req
	s.calls++
	return s.stream, s.err
}

func (s *stubExecutorClient) OpenRunTelemetry(
	_ context.Context,
	req domain.RunRequest,
) (runtimeclient.TelemetryStream, error) {
	if s.callLog != nil {
		*s.callLog = append(*s.callLog, "open_run_telemetry")
	}
	s.gotTelemetryReq = req
	s.telemetryCalls++
	return s.telemetryStream, s.telemetryErr
}

type fakeSessionQueryClient struct{}

func (fakeSessionQueryClient) ListSessions(
	context.Context,
	string,
	int32,
	string,
) ([]domain.SessionSummary, string, error) {
	return nil, "", nil
}

func (fakeSessionQueryClient) GetSession(
	context.Context,
	domain.SessionLocator,
) (domain.SessionSummary, error) {
	return domain.SessionSummary{}, nil
}

func (fakeSessionQueryClient) GetSessionMessagePage(
	context.Context,
	domain.SessionMessageQuery,
) (domain.SessionMessagePage, error) {
	return domain.SessionMessagePage{}, nil
}

func (fakeSessionQueryClient) GetSessionMessages(
	context.Context,
	domain.SessionMessageQuery,
) ([]domain.SessionMessage, string, error) {
	return nil, "", nil
}

func (fakeSessionQueryClient) GetLatestSession(
	context.Context,
	string,
) (domain.SessionSummary, error) {
	return domain.SessionSummary{}, nil
}

func (fakeSessionQueryClient) DeleteSession(context.Context, domain.SessionLocator) error {
	return nil
}

func (fakeSessionQueryClient) ListThreadArtifacts(
	context.Context,
	domain.ListArtifactsRequest,
) (domain.ListArtifactsResponse, error) {
	return domain.ListArtifactsResponse{}, nil
}

type stubSessionQueryClient struct {
	listSessionsResp      []domain.SessionSummary
	listSessionsToken     string
	listSessionsErr       error
	listSessionsAgentName string
	listSessionsPageSize  int32
	listSessionsPageToken string

	getSessionResp    domain.SessionSummary
	getSessionErr     error
	getSessionLocator domain.SessionLocator

	getPageResp  domain.SessionMessagePage
	getPageErr   error
	getPageQuery domain.SessionMessageQuery

	getMessagesResp  []domain.SessionMessage
	getMessagesToken string
	getMessagesErr   error
	getMessagesQuery domain.SessionMessageQuery

	getLatestResp      domain.SessionSummary
	getLatestErr       error
	getLatestAgentName string

	deleteSessionErr     error
	deleteSessionLocator domain.SessionLocator
}

func (s *stubSessionQueryClient) ListSessions(
	_ context.Context,
	agentName string,
	pageSize int32,
	pageToken string,
) ([]domain.SessionSummary, string, error) {
	s.listSessionsAgentName = agentName
	s.listSessionsPageSize = pageSize
	s.listSessionsPageToken = pageToken
	return s.listSessionsResp, s.listSessionsToken, s.listSessionsErr
}

func (s *stubSessionQueryClient) GetSession(
	_ context.Context,
	locator domain.SessionLocator,
) (domain.SessionSummary, error) {
	s.getSessionLocator = locator
	return s.getSessionResp, s.getSessionErr
}

func (s *stubSessionQueryClient) GetSessionMessagePage(
	_ context.Context,
	query domain.SessionMessageQuery,
) (domain.SessionMessagePage, error) {
	s.getPageQuery = query
	return s.getPageResp, s.getPageErr
}

func (s *stubSessionQueryClient) GetSessionMessages(
	_ context.Context,
	query domain.SessionMessageQuery,
) ([]domain.SessionMessage, string, error) {
	s.getMessagesQuery = query
	return s.getMessagesResp, s.getMessagesToken, s.getMessagesErr
}

func (s *stubSessionQueryClient) GetLatestSession(
	_ context.Context,
	agentName string,
) (domain.SessionSummary, error) {
	s.getLatestAgentName = agentName
	return s.getLatestResp, s.getLatestErr
}

func (s *stubSessionQueryClient) DeleteSession(
	_ context.Context,
	locator domain.SessionLocator,
) error {
	s.deleteSessionLocator = locator
	return s.deleteSessionErr
}

func (s *stubSessionQueryClient) ListThreadArtifacts(
	context.Context,
	domain.ListArtifactsRequest,
) (domain.ListArtifactsResponse, error) {
	return domain.ListArtifactsResponse{}, nil
}

func testResolvedAgentInput(agentName string) domain.ResolvedAgentInput {
	return domain.ResolvedAgentInput{
		Agent: domain.AuthoredAgentSpec{
			Name:     agentName,
			ModelRef: "default-openai",
		},
		ModelConfig: domain.ModelConfig{
			Name: "default-openai",
			Spec: domain.ModelSpec{
				Provider: "openai",
				Model:    "gpt-5",
			},
		},
	}
}

func testRuntimeAgentSpec(agentName string) domain.RuntimeAgentSpec {
	return domain.RuntimeAgentSpec{
		Name: agentName,
		Model: domain.ModelSpec{
			Provider: "openai",
			Model:    "gpt-5",
		},
	}
}

func TestNewServiceRejectsMissingResolver(t *testing.T) {
	_, err := NewService(Dependencies{})
	if err == nil {
		t.Fatal("expected constructor to reject missing dependencies")
	}
}

func TestNewServiceAcceptsCompleteDependencies(t *testing.T) {
	service, err := NewService(Dependencies{
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("expected constructor success: %v", err)
	}
	if service == nil {
		t.Fatal("expected service instance")
	}
}

func TestEnsureRunnableSyncsAndAssemblesAgent(t *testing.T) {
	callLog := []string{}
	resolved := testResolvedAgentInput("demo-agent")
	packaged := testRuntimeAgentSpec("demo-agent")

	packager := &fakePackager{
		result:  packaged,
		callLog: &callLog,
	}
	resourceSync := &fakeResourceSyncClient{
		syncResp:     runtimeclient.SyncResponse{OK: true},
		assembleResp: runtimeclient.AssembleResponse{OK: true, Status: "compiled"},
		callLog:      &callLog,
	}

	service, err := NewService(Dependencies{
		Resolver: &fakeResolver{
			result:  resolved,
			callLog: &callLog,
		},
		Packager:     packager,
		ResourceSync: resourceSync,
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	if err := service.EnsureRunnable(context.Background(), "demo-agent"); err != nil {
		t.Fatalf("ensure runnable: %v", err)
	}

	if !packager.receivedInput || packager.gotInput.Agent.Name != "demo-agent" {
		t.Fatalf("unexpected packager input: %#v", packager.gotInput)
	}
	if resourceSync.syncedSpec.Name != "demo-agent" {
		t.Fatalf("unexpected synced spec: %#v", resourceSync.syncedSpec)
	}
	if resourceSync.assembledAgent != "demo-agent" {
		t.Fatalf("unexpected assembled agent: %s", resourceSync.assembledAgent)
	}

	wantOrder := []string{"resolve", "package", "sync", "assemble"}
	if len(callLog) != len(wantOrder) {
		t.Fatalf("unexpected call count: %#v", callLog)
	}
	for index, want := range wantOrder {
		if callLog[index] != want {
			t.Fatalf("unexpected call order: %#v", callLog)
		}
	}
}

func TestEnsureRunnableReturnsSyncFailure(t *testing.T) {
	service, err := NewService(Dependencies{
		Resolver: &fakeResolver{
			result: testResolvedAgentInput("demo-agent"),
		},
		Packager: &fakePackager{
			result: testRuntimeAgentSpec("demo-agent"),
		},
		ResourceSync: &fakeResourceSyncClient{
			syncResp: runtimeclient.SyncResponse{
				OK:      false,
				Message: "validation failed",
			},
		},
		Executor:  fakeExecutorClient{},
		Telemetry: fakeExecutorClient{},
		Sessions:  fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	if err := service.EnsureRunnable(context.Background(), "demo-agent"); err == nil {
		t.Fatal("expected sync failure")
	}
}

func TestEnsureRunnableReturnsAssembleFailure(t *testing.T) {
	service, err := NewService(Dependencies{
		Resolver: &fakeResolver{
			result: testResolvedAgentInput("demo-agent"),
		},
		Packager: &fakePackager{
			result: testRuntimeAgentSpec("demo-agent"),
		},
		ResourceSync: &fakeResourceSyncClient{
			syncResp: runtimeclient.SyncResponse{OK: true},
			assembleResp: runtimeclient.AssembleResponse{
				OK:      false,
				Message: "compile failed",
				Status:  "degraded",
			},
		},
		Executor:  fakeExecutorClient{},
		Telemetry: fakeExecutorClient{},
		Sessions:  fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	if err := service.EnsureRunnable(context.Background(), "demo-agent"); err == nil {
		t.Fatal("expected assemble failure")
	}
}

func TestRunAgentEnsuresRunnableBeforeOpeningStream(t *testing.T) {
	callLog := []string{}
	resolver := &fakeResolver{
		result:  testResolvedAgentInput("demo-agent"),
		callLog: &callLog,
	}
	packager := &fakePackager{
		result:  testRuntimeAgentSpec("demo-agent"),
		callLog: &callLog,
	}
	resourceSync := &fakeResourceSyncClient{
		syncResp:     runtimeclient.SyncResponse{OK: true},
		assembleResp: runtimeclient.AssembleResponse{OK: true, Status: "compiled"},
		callLog:      &callLog,
	}
	wantStream := newStubRunStream()
	executor := &stubExecutorClient{
		stream:  wantStream,
		callLog: &callLog,
	}

	service, err := NewService(Dependencies{
		Resolver:     resolver,
		Packager:     packager,
		ResourceSync: resourceSync,
		Executor:     executor,
		Telemetry:    executor,
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	stream, err := service.RunAgent(context.Background(), domain.RunRequest{
		AgentName: " demo-agent ",
		Message:   "hello",
		ThreadID:  "thread-1",
	})
	if err != nil {
		t.Fatalf("RunAgent: %v", err)
	}
	if stream != wantStream {
		t.Fatalf("unexpected stream: %#v", stream)
	}
	if resolver.gotAgentName != "demo-agent" {
		t.Fatalf("unexpected resolver input: agent=%q", resolver.gotAgentName)
	}
	if executor.gotReq.AgentName != "demo-agent" || executor.gotReq.Message != "hello" || executor.gotReq.ThreadID != "thread-1" {
		t.Fatalf("unexpected run request: %#v", executor.gotReq)
	}

	wantOrder := []string{"resolve", "package", "sync", "assemble", "open_run"}
	if len(callLog) != len(wantOrder) {
		t.Fatalf("unexpected call count: %#v", callLog)
	}
	for index, want := range wantOrder {
		if callLog[index] != want {
			t.Fatalf("unexpected call order: %#v", callLog)
		}
	}
}

func TestRunAgentTelemetryEnsuresRunnableBeforeOpeningStream(t *testing.T) {
	callLog := []string{}
	resolver := &fakeResolver{
		result:  testResolvedAgentInput("demo-agent"),
		callLog: &callLog,
	}
	packager := &fakePackager{
		result:  testRuntimeAgentSpec("demo-agent"),
		callLog: &callLog,
	}
	resourceSync := &fakeResourceSyncClient{
		syncResp:     runtimeclient.SyncResponse{OK: true},
		assembleResp: runtimeclient.AssembleResponse{OK: true, Status: "compiled"},
		callLog:      &callLog,
	}
	wantStream := newStubTelemetryStream()
	executor := &stubExecutorClient{
		telemetryStream: wantStream,
		callLog:         &callLog,
	}

	service, err := NewService(Dependencies{
		Resolver:     resolver,
		Packager:     packager,
		ResourceSync: resourceSync,
		Executor:     executor,
		Telemetry:    executor,
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	stream, err := service.RunAgentTelemetry(context.Background(), domain.RunRequest{
		AgentName: " demo-agent ",
		Message:   "hello telemetry",
		ThreadID:  "thread-telemetry-1",
	})
	if err != nil {
		t.Fatalf("RunAgentTelemetry: %v", err)
	}
	if stream != wantStream {
		t.Fatalf("unexpected telemetry stream: %#v", stream)
	}
	if executor.gotTelemetryReq.AgentName != "demo-agent" ||
		executor.gotTelemetryReq.Message != "hello telemetry" ||
		executor.gotTelemetryReq.ThreadID != "thread-telemetry-1" {
		t.Fatalf("unexpected telemetry run request: %#v", executor.gotTelemetryReq)
	}

	wantOrder := []string{"resolve", "package", "sync", "assemble", "open_run_telemetry"}
	if len(callLog) != len(wantOrder) {
		t.Fatalf("unexpected call count: %#v", callLog)
	}
	for index, want := range wantOrder {
		if callLog[index] != want {
			t.Fatalf("unexpected call order: %#v", callLog)
		}
	}
}

func TestGetAgentGraphEnsuresRunnableBeforeDelegating(t *testing.T) {
	callLog := []string{}
	resolver := &fakeResolver{
		result:  testResolvedAgentInput("demo-agent"),
		callLog: &callLog,
	}
	packager := &fakePackager{
		result:  testRuntimeAgentSpec("demo-agent"),
		callLog: &callLog,
	}
	resourceSync := &fakeResourceSyncClient{
		syncResp:     runtimeclient.SyncResponse{OK: true},
		assembleResp: runtimeclient.AssembleResponse{OK: true, Status: "compiled"},
		graphResp:    []byte(`{"nodes":[{"id":"model"}],"edges":[]}`),
		callLog:      &callLog,
	}
	executor := &stubExecutorClient{}

	service, err := NewService(Dependencies{
		Resolver:     resolver,
		Packager:     packager,
		ResourceSync: resourceSync,
		Executor:     executor,
		Telemetry:    executor,
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	graph, err := service.GetAgentGraph(context.Background(), " demo-agent ", 2)
	if err != nil {
		t.Fatalf("GetAgentGraph: %v", err)
	}
	if string(graph) != `{"nodes":[{"id":"model"}],"edges":[]}` {
		t.Fatalf("unexpected graph response: %s", string(graph))
	}
	if resourceSync.graphAgentName != "demo-agent" || resourceSync.graphXrayDepth != 2 {
		t.Fatalf("unexpected graph request: agent=%q depth=%d", resourceSync.graphAgentName, resourceSync.graphXrayDepth)
	}

	wantOrder := []string{"resolve", "package", "sync", "assemble"}
	if len(callLog) != len(wantOrder) {
		t.Fatalf("unexpected call count: %#v", callLog)
	}
	for index, want := range wantOrder {
		if callLog[index] != want {
			t.Fatalf("unexpected call order: %#v", callLog)
		}
	}
}

func TestUploadWorkspaceFilesEnsuresRunnableBeforeDelegating(t *testing.T) {
	callLog := []string{}
	resolver := &fakeResolver{
		result:  testResolvedAgentInput("demo-agent"),
		callLog: &callLog,
	}
	packager := &fakePackager{
		result:  testRuntimeAgentSpec("demo-agent"),
		callLog: &callLog,
	}
	resourceSync := &fakeResourceSyncClient{
		syncResp:     runtimeclient.SyncResponse{OK: true},
		assembleResp: runtimeclient.AssembleResponse{OK: true, Status: "compiled"},
		uploadResp: domain.WorkspaceUploadResponse{
			ThreadID: "thread-1",
			Files: []domain.WorkspaceUploadResult{
				{Path: "report.txt"},
			},
		},
		callLog: &callLog,
	}

	service, err := NewService(Dependencies{
		Resolver:     resolver,
		Packager:     packager,
		ResourceSync: resourceSync,
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	resp, err := service.UploadWorkspaceFiles(
		context.Background(),
		domain.WorkspaceUploadRequest{
			AgentName: " demo-agent ",
			ThreadID:  "thread-1",
			Files: []domain.WorkspaceUploadFile{
				{Path: "report.txt", Content: []byte("hello")},
			},
		},
	)
	if err != nil {
		t.Fatalf("UploadWorkspaceFiles: %v", err)
	}
	if resp.ThreadID != "thread-1" || len(resp.Files) != 1 {
		t.Fatalf("unexpected upload response: %#v", resp)
	}
	if resourceSync.uploadReq.AgentName != "demo-agent" || resourceSync.uploadReq.ThreadID != "thread-1" {
		t.Fatalf("unexpected upload request: %#v", resourceSync.uploadReq)
	}

	wantOrder := []string{"resolve", "package", "sync", "assemble"}
	if len(callLog) != len(wantOrder) {
		t.Fatalf("unexpected call count: %#v", callLog)
	}
	for index, want := range wantOrder {
		if callLog[index] != want {
			t.Fatalf("unexpected call order: %#v", callLog)
		}
	}
}

func TestDownloadWorkspaceFilesEnsuresRunnableBeforeDelegating(t *testing.T) {
	callLog := []string{}
	resolver := &fakeResolver{
		result:  testResolvedAgentInput("demo-agent"),
		callLog: &callLog,
	}
	packager := &fakePackager{
		result:  testRuntimeAgentSpec("demo-agent"),
		callLog: &callLog,
	}
	resourceSync := &fakeResourceSyncClient{
		syncResp:     runtimeclient.SyncResponse{OK: true},
		assembleResp: runtimeclient.AssembleResponse{OK: true, Status: "compiled"},
		downloadResp: domain.WorkspaceDownloadResponse{
			ThreadID: "thread-1",
			Files: []domain.WorkspaceDownloadResult{
				{Path: "report.txt", Content: []byte("hello")},
			},
		},
		callLog: &callLog,
	}

	service, err := NewService(Dependencies{
		Resolver:     resolver,
		Packager:     packager,
		ResourceSync: resourceSync,
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	resp, err := service.DownloadWorkspaceFiles(
		context.Background(),
		domain.WorkspaceDownloadRequest{
			AgentName: " demo-agent ",
			ThreadID:  "thread-1",
			Paths:     []string{"report.txt"},
		},
	)
	if err != nil {
		t.Fatalf("DownloadWorkspaceFiles: %v", err)
	}
	if resp.ThreadID != "thread-1" || len(resp.Files) != 1 {
		t.Fatalf("unexpected download response: %#v", resp)
	}
	if resourceSync.downloadReq.AgentName != "demo-agent" || resourceSync.downloadReq.ThreadID != "thread-1" {
		t.Fatalf("unexpected download request: %#v", resourceSync.downloadReq)
	}

	wantOrder := []string{"resolve", "package", "sync", "assemble"}
	if len(callLog) != len(wantOrder) {
		t.Fatalf("unexpected call count: %#v", callLog)
	}
	for index, want := range wantOrder {
		if callLog[index] != want {
			t.Fatalf("unexpected call order: %#v", callLog)
		}
	}
}

func TestListWorkspaceFilesEnsuresRunnableBeforeDelegating(t *testing.T) {
	callLog := []string{}
	resolver := &fakeResolver{
		result:  testResolvedAgentInput("demo-agent"),
		callLog: &callLog,
	}
	packager := &fakePackager{
		result:  testRuntimeAgentSpec("demo-agent"),
		callLog: &callLog,
	}
	resourceSync := &fakeResourceSyncClient{
		syncResp:     runtimeclient.SyncResponse{OK: true},
		assembleResp: runtimeclient.AssembleResponse{OK: true, Status: "compiled"},
		listResp: domain.WorkspaceListResponse{
			ThreadID: "thread-1",
			Files: []domain.WorkspaceFileInfo{
				{Path: "report.txt", IsDir: false, Size: 5},
			},
		},
		callLog: &callLog,
	}

	service, err := NewService(Dependencies{
		Resolver:     resolver,
		Packager:     packager,
		ResourceSync: resourceSync,
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	resp, err := service.ListWorkspaceFiles(
		context.Background(),
		domain.WorkspaceListRequest{
			AgentName: " demo-agent ",
			ThreadID:  "thread-1",
			Path:      ".",
		},
	)
	if err != nil {
		t.Fatalf("ListWorkspaceFiles: %v", err)
	}
	if resp.ThreadID != "thread-1" || len(resp.Files) != 1 {
		t.Fatalf("unexpected list response: %#v", resp)
	}
	if resourceSync.listReq.AgentName != "demo-agent" || resourceSync.listReq.ThreadID != "thread-1" {
		t.Fatalf("unexpected list request: %#v", resourceSync.listReq)
	}

	wantOrder := []string{"resolve", "package", "sync", "assemble"}
	if len(callLog) != len(wantOrder) {
		t.Fatalf("unexpected call count: %#v", callLog)
	}
	for index, want := range wantOrder {
		if callLog[index] != want {
			t.Fatalf("unexpected call order: %#v", callLog)
		}
	}
}

func TestRunAgentReturnsEmptyAgentError(t *testing.T) {
	service, err := NewService(Dependencies{
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     &stubExecutorClient{},
		Telemetry:    &stubExecutorClient{},
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	if _, err := service.RunAgent(context.Background(), domain.RunRequest{AgentName: "   "}); !errors.Is(err, ErrEmptyAgentName) {
		t.Fatalf("expected ErrEmptyAgentName, got %v", err)
	}
}

func TestRunAgentShortCircuitsWhenEnsureRunnableFails(t *testing.T) {
	expectedErr := errors.New("resolve failed")
	executor := &stubExecutorClient{}

	service, err := NewService(Dependencies{
		Resolver: &fakeResolver{
			err: expectedErr,
		},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     executor,
		Telemetry:    executor,
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	if _, err := service.RunAgent(context.Background(), domain.RunRequest{AgentName: "demo-agent"}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected wrapped ensure error, got %v", err)
	}
	if executor.calls != 0 {
		t.Fatalf("expected executor not to be called, got %d", executor.calls)
	}
}

func TestRunAgentWrapsOpenRunError(t *testing.T) {
	expectedErr := errors.New("open run failed")
	executor := &stubExecutorClient{
		err: expectedErr,
	}
	service, err := NewService(Dependencies{
		Resolver: &fakeResolver{
			result: testResolvedAgentInput("demo-agent"),
		},
		Packager: &fakePackager{
			result: testRuntimeAgentSpec("demo-agent"),
		},
		ResourceSync: &fakeResourceSyncClient{
			syncResp:     runtimeclient.SyncResponse{OK: true},
			assembleResp: runtimeclient.AssembleResponse{OK: true},
		},
		Executor:  executor,
		Telemetry: executor,
		Sessions:  fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	if _, err := service.RunAgent(context.Background(), domain.RunRequest{AgentName: "demo-agent"}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected wrapped open-run error, got %v", err)
	}
	if executor.calls != 1 {
		t.Fatalf("expected executor to be called once, got %d", executor.calls)
	}
}

func TestHealthDelegatesToResourceSync(t *testing.T) {
	service, err := NewService(Dependencies{
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{healthResp: runtimeclient.HealthResponse{Ready: true, Status: "ok"}},
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	resp, err := service.Health(context.Background())
	if err != nil {
		t.Fatalf("health: %v", err)
	}
	if !resp.Ready || resp.Status != "ok" {
		t.Fatalf("unexpected health response: %#v", resp)
	}
}

func TestResourceCRUDDelegatesToRegistry(t *testing.T) {
	reg := &stubRegistry{}
	service, err := NewService(Dependencies{
		Registry:     reg,
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	modelConfig, err := service.UpsertModelConfig(context.Background(), domain.ModelConfig{
		Name: "default-openai",
		Spec: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
	})
	if err != nil || modelConfig.Name != "default-openai" {
		t.Fatalf("unexpected upsert model result: %#v err=%v", modelConfig, err)
	}
	if got, err := service.GetModelConfig(context.Background(), "default-openai"); err != nil || got.Name != "default-openai" {
		t.Fatalf("unexpected get model result: %#v err=%v", got, err)
	}
	if list, err := service.ListModelConfigs(context.Background()); err != nil || len(list) != 1 {
		t.Fatalf("unexpected list models result: %#v err=%v", list, err)
	}
	if page, err := service.ListModelConfigsPage(
		context.Background(),
		domain.PageQuery{PageSize: 1, PageNumber: 1},
	); err != nil || len(page.Items) != 1 || page.TotalSize != 1 || page.TotalPages != 1 {
		t.Fatalf("unexpected list model page result: %#v err=%v", page, err)
	}
	if err := service.DeleteModelConfig(context.Background(), "default-openai"); err != nil {
		t.Fatalf("delete model: %v", err)
	}

	skill, err := service.UpsertSkill(context.Background(), domain.Skill{Name: "research", Content: "# SKILL"})
	if err != nil || skill.Name != "research" {
		t.Fatalf("unexpected upsert skill result: %#v err=%v", skill, err)
	}
	if got, err := service.GetSkill(context.Background(), "research"); err != nil || got.Name != "research" {
		t.Fatalf("unexpected get skill result: %#v err=%v", got, err)
	}
	if list, err := service.ListSkills(context.Background()); err != nil || len(list) != 1 {
		t.Fatalf("unexpected list skills result: %#v err=%v", list, err)
	}
	if page, err := service.ListSkillsPage(
		context.Background(),
		domain.PageQuery{PageSize: 1, PageNumber: 1},
	); err != nil || len(page.Items) != 1 || page.TotalSize != 1 || page.TotalPages != 1 {
		t.Fatalf("unexpected list skill page result: %#v err=%v", page, err)
	}
	if err := service.DeleteSkill(context.Background(), "research"); err != nil {
		t.Fatalf("delete skill: %v", err)
	}

	config, err := service.UpsertMCPConfig(context.Background(), domain.MCPConfig{Name: "github", Command: "npx"})
	if err != nil || config.Name != "github" {
		t.Fatalf("unexpected upsert mcp result: %#v err=%v", config, err)
	}
	if got, err := service.GetMCPConfig(context.Background(), "github"); err != nil || got.Name != "github" {
		t.Fatalf("unexpected get mcp result: %#v err=%v", got, err)
	}
	if list, err := service.ListMCPConfigs(context.Background()); err != nil || len(list) != 1 {
		t.Fatalf("unexpected list mcps result: %#v err=%v", list, err)
	}
	if page, err := service.ListMCPConfigsPage(
		context.Background(),
		domain.PageQuery{PageSize: 1, PageNumber: 1},
	); err != nil || len(page.Items) != 1 || page.TotalSize != 1 || page.TotalPages != 1 {
		t.Fatalf("unexpected list mcp page result: %#v err=%v", page, err)
	}
	if err := service.DeleteMCPConfig(context.Background(), "github"); err != nil {
		t.Fatalf("delete mcp: %v", err)
	}

	spec, err := service.UpsertAgentSpec(
		context.Background(),
		domain.AuthoredAgentSpec{Name: "assistant", ModelRef: "default-openai"},
	)
	if err != nil || spec.Name != "assistant" {
		t.Fatalf("unexpected upsert agent result: %#v err=%v", spec, err)
	}
	if got, err := service.GetAgentSpec(context.Background(), "assistant"); err != nil || got.Name != "assistant" {
		t.Fatalf("unexpected get agent result: %#v err=%v", got, err)
	}
	if list, err := service.ListAgentSpecs(context.Background()); err != nil || len(list) != 1 {
		t.Fatalf("unexpected list agents result: %#v err=%v", list, err)
	}
	if page, err := service.ListAgentSpecsPage(
		context.Background(),
		domain.PageQuery{PageSize: 1, PageNumber: 1},
	); err != nil || len(page.Items) != 1 || page.TotalSize != 1 || page.TotalPages != 1 {
		t.Fatalf("unexpected list agent page result: %#v err=%v", page, err)
	}
	if err := service.DeleteAgentSpec(context.Background(), "assistant"); err != nil {
		t.Fatalf("delete agent: %v", err)
	}
}

func TestResourcePageRejectsPageNumberWithoutPageSize(t *testing.T) {
	reg := &stubRegistry{
		models: map[string]domain.ModelConfig{
			"default-openai": {Name: "default-openai"},
		},
	}
	service, err := NewService(Dependencies{
		Registry:     reg,
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	_, err = service.ListModelConfigsPage(context.Background(), domain.PageQuery{PageNumber: 1})
	if !errors.Is(err, registrypkg.ErrInvalid) {
		t.Fatalf("expected invalid pagination error, got %v", err)
	}
}

func TestListSessionsDelegatesToSessionClient(t *testing.T) {
	sessionsClient := &stubSessionQueryClient{
		listSessionsResp:  []domain.SessionSummary{{ThreadID: "thread-1"}},
		listSessionsToken: "page-2",
	}
	service, err := NewService(Dependencies{
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     sessionsClient,
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	sessions, nextPageToken, err := service.ListSessions(context.Background(), "assistant", 20, "page-1")
	if err != nil {
		t.Fatalf("ListSessions: %v", err)
	}
	if len(sessions) != 1 || sessions[0].ThreadID != "thread-1" || nextPageToken != "page-2" {
		t.Fatalf("unexpected list sessions response: %#v %q", sessions, nextPageToken)
	}
	if sessionsClient.listSessionsAgentName != "assistant" ||
		sessionsClient.listSessionsPageSize != 20 ||
		sessionsClient.listSessionsPageToken != "page-1" {
		t.Fatalf("unexpected list sessions inputs: %#v", sessionsClient)
	}
}

func TestGetSessionDelegatesToSessionClient(t *testing.T) {
	sessionsClient := &stubSessionQueryClient{
		getSessionResp: domain.SessionSummary{ThreadID: "thread-1", CheckpointCount: 3},
	}
	service, err := NewService(Dependencies{
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     sessionsClient,
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	session, err := service.GetSession(context.Background(), domain.SessionLocator{
		AgentName: "assistant",
		ThreadID:  "thread-1",
	})
	if err != nil {
		t.Fatalf("GetSession: %v", err)
	}
	if session.ThreadID != "thread-1" || session.CheckpointCount != 3 {
		t.Fatalf("unexpected session: %#v", session)
	}
	if sessionsClient.getSessionLocator != (domain.SessionLocator{AgentName: "assistant", ThreadID: "thread-1"}) {
		t.Fatalf("unexpected get session input: %#v", sessionsClient)
	}
}

func TestGetSessionMessagePageDelegatesToSessionClient(t *testing.T) {
	query := domain.SessionMessageQuery{
		AgentName:    "assistant",
		ThreadID:     "thread-1",
		CheckpointID: "cp-1",
		Mode:         domain.SessionHistoryModeResumeView,
		PageSize:     20,
		PageToken:    "page-1",
		IncludeRaw:   true,
	}
	sessionsClient := &stubSessionQueryClient{
		getPageResp: domain.SessionMessagePage{
			ThreadID:             "thread-1",
			ResolvedCheckpointID: "cp-2",
			ActualMode:           domain.SessionHistoryModeResumeView,
			TotalMessageCount:    2,
			Messages:             []domain.SessionMessage{{Index: 0, Text: "hello"}},
			NextPageToken:        "page-2",
		},
	}
	service, err := NewService(Dependencies{
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     sessionsClient,
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	page, err := service.GetSessionMessagePage(context.Background(), query)
	if err != nil {
		t.Fatalf("GetSessionMessagePage: %v", err)
	}
	if page.ResolvedCheckpointID != "cp-2" || page.TotalMessageCount != 2 {
		t.Fatalf("unexpected page: %#v", page)
	}
	if sessionsClient.getPageQuery != query {
		t.Fatalf("unexpected page query: %#v", sessionsClient.getPageQuery)
	}
}

func TestGetSessionMessagesDelegatesToSessionClient(t *testing.T) {
	sessionsClient := &stubSessionQueryClient{
		getMessagesResp:  []domain.SessionMessage{{Index: 0, Text: "hello"}},
		getMessagesToken: "page-2",
	}
	service, err := NewService(Dependencies{
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     sessionsClient,
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	messages, nextPageToken, err := service.GetSessionMessages(context.Background(), domain.SessionMessageQuery{
		AgentName: "assistant",
		ThreadID:  "thread-1",
		Mode:      domain.SessionHistoryModeResumeView,
		PageSize:  20,
		PageToken: "page-1",
	})
	if err != nil {
		t.Fatalf("GetSessionMessages: %v", err)
	}
	if len(messages) != 1 || messages[0].Text != "hello" || nextPageToken != "page-2" {
		t.Fatalf("unexpected messages: %#v %q", messages, nextPageToken)
	}
	if sessionsClient.getMessagesQuery != (domain.SessionMessageQuery{
		AgentName: "assistant",
		ThreadID:  "thread-1",
		Mode:      domain.SessionHistoryModeResumeView,
		PageSize:  20,
		PageToken: "page-1",
	}) {
		t.Fatalf("unexpected get messages inputs: %#v", sessionsClient)
	}
}

func TestGetLatestSessionDelegatesToSessionClient(t *testing.T) {
	sessionsClient := &stubSessionQueryClient{
		getLatestResp: domain.SessionSummary{ThreadID: "thread-9"},
	}
	service, err := NewService(Dependencies{
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     sessionsClient,
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	session, err := service.GetLatestSession(context.Background(), "assistant")
	if err != nil {
		t.Fatalf("GetLatestSession: %v", err)
	}
	if session.ThreadID != "thread-9" {
		t.Fatalf("unexpected latest session: %#v", session)
	}
	if sessionsClient.getLatestAgentName != "assistant" {
		t.Fatalf("unexpected latest session input: %#v", sessionsClient)
	}
}

func TestDeleteSessionDelegatesToSessionClient(t *testing.T) {
	sessionsClient := &stubSessionQueryClient{}
	service, err := NewService(Dependencies{
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     fakeExecutorClient{},
		Telemetry:    fakeExecutorClient{},
		Sessions:     sessionsClient,
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	if err := service.DeleteSession(context.Background(), domain.SessionLocator{
		AgentName: "assistant",
		ThreadID:  "thread-1",
	}); err != nil {
		t.Fatalf("DeleteSession: %v", err)
	}
	if sessionsClient.deleteSessionLocator != (domain.SessionLocator{AgentName: "assistant", ThreadID: "thread-1"}) {
		t.Fatalf("unexpected delete session input: %#v", sessionsClient)
	}
}
