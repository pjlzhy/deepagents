package api

import (
	"context"
	"errors"
	"testing"

	"agentctl/pkg/domain"
	"agentctl/pkg/runtimeclient"
)

type fakeAgentService struct {
	ensureRunnableErr error
	ensureAgent       string

	runStream  runtimeclient.RunStream
	runErr     error
	runRequest domain.RunRequest

	healthResp runtimeclient.HealthResponse
	healthErr  error

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

	deleteErr      error
	deleteThreadID string

	upsertSkillResp domain.Skill
	upsertSkillErr  error
	upsertSkillReq  domain.Skill
	getSkillResp    domain.Skill
	getSkillErr     error
	getSkillName    string
	listSkillsResp  []domain.Skill
	listSkillsErr   error
	deleteSkillErr  error
	deleteSkillName string

	upsertMCPResp domain.MCPConfig
	upsertMCPErr  error
	upsertMCPReq  domain.MCPConfig
	getMCPResp    domain.MCPConfig
	getMCPErr     error
	getMCPName    string
	listMCPsResp  []domain.MCPConfig
	listMCPsErr   error
	deleteMCPErr  error
	deleteMCPName string

	upsertAgentResp domain.AuthoredAgentSpec
	upsertAgentErr  error
	upsertAgentReq  domain.AuthoredAgentSpec
	getAgentResp    domain.AuthoredAgentSpec
	getAgentErr     error
	getAgentName    string
	listAgentsResp  []domain.AuthoredAgentSpec
	listAgentsErr   error
	deleteAgentErr  error
	deleteAgentName string
}

func (f *fakeAgentService) EnsureRunnable(_ context.Context, agentName string) error {
	f.ensureAgent = agentName
	return f.ensureRunnableErr
}

func (f *fakeAgentService) RunAgent(_ context.Context, req domain.RunRequest) (runtimeclient.RunStream, error) {
	f.runRequest = req
	return f.runStream, f.runErr
}

func (f *fakeAgentService) Health(context.Context) (runtimeclient.HealthResponse, error) {
	return f.healthResp, f.healthErr
}

func (f *fakeAgentService) ListSessions(
	_ context.Context,
	agentName string,
	pageSize int32,
	pageToken string,
) ([]domain.SessionSummary, string, error) {
	f.listSessionsAgentName = agentName
	f.listSessionsPageSize = pageSize
	f.listSessionsPageToken = pageToken
	return f.listSessionsResp, f.listSessionsToken, f.listSessionsErr
}

func (f *fakeAgentService) GetSession(_ context.Context, threadID string) (domain.SessionSummary, error) {
	f.getSessionThreadID = threadID
	return f.getSessionResp, f.getSessionErr
}

func (f *fakeAgentService) GetSessionMessagePage(
	_ context.Context,
	query domain.SessionMessageQuery,
) (domain.SessionMessagePage, error) {
	f.getPageQuery = query
	return f.getPageResp, f.getPageErr
}

func (f *fakeAgentService) GetSessionMessages(
	_ context.Context,
	threadID string,
	mode domain.SessionHistoryMode,
	pageSize int32,
	pageToken string,
) ([]domain.SessionMessage, string, error) {
	f.getMessagesThreadID = threadID
	f.getMessagesMode = mode
	f.getMessagesPageSize = pageSize
	f.getMessagesPageToken = pageToken
	return f.getMessagesResp, f.getMessagesToken, f.getMessagesErr
}

func (f *fakeAgentService) GetLatestSession(_ context.Context, agentName string) (domain.SessionSummary, error) {
	f.getLatestAgentName = agentName
	return f.getLatestResp, f.getLatestErr
}

func (f *fakeAgentService) DeleteSession(_ context.Context, threadID string) error {
	f.deleteThreadID = threadID
	return f.deleteErr
}

func (f *fakeAgentService) UpsertSkill(_ context.Context, skill domain.Skill) (domain.Skill, error) {
	f.upsertSkillReq = skill
	return f.upsertSkillResp, f.upsertSkillErr
}

func (f *fakeAgentService) GetSkill(_ context.Context, name string) (domain.Skill, error) {
	f.getSkillName = name
	return f.getSkillResp, f.getSkillErr
}

func (f *fakeAgentService) ListSkills(context.Context) ([]domain.Skill, error) {
	return f.listSkillsResp, f.listSkillsErr
}

func (f *fakeAgentService) DeleteSkill(_ context.Context, name string) error {
	f.deleteSkillName = name
	return f.deleteSkillErr
}

func (f *fakeAgentService) UpsertMCPConfig(
	_ context.Context,
	config domain.MCPConfig,
) (domain.MCPConfig, error) {
	f.upsertMCPReq = config
	return f.upsertMCPResp, f.upsertMCPErr
}

func (f *fakeAgentService) GetMCPConfig(_ context.Context, name string) (domain.MCPConfig, error) {
	f.getMCPName = name
	return f.getMCPResp, f.getMCPErr
}

func (f *fakeAgentService) ListMCPConfigs(context.Context) ([]domain.MCPConfig, error) {
	return f.listMCPsResp, f.listMCPsErr
}

func (f *fakeAgentService) DeleteMCPConfig(_ context.Context, name string) error {
	f.deleteMCPName = name
	return f.deleteMCPErr
}

func (f *fakeAgentService) UpsertAgentSpec(
	_ context.Context,
	spec domain.AuthoredAgentSpec,
) (domain.AuthoredAgentSpec, error) {
	f.upsertAgentReq = spec
	return f.upsertAgentResp, f.upsertAgentErr
}

func (f *fakeAgentService) GetAgentSpec(_ context.Context, name string) (domain.AuthoredAgentSpec, error) {
	f.getAgentName = name
	return f.getAgentResp, f.getAgentErr
}

func (f *fakeAgentService) ListAgentSpecs(context.Context) ([]domain.AuthoredAgentSpec, error) {
	return f.listAgentsResp, f.listAgentsErr
}

func (f *fakeAgentService) DeleteAgentSpec(_ context.Context, name string) error {
	f.deleteAgentName = name
	return f.deleteAgentErr
}

type stubRunStream struct{}

func (stubRunStream) Events() <-chan runtimeclient.AgentEvent { return nil }
func (stubRunStream) SendHITLDecision(context.Context, string, []runtimeclient.ToolDecision) error {
	return nil
}
func (stubRunStream) SendCancel(context.Context, string) error { return nil }
func (stubRunStream) Close() error                             { return nil }

func TestNewServerRejectsNilService(t *testing.T) {
	if _, err := NewServer(nil); err == nil {
		t.Fatal("expected nil service rejection")
	}
}

func TestServerDelegatesLifecycleAndHealth(t *testing.T) {
	service := &fakeAgentService{
		runStream:  stubRunStream{},
		healthResp: runtimeclient.HealthResponse{Ready: true, Status: "ok"},
	}
	server, err := NewServer(service)
	if err != nil {
		t.Fatalf("NewServer: %v", err)
	}

	if err := server.EnsureRunnable(context.Background(), "assistant"); err != nil {
		t.Fatalf("EnsureRunnable: %v", err)
	}
	if service.ensureAgent != "assistant" {
		t.Fatalf("unexpected ensure inputs: %#v", service)
	}

	stream, err := server.RunAgent(context.Background(), domain.RunRequest{
		AgentName: "assistant",
		Message:   "hello",
	})
	if err != nil {
		t.Fatalf("RunAgent: %v", err)
	}
	if stream == nil {
		t.Fatal("expected run stream")
	}
	if service.runRequest.AgentName != "assistant" {
		t.Fatalf("unexpected run inputs: %#v", service)
	}

	health, err := server.Health(context.Background())
	if err != nil {
		t.Fatalf("Health: %v", err)
	}
	if !health.Ready || health.Status != "ok" {
		t.Fatalf("unexpected health response: %#v", health)
	}
}

func TestServerDelegatesSessionQueries(t *testing.T) {
	pageQuery := domain.SessionMessageQuery{
		ThreadID:   "thread-1",
		PageSize:   20,
		PageToken:  "page-1",
		Mode:       domain.SessionHistoryModeResumeView,
		IncludeRaw: true,
	}
	service := &fakeAgentService{
		listSessionsResp:  []domain.SessionSummary{{ThreadID: "thread-1"}},
		listSessionsToken: "page-2",
		getSessionResp:    domain.SessionSummary{ThreadID: "thread-1"},
		getPageResp: domain.SessionMessagePage{
			ThreadID:             "thread-1",
			ResolvedCheckpointID: "cp-2",
			ActualMode:           domain.SessionHistoryModeResumeView,
			Messages:             []domain.SessionMessage{{Index: 0, Text: "hello"}},
			NextPageToken:        "page-2",
		},
		getMessagesResp:  []domain.SessionMessage{{Index: 0, Text: "hello"}},
		getMessagesToken: "page-2",
		getLatestResp:    domain.SessionSummary{ThreadID: "thread-9"},
	}
	server, err := NewServer(service)
	if err != nil {
		t.Fatalf("NewServer: %v", err)
	}

	sessions, token, err := server.ListSessions(context.Background(), "assistant", 20, "page-1")
	if err != nil {
		t.Fatalf("ListSessions: %v", err)
	}
	if len(sessions) != 1 || token != "page-2" {
		t.Fatalf("unexpected list sessions response: %#v %q", sessions, token)
	}

	session, err := server.GetSession(context.Background(), "thread-1")
	if err != nil {
		t.Fatalf("GetSession: %v", err)
	}
	if session.ThreadID != "thread-1" {
		t.Fatalf("unexpected session: %#v", session)
	}

	page, err := server.GetSessionMessagePage(context.Background(), pageQuery)
	if err != nil {
		t.Fatalf("GetSessionMessagePage: %v", err)
	}
	if page.ResolvedCheckpointID != "cp-2" {
		t.Fatalf("unexpected page: %#v", page)
	}
	if service.getPageQuery != pageQuery {
		t.Fatalf("unexpected page query input: %#v", service.getPageQuery)
	}

	messages, nextPageToken, err := server.GetSessionMessages(
		context.Background(),
		"thread-1",
		domain.SessionHistoryModeResumeView,
		20,
		"page-1",
	)
	if err != nil {
		t.Fatalf("GetSessionMessages: %v", err)
	}
	if len(messages) != 1 || nextPageToken != "page-2" {
		t.Fatalf("unexpected messages response: %#v %q", messages, nextPageToken)
	}

	latest, err := server.GetLatestSession(context.Background(), "assistant")
	if err != nil {
		t.Fatalf("GetLatestSession: %v", err)
	}
	if latest.ThreadID != "thread-9" {
		t.Fatalf("unexpected latest session: %#v", latest)
	}

	if err := server.DeleteSession(context.Background(), "thread-1"); err != nil {
		t.Fatalf("DeleteSession: %v", err)
	}
	if service.deleteThreadID != "thread-1" {
		t.Fatalf("unexpected delete input: %#v", service)
	}
}

func TestServerDelegatesResourceCRUD(t *testing.T) {
	service := &fakeAgentService{
		upsertSkillResp: domain.Skill{Name: "research"},
		getSkillResp:    domain.Skill{Name: "research"},
		listSkillsResp:  []domain.Skill{{Name: "research"}},
		upsertMCPResp:   domain.MCPConfig{Name: "github"},
		getMCPResp:      domain.MCPConfig{Name: "github"},
		listMCPsResp:    []domain.MCPConfig{{Name: "github"}},
		upsertAgentResp: domain.AuthoredAgentSpec{Name: "assistant"},
		getAgentResp:    domain.AuthoredAgentSpec{Name: "assistant"},
		listAgentsResp:  []domain.AuthoredAgentSpec{{Name: "assistant"}},
	}
	server, err := NewServer(service)
	if err != nil {
		t.Fatalf("NewServer: %v", err)
	}

	if _, err := server.UpsertSkill(context.Background(), domain.Skill{Name: "research"}); err != nil {
		t.Fatalf("UpsertSkill: %v", err)
	}
	if _, err := server.GetSkill(context.Background(), "research"); err != nil {
		t.Fatalf("GetSkill: %v", err)
	}
	if _, err := server.ListSkills(context.Background()); err != nil {
		t.Fatalf("ListSkills: %v", err)
	}
	if err := server.DeleteSkill(context.Background(), "research"); err != nil {
		t.Fatalf("DeleteSkill: %v", err)
	}

	if _, err := server.UpsertMCPConfig(context.Background(), domain.MCPConfig{Name: "github"}); err != nil {
		t.Fatalf("UpsertMCPConfig: %v", err)
	}
	if _, err := server.GetMCPConfig(context.Background(), "github"); err != nil {
		t.Fatalf("GetMCPConfig: %v", err)
	}
	if _, err := server.ListMCPConfigs(context.Background()); err != nil {
		t.Fatalf("ListMCPConfigs: %v", err)
	}
	if err := server.DeleteMCPConfig(context.Background(), "github"); err != nil {
		t.Fatalf("DeleteMCPConfig: %v", err)
	}

	if _, err := server.UpsertAgentSpec(context.Background(), domain.AuthoredAgentSpec{Name: "assistant"}); err != nil {
		t.Fatalf("UpsertAgentSpec: %v", err)
	}
	if _, err := server.GetAgentSpec(context.Background(), "assistant"); err != nil {
		t.Fatalf("GetAgentSpec: %v", err)
	}
	if _, err := server.ListAgentSpecs(context.Background()); err != nil {
		t.Fatalf("ListAgentSpecs: %v", err)
	}
	if err := server.DeleteAgentSpec(context.Background(), "assistant"); err != nil {
		t.Fatalf("DeleteAgentSpec: %v", err)
	}

	if service.upsertSkillReq.Name != "research" || service.getSkillName != "research" || service.deleteSkillName != "research" {
		t.Fatalf("unexpected skill delegation: %#v", service)
	}
	if service.upsertMCPReq.Name != "github" || service.getMCPName != "github" || service.deleteMCPName != "github" {
		t.Fatalf("unexpected mcp delegation: %#v", service)
	}
	if service.upsertAgentReq.Name != "assistant" || service.getAgentName != "assistant" || service.deleteAgentName != "assistant" {
		t.Fatalf("unexpected agent delegation: %#v", service)
	}
}

func TestServerPropagatesServiceErrors(t *testing.T) {
	expectedErr := errors.New("boom")
	service := &fakeAgentService{
		ensureRunnableErr: expectedErr,
		runErr:            expectedErr,
		healthErr:         expectedErr,
		listSessionsErr:   expectedErr,
		getSessionErr:     expectedErr,
		getPageErr:        expectedErr,
		getMessagesErr:    expectedErr,
		getLatestErr:      expectedErr,
		deleteErr:         expectedErr,
		upsertSkillErr:    expectedErr,
		getSkillErr:       expectedErr,
		listSkillsErr:     expectedErr,
		deleteSkillErr:    expectedErr,
		upsertMCPErr:      expectedErr,
		getMCPErr:         expectedErr,
		listMCPsErr:       expectedErr,
		deleteMCPErr:      expectedErr,
		upsertAgentErr:    expectedErr,
		getAgentErr:       expectedErr,
		listAgentsErr:     expectedErr,
		deleteAgentErr:    expectedErr,
	}
	server, err := NewServer(service)
	if err != nil {
		t.Fatalf("NewServer: %v", err)
	}

	if err := server.EnsureRunnable(context.Background(), "assistant"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected EnsureRunnable error, got %v", err)
	}
	if _, err := server.RunAgent(context.Background(), domain.RunRequest{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected RunAgent error, got %v", err)
	}
	if _, err := server.Health(context.Background()); !errors.Is(err, expectedErr) {
		t.Fatalf("expected Health error, got %v", err)
	}
	if _, _, err := server.ListSessions(context.Background(), "", 0, ""); !errors.Is(err, expectedErr) {
		t.Fatalf("expected ListSessions error, got %v", err)
	}
	if _, err := server.GetSession(context.Background(), "thread-1"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetSession error, got %v", err)
	}
	if _, err := server.GetSessionMessagePage(context.Background(), domain.SessionMessageQuery{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetSessionMessagePage error, got %v", err)
	}
	if _, _, err := server.GetSessionMessages(
		context.Background(),
		"thread-1",
		domain.SessionHistoryModeResumeView,
		20,
		"",
	); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetSessionMessages error, got %v", err)
	}
	if _, err := server.GetLatestSession(context.Background(), "assistant"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetLatestSession error, got %v", err)
	}
	if err := server.DeleteSession(context.Background(), "thread-1"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected DeleteSession error, got %v", err)
	}
	if _, err := server.UpsertSkill(context.Background(), domain.Skill{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected UpsertSkill error, got %v", err)
	}
	if _, err := server.GetSkill(context.Background(), "research"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetSkill error, got %v", err)
	}
	if _, err := server.ListSkills(context.Background()); !errors.Is(err, expectedErr) {
		t.Fatalf("expected ListSkills error, got %v", err)
	}
	if err := server.DeleteSkill(context.Background(), "research"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected DeleteSkill error, got %v", err)
	}
	if _, err := server.UpsertMCPConfig(context.Background(), domain.MCPConfig{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected UpsertMCPConfig error, got %v", err)
	}
	if _, err := server.GetMCPConfig(context.Background(), "github"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetMCPConfig error, got %v", err)
	}
	if _, err := server.ListMCPConfigs(context.Background()); !errors.Is(err, expectedErr) {
		t.Fatalf("expected ListMCPConfigs error, got %v", err)
	}
	if err := server.DeleteMCPConfig(context.Background(), "github"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected DeleteMCPConfig error, got %v", err)
	}
	if _, err := server.UpsertAgentSpec(context.Background(), domain.AuthoredAgentSpec{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected UpsertAgentSpec error, got %v", err)
	}
	if _, err := server.GetAgentSpec(context.Background(), "assistant"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetAgentSpec error, got %v", err)
	}
	if _, err := server.ListAgentSpecs(context.Background()); !errors.Is(err, expectedErr) {
		t.Fatalf("expected ListAgentSpecs error, got %v", err)
	}
	if err := server.DeleteAgentSpec(context.Background(), "assistant"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected DeleteAgentSpec error, got %v", err)
	}
}
