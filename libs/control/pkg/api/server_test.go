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
	uploadResp domain.WorkspaceUploadResponse
	uploadErr  error
	uploadReq  domain.WorkspaceUploadRequest

	downloadResp domain.WorkspaceDownloadResponse
	downloadErr  error
	downloadReq  domain.WorkspaceDownloadRequest

	listFilesResp domain.WorkspaceListResponse
	listFilesErr  error
	listFilesReq  domain.WorkspaceListRequest

	artifactsResp domain.ListArtifactsResponse
	artifactsErr  error
	artifactsReq  domain.ListArtifactsRequest

	healthResp runtimeclient.HealthResponse
	healthErr  error

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

	deleteErr     error
	deleteLocator domain.SessionLocator

	upsertModelResp domain.ModelConfig
	upsertModelErr  error
	upsertModelReq  domain.ModelConfig
	getModelResp    domain.ModelConfig
	getModelErr     error
	getModelName    string
	listModelsResp  []domain.ModelConfig
	listModelsPage  domain.ResourcePage[domain.ModelConfig]
	listModelsQuery domain.PageQuery
	listModelsErr   error
	deleteModelErr  error
	deleteModelName string

	upsertSkillResp domain.Skill
	upsertSkillErr  error
	upsertSkillReq  domain.Skill
	getSkillResp    domain.Skill
	getSkillErr     error
	getSkillName    string
	listSkillsResp  []domain.Skill
	listSkillsPage  domain.ResourcePage[domain.Skill]
	listSkillsQuery domain.PageQuery
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
	listMCPsPage  domain.ResourcePage[domain.MCPConfig]
	listMCPsQuery domain.PageQuery
	listMCPsErr   error
	deleteMCPErr  error
	deleteMCPName string

	upsertSandboxResp  domain.SandboxConfig
	upsertSandboxErr   error
	upsertSandboxReq   domain.SandboxConfig
	getSandboxResp     domain.SandboxConfig
	getSandboxErr      error
	getSandboxName     string
	listSandboxesResp  []domain.SandboxConfig
	listSandboxesPage  domain.ResourcePage[domain.SandboxConfig]
	listSandboxesQuery domain.PageQuery
	listSandboxesErr   error
	deleteSandboxErr   error
	deleteSandboxName  string

	upsertAgentResp domain.AuthoredAgentSpec
	upsertAgentErr  error
	upsertAgentReq  domain.AuthoredAgentSpec
	getAgentResp    domain.AuthoredAgentSpec
	getAgentErr     error
	getAgentName    string
	listAgentsResp  []domain.AuthoredAgentSpec
	listAgentsPage  domain.ResourcePage[domain.AuthoredAgentSpec]
	listAgentsQuery domain.PageQuery
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

func (f *fakeAgentService) UploadWorkspaceFiles(
	_ context.Context,
	req domain.WorkspaceUploadRequest,
) (domain.WorkspaceUploadResponse, error) {
	f.uploadReq = req
	return f.uploadResp, f.uploadErr
}

func (f *fakeAgentService) DownloadWorkspaceFiles(
	_ context.Context,
	req domain.WorkspaceDownloadRequest,
) (domain.WorkspaceDownloadResponse, error) {
	f.downloadReq = req
	return f.downloadResp, f.downloadErr
}

func (f *fakeAgentService) ListWorkspaceFiles(
	_ context.Context,
	req domain.WorkspaceListRequest,
) (domain.WorkspaceListResponse, error) {
	f.listFilesReq = req
	return f.listFilesResp, f.listFilesErr
}

func (f *fakeAgentService) ListThreadArtifacts(
	_ context.Context,
	req domain.ListArtifactsRequest,
) (domain.ListArtifactsResponse, error) {
	f.artifactsReq = req
	return f.artifactsResp, f.artifactsErr
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

func (f *fakeAgentService) GetSession(
	_ context.Context,
	locator domain.SessionLocator,
) (domain.SessionSummary, error) {
	f.getSessionLocator = locator
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
	query domain.SessionMessageQuery,
) ([]domain.SessionMessage, string, error) {
	f.getMessagesQuery = query
	return f.getMessagesResp, f.getMessagesToken, f.getMessagesErr
}

func (f *fakeAgentService) GetLatestSession(_ context.Context, agentName string) (domain.SessionSummary, error) {
	f.getLatestAgentName = agentName
	return f.getLatestResp, f.getLatestErr
}

func (f *fakeAgentService) DeleteSession(_ context.Context, locator domain.SessionLocator) error {
	f.deleteLocator = locator
	return f.deleteErr
}

func (f *fakeAgentService) UpsertModelConfig(
	_ context.Context,
	config domain.ModelConfig,
) (domain.ModelConfig, error) {
	f.upsertModelReq = config
	return f.upsertModelResp, f.upsertModelErr
}

func (f *fakeAgentService) GetModelConfig(_ context.Context, name string) (domain.ModelConfig, error) {
	f.getModelName = name
	return f.getModelResp, f.getModelErr
}

func (f *fakeAgentService) ListModelConfigs(context.Context) ([]domain.ModelConfig, error) {
	return f.listModelsResp, f.listModelsErr
}

func (f *fakeAgentService) ListModelConfigsPage(
	_ context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.ModelConfig], error) {
	f.listModelsQuery = query
	return f.listModelsPage, f.listModelsErr
}

func (f *fakeAgentService) DeleteModelConfig(_ context.Context, name string) error {
	f.deleteModelName = name
	return f.deleteModelErr
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

func (f *fakeAgentService) ListSkillsPage(
	_ context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.Skill], error) {
	f.listSkillsQuery = query
	return f.listSkillsPage, f.listSkillsErr
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

func (f *fakeAgentService) ListMCPConfigsPage(
	_ context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.MCPConfig], error) {
	f.listMCPsQuery = query
	return f.listMCPsPage, f.listMCPsErr
}

func (f *fakeAgentService) DeleteMCPConfig(_ context.Context, name string) error {
	f.deleteMCPName = name
	return f.deleteMCPErr
}

func (f *fakeAgentService) UpsertSandboxConfig(
	_ context.Context,
	config domain.SandboxConfig,
) (domain.SandboxConfig, error) {
	f.upsertSandboxReq = config
	return f.upsertSandboxResp, f.upsertSandboxErr
}

func (f *fakeAgentService) GetSandboxConfig(_ context.Context, name string) (domain.SandboxConfig, error) {
	f.getSandboxName = name
	return f.getSandboxResp, f.getSandboxErr
}

func (f *fakeAgentService) ListSandboxConfigs(context.Context) ([]domain.SandboxConfig, error) {
	return f.listSandboxesResp, f.listSandboxesErr
}

func (f *fakeAgentService) ListSandboxConfigsPage(
	_ context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.SandboxConfig], error) {
	f.listSandboxesQuery = query
	return f.listSandboxesPage, f.listSandboxesErr
}

func (f *fakeAgentService) DeleteSandboxConfig(_ context.Context, name string) error {
	f.deleteSandboxName = name
	return f.deleteSandboxErr
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

func (f *fakeAgentService) ListAgentSpecsPage(
	_ context.Context,
	query domain.PageQuery,
) (domain.ResourcePage[domain.AuthoredAgentSpec], error) {
	f.listAgentsQuery = query
	return f.listAgentsPage, f.listAgentsErr
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
		runStream: stubRunStream{},
		uploadResp: domain.WorkspaceUploadResponse{
			ThreadID: "thread-1",
			Files: []domain.WorkspaceUploadResult{
				{Path: "/workspace/report.txt"},
			},
		},
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

	uploadResp, err := server.UploadWorkspaceFiles(
		context.Background(),
		domain.WorkspaceUploadRequest{
			AgentName: "assistant",
			ThreadID:  "thread-1",
			Files: []domain.WorkspaceUploadFile{
				{Path: "report.txt", Content: []byte("hello")},
			},
		},
	)
	if err != nil {
		t.Fatalf("UploadWorkspaceFiles: %v", err)
	}
	if uploadResp.ThreadID != "thread-1" || len(uploadResp.Files) != 1 {
		t.Fatalf("unexpected upload response: %#v", uploadResp)
	}
	if service.uploadReq.AgentName != "assistant" || service.uploadReq.ThreadID != "thread-1" {
		t.Fatalf("unexpected upload request: %#v", service.uploadReq)
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
		AgentName:  "assistant",
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

	session, err := server.GetSession(context.Background(), domain.SessionLocator{
		AgentName: "assistant",
		ThreadID:  "thread-1",
	})
	if err != nil {
		t.Fatalf("GetSession: %v", err)
	}
	if session.ThreadID != "thread-1" {
		t.Fatalf("unexpected session: %#v", session)
	}
	if service.getSessionLocator != (domain.SessionLocator{AgentName: "assistant", ThreadID: "thread-1"}) {
		t.Fatalf("unexpected session locator input: %#v", service.getSessionLocator)
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

	messages, nextPageToken, err := server.GetSessionMessages(context.Background(), domain.SessionMessageQuery{
		AgentName: "assistant",
		ThreadID:  "thread-1",
		Mode:      domain.SessionHistoryModeResumeView,
		PageSize:  20,
		PageToken: "page-1",
	})
	if err != nil {
		t.Fatalf("GetSessionMessages: %v", err)
	}
	if len(messages) != 1 || nextPageToken != "page-2" {
		t.Fatalf("unexpected messages response: %#v %q", messages, nextPageToken)
	}
	if service.getMessagesQuery != (domain.SessionMessageQuery{
		AgentName: "assistant",
		ThreadID:  "thread-1",
		Mode:      domain.SessionHistoryModeResumeView,
		PageSize:  20,
		PageToken: "page-1",
	}) {
		t.Fatalf("unexpected messages query input: %#v", service.getMessagesQuery)
	}

	latest, err := server.GetLatestSession(context.Background(), "assistant")
	if err != nil {
		t.Fatalf("GetLatestSession: %v", err)
	}
	if latest.ThreadID != "thread-9" {
		t.Fatalf("unexpected latest session: %#v", latest)
	}

	if err := server.DeleteSession(context.Background(), domain.SessionLocator{
		AgentName: "assistant",
		ThreadID:  "thread-1",
	}); err != nil {
		t.Fatalf("DeleteSession: %v", err)
	}
	if service.deleteLocator != (domain.SessionLocator{AgentName: "assistant", ThreadID: "thread-1"}) {
		t.Fatalf("unexpected delete input: %#v", service)
	}
}

func TestServerDelegatesResourceCRUD(t *testing.T) {
	service := &fakeAgentService{
		upsertModelResp: domain.ModelConfig{Name: "default-openai"},
		getModelResp:    domain.ModelConfig{Name: "default-openai"},
		listModelsResp:  []domain.ModelConfig{{Name: "default-openai"}},
		listModelsPage: domain.ResourcePage[domain.ModelConfig]{
			Items: []domain.ModelConfig{{Name: "default-openai"}},
			PageMetadata: domain.PageMetadata{
				PageSize:   10,
				PageNumber: 2,
				TotalSize:  11,
				TotalPages: 2,
			},
		},
		upsertSkillResp: domain.Skill{Name: "research"},
		getSkillResp:    domain.Skill{Name: "research"},
		listSkillsResp:  []domain.Skill{{Name: "research"}},
		listSkillsPage: domain.ResourcePage[domain.Skill]{
			Items: []domain.Skill{{Name: "research"}},
			PageMetadata: domain.PageMetadata{
				PageSize:   10,
				PageNumber: 2,
				TotalSize:  11,
				TotalPages: 2,
			},
		},
		upsertMCPResp: domain.MCPConfig{Name: "github"},
		getMCPResp:    domain.MCPConfig{Name: "github"},
		listMCPsResp:  []domain.MCPConfig{{Name: "github"}},
		listMCPsPage: domain.ResourcePage[domain.MCPConfig]{
			Items: []domain.MCPConfig{{Name: "github"}},
			PageMetadata: domain.PageMetadata{
				PageSize:   10,
				PageNumber: 2,
				TotalSize:  11,
				TotalPages: 2,
			},
		},
		upsertAgentResp: domain.AuthoredAgentSpec{Name: "assistant"},
		getAgentResp:    domain.AuthoredAgentSpec{Name: "assistant"},
		listAgentsResp:  []domain.AuthoredAgentSpec{{Name: "assistant"}},
		listAgentsPage: domain.ResourcePage[domain.AuthoredAgentSpec]{
			Items: []domain.AuthoredAgentSpec{{Name: "assistant"}},
			PageMetadata: domain.PageMetadata{
				PageSize:   10,
				PageNumber: 2,
				TotalSize:  11,
				TotalPages: 2,
			},
		},
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
	if page, err := server.ListSkillsPage(context.Background(), domain.PageQuery{PageSize: 10, PageNumber: 2}); err != nil || len(page.Items) != 1 {
		t.Fatalf("ListSkillsPage: %#v err=%v", page, err)
	}
	if err := server.DeleteSkill(context.Background(), "research"); err != nil {
		t.Fatalf("DeleteSkill: %v", err)
	}

	if _, err := server.UpsertModelConfig(context.Background(), domain.ModelConfig{Name: "default-openai"}); err != nil {
		t.Fatalf("UpsertModelConfig: %v", err)
	}
	if _, err := server.GetModelConfig(context.Background(), "default-openai"); err != nil {
		t.Fatalf("GetModelConfig: %v", err)
	}
	if _, err := server.ListModelConfigs(context.Background()); err != nil {
		t.Fatalf("ListModelConfigs: %v", err)
	}
	if page, err := server.ListModelConfigsPage(context.Background(), domain.PageQuery{PageSize: 10, PageNumber: 2}); err != nil || len(page.Items) != 1 {
		t.Fatalf("ListModelConfigsPage: %#v err=%v", page, err)
	}
	if err := server.DeleteModelConfig(context.Background(), "default-openai"); err != nil {
		t.Fatalf("DeleteModelConfig: %v", err)
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
	if page, err := server.ListMCPConfigsPage(context.Background(), domain.PageQuery{PageSize: 10, PageNumber: 2}); err != nil || len(page.Items) != 1 {
		t.Fatalf("ListMCPConfigsPage: %#v err=%v", page, err)
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
	if page, err := server.ListAgentSpecsPage(context.Background(), domain.PageQuery{PageSize: 10, PageNumber: 2}); err != nil || len(page.Items) != 1 {
		t.Fatalf("ListAgentSpecsPage: %#v err=%v", page, err)
	}
	if err := server.DeleteAgentSpec(context.Background(), "assistant"); err != nil {
		t.Fatalf("DeleteAgentSpec: %v", err)
	}

	if service.upsertSkillReq.Name != "research" || service.getSkillName != "research" || service.deleteSkillName != "research" {
		t.Fatalf("unexpected skill delegation: %#v", service)
	}
	if service.listSkillsQuery != (domain.PageQuery{PageSize: 10, PageNumber: 2}) {
		t.Fatalf("unexpected skill page delegation: %#v", service.listSkillsQuery)
	}
	if service.upsertModelReq.Name != "default-openai" || service.getModelName != "default-openai" || service.deleteModelName != "default-openai" {
		t.Fatalf("unexpected model delegation: %#v", service)
	}
	if service.listModelsQuery != (domain.PageQuery{PageSize: 10, PageNumber: 2}) {
		t.Fatalf("unexpected model page delegation: %#v", service.listModelsQuery)
	}
	if service.upsertMCPReq.Name != "github" || service.getMCPName != "github" || service.deleteMCPName != "github" {
		t.Fatalf("unexpected mcp delegation: %#v", service)
	}
	if service.listMCPsQuery != (domain.PageQuery{PageSize: 10, PageNumber: 2}) {
		t.Fatalf("unexpected mcp page delegation: %#v", service.listMCPsQuery)
	}
	if service.upsertAgentReq.Name != "assistant" || service.getAgentName != "assistant" || service.deleteAgentName != "assistant" {
		t.Fatalf("unexpected agent delegation: %#v", service)
	}
	if service.listAgentsQuery != (domain.PageQuery{PageSize: 10, PageNumber: 2}) {
		t.Fatalf("unexpected agent page delegation: %#v", service.listAgentsQuery)
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
		upsertModelErr:    expectedErr,
		getModelErr:       expectedErr,
		listModelsErr:     expectedErr,
		deleteModelErr:    expectedErr,
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
	if _, err := server.GetSession(context.Background(), domain.SessionLocator{
		AgentName: "assistant",
		ThreadID:  "thread-1",
	}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetSession error, got %v", err)
	}
	if _, err := server.GetSessionMessagePage(context.Background(), domain.SessionMessageQuery{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetSessionMessagePage error, got %v", err)
	}
	if _, _, err := server.GetSessionMessages(context.Background(), domain.SessionMessageQuery{
		AgentName: "assistant",
		ThreadID:  "thread-1",
		Mode:      domain.SessionHistoryModeResumeView,
		PageSize:  20,
	}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetSessionMessages error, got %v", err)
	}
	if _, err := server.GetLatestSession(context.Background(), "assistant"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetLatestSession error, got %v", err)
	}
	if err := server.DeleteSession(context.Background(), domain.SessionLocator{
		AgentName: "assistant",
		ThreadID:  "thread-1",
	}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected DeleteSession error, got %v", err)
	}
	if _, err := server.UpsertModelConfig(context.Background(), domain.ModelConfig{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected UpsertModelConfig error, got %v", err)
	}
	if _, err := server.GetModelConfig(context.Background(), "default-openai"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected GetModelConfig error, got %v", err)
	}
	if _, err := server.ListModelConfigs(context.Background()); !errors.Is(err, expectedErr) {
		t.Fatalf("expected ListModelConfigs error, got %v", err)
	}
	if _, err := server.ListModelConfigsPage(context.Background(), domain.PageQuery{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected ListModelConfigsPage error, got %v", err)
	}
	if err := server.DeleteModelConfig(context.Background(), "default-openai"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected DeleteModelConfig error, got %v", err)
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
	if _, err := server.ListSkillsPage(context.Background(), domain.PageQuery{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected ListSkillsPage error, got %v", err)
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
	if _, err := server.ListMCPConfigsPage(context.Background(), domain.PageQuery{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected ListMCPConfigsPage error, got %v", err)
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
	if _, err := server.ListAgentSpecsPage(context.Background(), domain.PageQuery{}); !errors.Is(err, expectedErr) {
		t.Fatalf("expected ListAgentSpecsPage error, got %v", err)
	}
	if err := server.DeleteAgentSpec(context.Background(), "assistant"); !errors.Is(err, expectedErr) {
		t.Fatalf("expected DeleteAgentSpec error, got %v", err)
	}
}
