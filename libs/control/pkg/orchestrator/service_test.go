package orchestrator

import (
	"agentctl/pkg/domain"
	registrypkg "agentctl/pkg/registry"
	"agentctl/pkg/runtimeclient"
	"context"
	"errors"
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
	skills map[string]domain.Skill
	mcps   map[string]domain.MCPConfig
	agents map[string]domain.AuthoredAgentSpec
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

func (s *stubRegistry) ListSkills(context.Context) ([]domain.Skill, error) {
	skills := make([]domain.Skill, 0, len(s.skills))
	for _, skill := range s.skills {
		skills = append(skills, skill)
	}
	return skills, nil
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

func (s *stubRegistry) ListMCPConfigs(context.Context) ([]domain.MCPConfig, error) {
	configs := make([]domain.MCPConfig, 0, len(s.mcps))
	for _, config := range s.mcps {
		configs = append(configs, config)
	}
	return configs, nil
}

func (s *stubRegistry) DeleteMCPConfig(_ context.Context, name string) error {
	delete(s.mcps, name)
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

func (s *stubRegistry) ListAgentSpecs(context.Context) ([]domain.AuthoredAgentSpec, error) {
	specs := make([]domain.AuthoredAgentSpec, 0, len(s.agents))
	for _, spec := range s.agents {
		specs = append(specs, spec)
	}
	return specs, nil
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
	healthResp     runtimeclient.HealthResponse
	healthErr      error
	syncedSpec     domain.RuntimeAgentSpec
	assembledAgent string
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

func (f *fakeResourceSyncClient) RemoveAgent(
	context.Context,
	string,
) (runtimeclient.SyncResponse, error) {
	return runtimeclient.SyncResponse{}, nil
}

func (f *fakeResourceSyncClient) Health(context.Context) (runtimeclient.HealthResponse, error) {
	return f.healthResp, f.healthErr
}

type fakeExecutorClient struct{}

func (fakeExecutorClient) OpenRun(context.Context, domain.RunRequest) (runtimeclient.RunStream, error) {
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

type stubExecutorClient struct {
	stream  runtimeclient.RunStream
	err     error
	gotReq  domain.RunRequest
	calls   int
	callLog *[]string
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

type fakeSessionQueryClient struct{}

func (fakeSessionQueryClient) ListSessions(
	context.Context,
	string,
	int32,
	string,
) ([]domain.SessionSummary, string, error) {
	return nil, "", nil
}

func (fakeSessionQueryClient) GetSession(context.Context, string) (domain.SessionSummary, error) {
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
	string,
	domain.SessionHistoryMode,
	int32,
	string,
) ([]domain.SessionMessage, string, error) {
	return nil, "", nil
}

func (fakeSessionQueryClient) GetLatestSession(
	context.Context,
	string,
) (domain.SessionSummary, error) {
	return domain.SessionSummary{}, nil
}

func (fakeSessionQueryClient) DeleteSession(context.Context, string) error {
	return nil
}

type stubSessionQueryClient struct {
	listSessionsResp      []domain.SessionSummary
	listSessionsToken     string
	listSessionsErr       error
	listSessionsAgentName string
	listSessionsPageSize  int32
	listSessionsPageToken string

	getSessionResp     domain.SessionSummary
	getSessionErr      error
	getSessionThreadID string

	getPageResp  domain.SessionMessagePage
	getPageErr   error
	getPageQuery domain.SessionMessageQuery

	getMessagesResp      []domain.SessionMessage
	getMessagesToken     string
	getMessagesErr       error
	getMessagesThreadID  string
	getMessagesMode      domain.SessionHistoryMode
	getMessagesPageSize  int32
	getMessagesPageToken string

	getLatestResp      domain.SessionSummary
	getLatestErr       error
	getLatestAgentName string

	deleteSessionErr      error
	deleteSessionThreadID string
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

func (s *stubSessionQueryClient) GetSession(_ context.Context, threadID string) (domain.SessionSummary, error) {
	s.getSessionThreadID = threadID
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
	threadID string,
	mode domain.SessionHistoryMode,
	pageSize int32,
	pageToken string,
) ([]domain.SessionMessage, string, error) {
	s.getMessagesThreadID = threadID
	s.getMessagesMode = mode
	s.getMessagesPageSize = pageSize
	s.getMessagesPageToken = pageToken
	return s.getMessagesResp, s.getMessagesToken, s.getMessagesErr
}

func (s *stubSessionQueryClient) GetLatestSession(
	_ context.Context,
	agentName string,
) (domain.SessionSummary, error) {
	s.getLatestAgentName = agentName
	return s.getLatestResp, s.getLatestErr
}

func (s *stubSessionQueryClient) DeleteSession(_ context.Context, threadID string) error {
	s.deleteSessionThreadID = threadID
	return s.deleteSessionErr
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
	resolved := domain.ResolvedAgentInput{
		Agent: domain.AuthoredAgentSpec{
			Name:  "demo-agent",
			Model: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
		},
	}
	packaged := domain.RuntimeAgentSpec{
		Name:  "demo-agent",
		Model: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
	}

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
			result: domain.ResolvedAgentInput{
				Agent: domain.AuthoredAgentSpec{
					Name:  "demo-agent",
					Model: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
				},
			},
		},
		Packager: &fakePackager{
			result: domain.RuntimeAgentSpec{
				Name:  "demo-agent",
				Model: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
			},
		},
		ResourceSync: &fakeResourceSyncClient{
			syncResp: runtimeclient.SyncResponse{
				OK:      false,
				Message: "validation failed",
			},
		},
		Executor: fakeExecutorClient{},
		Sessions: fakeSessionQueryClient{},
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
			result: domain.ResolvedAgentInput{
				Agent: domain.AuthoredAgentSpec{
					Name:  "demo-agent",
					Model: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
				},
			},
		},
		Packager: &fakePackager{
			result: domain.RuntimeAgentSpec{
				Name:  "demo-agent",
				Model: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
			},
		},
		ResourceSync: &fakeResourceSyncClient{
			syncResp: runtimeclient.SyncResponse{OK: true},
			assembleResp: runtimeclient.AssembleResponse{
				OK:      false,
				Message: "compile failed",
				Status:  "degraded",
			},
		},
		Executor: fakeExecutorClient{},
		Sessions: fakeSessionQueryClient{},
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
		result: domain.ResolvedAgentInput{
			Agent: domain.AuthoredAgentSpec{
				Name:  "demo-agent",
				Model: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
			},
		},
		callLog: &callLog,
	}
	packager := &fakePackager{
		result: domain.RuntimeAgentSpec{
			Name:  "demo-agent",
			Model: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
		},
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

func TestRunAgentReturnsEmptyAgentError(t *testing.T) {
	service, err := NewService(Dependencies{
		Resolver:     &fakeResolver{},
		Packager:     &fakePackager{},
		ResourceSync: &fakeResourceSyncClient{},
		Executor:     &stubExecutorClient{},
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
			result: domain.ResolvedAgentInput{
				Agent: domain.AuthoredAgentSpec{
					Name:  "demo-agent",
					Model: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
				},
			},
		},
		Packager: &fakePackager{
			result: domain.RuntimeAgentSpec{
				Name:  "demo-agent",
				Model: domain.ModelSpec{Provider: "openai", Model: "gpt-5"},
			},
		},
		ResourceSync: &fakeResourceSyncClient{
			syncResp:     runtimeclient.SyncResponse{OK: true},
			assembleResp: runtimeclient.AssembleResponse{OK: true},
		},
		Executor: executor,
		Sessions: fakeSessionQueryClient{},
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
		Sessions:     fakeSessionQueryClient{},
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
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
	if err := service.DeleteMCPConfig(context.Background(), "github"); err != nil {
		t.Fatalf("delete mcp: %v", err)
	}

	spec, err := service.UpsertAgentSpec(
		context.Background(),
		domain.AuthoredAgentSpec{Name: "assistant", Model: domain.ModelSpec{Provider: "openai", Model: "gpt-4o"}},
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
	if err := service.DeleteAgentSpec(context.Background(), "assistant"); err != nil {
		t.Fatalf("delete agent: %v", err)
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
		Sessions:     sessionsClient,
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	session, err := service.GetSession(context.Background(), "thread-1")
	if err != nil {
		t.Fatalf("GetSession: %v", err)
	}
	if session.ThreadID != "thread-1" || session.CheckpointCount != 3 {
		t.Fatalf("unexpected session: %#v", session)
	}
	if sessionsClient.getSessionThreadID != "thread-1" {
		t.Fatalf("unexpected get session input: %#v", sessionsClient)
	}
}

func TestGetSessionMessagePageDelegatesToSessionClient(t *testing.T) {
	query := domain.SessionMessageQuery{
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
		Sessions:     sessionsClient,
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	messages, nextPageToken, err := service.GetSessionMessages(
		context.Background(),
		"thread-1",
		domain.SessionHistoryModeResumeView,
		20,
		"page-1",
	)
	if err != nil {
		t.Fatalf("GetSessionMessages: %v", err)
	}
	if len(messages) != 1 || messages[0].Text != "hello" || nextPageToken != "page-2" {
		t.Fatalf("unexpected messages: %#v %q", messages, nextPageToken)
	}
	if sessionsClient.getMessagesThreadID != "thread-1" ||
		sessionsClient.getMessagesMode != domain.SessionHistoryModeResumeView ||
		sessionsClient.getMessagesPageSize != 20 ||
		sessionsClient.getMessagesPageToken != "page-1" {
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
		Sessions:     sessionsClient,
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}

	if err := service.DeleteSession(context.Background(), "thread-1"); err != nil {
		t.Fatalf("DeleteSession: %v", err)
	}
	if sessionsClient.deleteSessionThreadID != "thread-1" {
		t.Fatalf("unexpected delete session input: %#v", sessionsClient)
	}
}
