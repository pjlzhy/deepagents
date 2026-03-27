package api

import (
	"agentctl/pkg/domain"
	registrypkg "agentctl/pkg/registry"
	"agentctl/pkg/runtimeclient"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

type httpTransportRunStream struct {
	events chan runtimeclient.AgentEvent

	mu              sync.Mutex
	decisions       []runtimeclient.ToolDecision
	interruptIDs    []string
	cancels         []string
	sendDecisionErr error
	sendCancelErr   error
	closeErr        error
	closeCalls      int

	decisionSignal chan struct{}
	cancelSignal   chan struct{}
}

func newHTTPTransportRunStream() *httpTransportRunStream {
	return &httpTransportRunStream{
		events:         make(chan runtimeclient.AgentEvent, 16),
		decisionSignal: make(chan struct{}, 1),
		cancelSignal:   make(chan struct{}, 1),
	}
}

func (s *httpTransportRunStream) Events() <-chan runtimeclient.AgentEvent {
	return s.events
}

func (s *httpTransportRunStream) SendHITLDecision(
	_ context.Context,
	interruptID string,
	decisions []runtimeclient.ToolDecision,
) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.interruptIDs = append(s.interruptIDs, interruptID)
	s.decisions = append(s.decisions, decisions...)
	select {
	case s.decisionSignal <- struct{}{}:
	default:
	}
	return s.sendDecisionErr
}

func (s *httpTransportRunStream) SendCancel(_ context.Context, reason string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.cancels = append(s.cancels, reason)
	select {
	case s.cancelSignal <- struct{}{}:
	default:
	}
	return s.sendCancelErr
}

func (s *httpTransportRunStream) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.closeCalls++
	return s.closeErr
}

func TestHTTPHandlerStreamsRunEventsOverSSE(t *testing.T) {
	runStream := newHTTPTransportRunStream()
	service := &fakeAgentService{runStream: runStream}
	handler, err := NewHTTPHandler(service, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	startedAt := time.Unix(1710000000, 125000000).UTC()
	deltaAt := time.Unix(1710000000, 250000000).UTC()
	toolAt := time.Unix(1710000000, 375000000).UTC()
	endedAt := time.Unix(1710000000, 500000000).UTC()

	go func() {
		runStream.events <- runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeRunStarted,
			RunID:     "run-1",
			AgentName: "assistant",
			ThreadID:  "thread-1",
			Timestamp: startedAt,
		}
		runStream.events <- runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeTextDelta,
			RunID:     "run-1",
			AgentName: "assistant",
			ThreadID:  "thread-1",
			Text:      "hello",
			Timestamp: deltaAt,
		}
		runStream.events <- runtimeclient.AgentEvent{
			Type:       runtimeclient.AgentEventTypeToolCallStart,
			RunID:      "run-1",
			AgentName:  "assistant",
			ThreadID:   "thread-1",
			ToolName:   "execute",
			ToolCallID: "tool-1",
			Payload:    json.RawMessage(`{"command":"pwd"}`),
			Timestamp:  toolAt,
		}
		runStream.events <- runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeRunEnded,
			RunID:     "run-1",
			AgentName: "assistant",
			ThreadID:  "thread-1",
			Timestamp: endedAt,
		}
		close(runStream.events)
	}()

	resp, err := http.Post(
		server.URL+"/api/v1/agents/assistant/runs/stream",
		"application/json",
		strings.NewReader(`{"message":"hello","thread_id":"thread-1","metadata":{"source":"test"}}`),
	)
	if err != nil {
		t.Fatalf("POST run stream: %v", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read response body: %v", err)
	}

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected status: %d body=%s", resp.StatusCode, string(body))
	}
	if contentType := resp.Header.Get("Content-Type"); !strings.HasPrefix(contentType, "text/event-stream") {
		t.Fatalf("unexpected content type: %s", contentType)
	}
	sessionID := resp.Header.Get(runSessionHeader)
	if sessionID == "" {
		t.Fatal("expected run session header")
	}
	bodyText := string(body)
	if !strings.Contains(bodyText, "event: run_session") ||
		!strings.Contains(bodyText, `"session_id":"`+sessionID+`"`) {
		t.Fatalf("expected run session event, got %s", bodyText)
	}
	if !strings.Contains(bodyText, "event: run_started") ||
		!strings.Contains(bodyText, "event: text_delta") ||
		!strings.Contains(bodyText, "event: tool_call_start") ||
		!strings.Contains(bodyText, "event: run_ended") {
		t.Fatalf("expected run events in body, got %s", bodyText)
	}
	if !strings.Contains(bodyText, `"agent_name":"assistant"`) ||
		!strings.Contains(bodyText, `"text":"hello"`) ||
		!strings.Contains(bodyText, `"payload":{"command":"pwd"}`) ||
		!strings.Contains(bodyText, `"timestamp":"`+startedAt.Format("2006-01-02T15:04:05.999999999Z07:00")+`"`) {
		t.Fatalf("expected event payload in body, got %s", bodyText)
	}

	if service.runRequest.AgentName != "assistant" ||
		service.runRequest.Message != "hello" ||
		service.runRequest.ThreadID != "thread-1" ||
		service.runRequest.Metadata["source"] != "test" {
		t.Fatalf("unexpected run request: %#v", service.runRequest)
	}
	if runStream.closeCalls != 1 {
		t.Fatalf("expected upstream close once, got %d", runStream.closeCalls)
	}
}

func TestHTTPHandlerForwardsCancelRequests(t *testing.T) {
	runStream := newHTTPTransportRunStream()
	service := &fakeAgentService{runStream: runStream}
	handler, err := NewHTTPHandler(service, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	request, err := http.NewRequest(
		http.MethodPost,
		server.URL+"/api/v1/agents/assistant/runs/stream",
		strings.NewReader(`{"message":"hello"}`),
	)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	request.Header.Set("Content-Type", "application/json")

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("Do run request: %v", err)
	}
	sessionID := response.Header.Get(runSessionHeader)
	if sessionID == "" {
		t.Fatal("expected run session header")
	}

	cancelResp, err := http.Post(
		server.URL+"/api/v1/run_sessions/"+sessionID+"/cancel",
		"application/json",
		strings.NewReader(`{"reason":"user canceled"}`),
	)
	if err != nil {
		t.Fatalf("POST cancel request: %v", err)
	}
	defer cancelResp.Body.Close()

	if cancelResp.StatusCode != http.StatusAccepted {
		body, _ := io.ReadAll(cancelResp.Body)
		t.Fatalf("unexpected cancel status: %d body=%s", cancelResp.StatusCode, string(body))
	}
	waitForSignal(t, runStream.cancelSignal, "cancel")

	runStream.mu.Lock()
	if len(runStream.cancels) != 1 || runStream.cancels[0] != "user canceled" {
		runStream.mu.Unlock()
		t.Fatalf("unexpected cancels: %#v", runStream.cancels)
	}
	runStream.mu.Unlock()

	response.Body.Close()
	close(runStream.events)
}

func TestHTTPHandlerForwardsHITLDecisions(t *testing.T) {
	runStream := newHTTPTransportRunStream()
	service := &fakeAgentService{runStream: runStream}
	handler, err := NewHTTPHandler(service, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	request, err := http.NewRequest(
		http.MethodPost,
		server.URL+"/api/v1/agents/assistant/runs/stream",
		strings.NewReader(`{"message":"hello"}`),
	)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	request.Header.Set("Content-Type", "application/json")

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("Do run request: %v", err)
	}
	sessionID := response.Header.Get(runSessionHeader)
	if sessionID == "" {
		t.Fatal("expected run session header")
	}

	hitlResp, err := http.Post(
		server.URL+"/api/v1/run_sessions/"+sessionID+"/hitl_decisions",
		"application/json",
		strings.NewReader(`{"interrupt_id":"interrupt-1","decisions":[{"type":"approve"}]}`),
	)
	if err != nil {
		t.Fatalf("POST hitl request: %v", err)
	}
	defer hitlResp.Body.Close()

	if hitlResp.StatusCode != http.StatusAccepted {
		body, _ := io.ReadAll(hitlResp.Body)
		t.Fatalf("unexpected hitl status: %d body=%s", hitlResp.StatusCode, string(body))
	}
	waitForSignal(t, runStream.decisionSignal, "hitl decision")

	runStream.mu.Lock()
	if len(runStream.interruptIDs) != 1 || runStream.interruptIDs[0] != "interrupt-1" {
		runStream.mu.Unlock()
		t.Fatalf("unexpected interrupt ids: %#v", runStream.interruptIDs)
	}
	if len(runStream.decisions) != 1 ||
		runStream.decisions[0].Type != "approve" ||
		runStream.decisions[0].EditedAction != nil ||
		runStream.decisions[0].Message != "" {
		runStream.mu.Unlock()
		t.Fatalf("unexpected decisions: %#v", runStream.decisions)
	}
	runStream.mu.Unlock()

	response.Body.Close()
	close(runStream.events)
}

func TestHTTPHandlerReturnsNotFoundForUnknownRunSession(t *testing.T) {
	handler, err := NewHTTPHandler(&fakeAgentService{}, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	resp, err := http.Post(
		server.URL+"/api/v1/run_sessions/missing/cancel",
		"application/json",
		strings.NewReader(`{"reason":"user canceled"}`),
	)
	if err != nil {
		t.Fatalf("POST cancel request: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusNotFound {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("unexpected status: %d body=%s", resp.StatusCode, string(body))
	}
}

func TestDecodeHITLDecisionRequestDecodesRejectDecision(t *testing.T) {
	request := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/run_sessions/session-1/hitl_decisions",
		strings.NewReader(`{"interrupt_id":"interrupt-1","decisions":[{"type":"reject","message":"deny"}]}`),
	)
	request.Header.Set("Content-Type", "application/json")

	decoded, err := decodeHITLDecisionRequest(request)
	if err != nil {
		t.Fatalf("decodeHITLDecisionRequest: %v", err)
	}
	if decoded.InterruptID != "interrupt-1" {
		t.Fatalf("unexpected interrupt id: %q", decoded.InterruptID)
	}
	if len(decoded.Decisions) != 1 {
		t.Fatalf("unexpected decision count: %d", len(decoded.Decisions))
	}
	if decoded.Decisions[0].Type != "reject" {
		t.Fatalf("unexpected decision type: %q", decoded.Decisions[0].Type)
	}
	if decoded.Decisions[0].Message != "deny" {
		t.Fatalf("unexpected message: %q", decoded.Decisions[0].Message)
	}
}

func TestHTTPHandlerReturnsTransportErrorEvent(t *testing.T) {
	runStream := newHTTPTransportRunStream()
	runStream.sendCancelErr = errors.New("cancel failed")
	service := &fakeAgentService{runStream: runStream}
	handler, err := NewHTTPHandler(service, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	request, err := http.NewRequest(
		http.MethodPost,
		server.URL+"/api/v1/agents/assistant/runs/stream",
		strings.NewReader(`{"message":"hello"}`),
	)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	request.Header.Set("Content-Type", "application/json")

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("Do run request: %v", err)
	}
	sessionID := response.Header.Get(runSessionHeader)
	if sessionID == "" {
		t.Fatal("expected run session header")
	}

	cancelResp, err := http.Post(
		server.URL+"/api/v1/run_sessions/"+sessionID+"/cancel",
		"application/json",
		strings.NewReader(`{"reason":"user canceled"}`),
	)
	if err != nil {
		t.Fatalf("POST cancel request: %v", err)
	}
	cancelResp.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("read response body: %v", err)
	}
	if !strings.Contains(string(body), "event: transport_error") ||
		!strings.Contains(string(body), `"error":"forward cancel request: cancel failed"`) {
		t.Fatalf("expected transport_error event, got %s", string(body))
	}
}

func TestHTTPHandlerDelegatesLifecycleAndQueries(t *testing.T) {
	service := &fakeAgentService{
		healthResp: runtimeclient.HealthResponse{Ready: true, Status: "ok", RunningAgentCount: 1},
		listSessionsResp: []domain.SessionSummary{
			{ThreadID: "thread-1", AgentName: "assistant", MessageCount: 3},
		},
		listSessionsToken: "page-2",
		getSessionResp: domain.SessionSummary{
			ThreadID:           "thread-1",
			AgentName:          "assistant",
			LatestCheckpointID: "cp-2",
		},
		getPageResp: domain.SessionMessagePage{
			ThreadID:             "thread-1",
			ResolvedCheckpointID: "cp-2",
			ActualMode:           domain.SessionHistoryModeResumeView,
			TotalMessageCount:    2,
			Messages:             []domain.SessionMessage{{Index: 0, Text: "hello"}},
			NextPageToken:        "page-2",
		},
		getMessagesResp:  []domain.SessionMessage{{Index: 0, Text: "hello"}},
		getMessagesToken: "page-2",
		getLatestResp:    domain.SessionSummary{ThreadID: "thread-9", AgentName: "assistant"},
	}

	handler, err := NewHTTPHandler(service, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	healthResp, err := http.Get(server.URL + "/api/v1/health")
	if err != nil {
		t.Fatalf("GET health: %v", err)
	}
	assertStatus(t, healthResp, http.StatusOK)
	healthBody, healthRaw := decodeBodyWithRaw[healthResponse](t, healthResp)
	if healthBody.Status != "ok" || !healthBody.Ready || healthBody.RunningAgentCount != 1 {
		t.Fatalf("unexpected health body: %#v", healthBody)
	}
	if !strings.Contains(healthRaw, `"running_agent_count":1`) || strings.Contains(healthRaw, `"RunningAgentCount"`) {
		t.Fatalf("expected snake_case health response, got %s", healthRaw)
	}

	ensureReq, err := http.NewRequest(
		http.MethodPost,
		server.URL+"/api/v1/agents/assistant/ensure_runnable",
		nil,
	)
	if err != nil {
		t.Fatalf("NewRequest ensure: %v", err)
	}
	ensureResp, err := http.DefaultClient.Do(ensureReq)
	if err != nil {
		t.Fatalf("POST ensure: %v", err)
	}
	assertStatus(t, ensureResp, http.StatusAccepted)
	ensureResp.Body.Close()
	if service.ensureAgent != "assistant" {
		t.Fatalf("unexpected ensure inputs: %#v", service)
	}

	listResp, err := http.Get(server.URL + "/api/v1/sessions?agent_name=assistant&page_size=20&page_token=page-1")
	if err != nil {
		t.Fatalf("GET sessions: %v", err)
	}
	assertStatus(t, listResp, http.StatusOK)
	listBody := decodeBody[sessionListResponse](t, listResp)
	if len(listBody.Sessions) != 1 || listBody.Sessions[0].ThreadID != "thread-1" || listBody.NextPageToken != "page-2" {
		t.Fatalf("unexpected list body: %#v", listBody)
	}
	if service.listSessionsAgentName != "assistant" || service.listSessionsPageSize != 20 || service.listSessionsPageToken != "page-1" {
		t.Fatalf("unexpected list inputs: %#v", service)
	}

	sessionResp, err := http.Get(server.URL + "/api/v1/sessions/thread-1?agent_name=assistant")
	if err != nil {
		t.Fatalf("GET session: %v", err)
	}
	assertStatus(t, sessionResp, http.StatusOK)
	sessionBody, sessionRaw := decodeBodyWithRaw[sessionSummaryResponse](t, sessionResp)
	if sessionBody.ThreadID != "thread-1" ||
		service.getSessionLocator != (domain.SessionLocator{AgentName: "assistant", ThreadID: "thread-1"}) {
		t.Fatalf("unexpected session body or input: %#v %#v", sessionBody, service)
	}
	if !strings.Contains(sessionRaw, `"thread_id":"thread-1"`) || strings.Contains(sessionRaw, `"ThreadID"`) {
		t.Fatalf("expected snake_case session response, got %s", sessionRaw)
	}

	pageResp, err := http.Get(
		server.URL + "/api/v1/sessions/thread-1/message_page?agent_name=assistant&checkpoint_id=cp-1&mode=resume_view&page_size=20&page_token=page-1&include_raw=true",
	)
	if err != nil {
		t.Fatalf("GET message page: %v", err)
	}
	assertStatus(t, pageResp, http.StatusOK)
	pageBody, pageRaw := decodeBodyWithRaw[sessionMessagePageResponse](t, pageResp)
	if pageBody.ResolvedCheckpointID != "cp-2" || service.getPageQuery.AgentName != "assistant" ||
		service.getPageQuery.ThreadID != "thread-1" || service.getPageQuery.CheckpointID != "cp-1" ||
		service.getPageQuery.Mode != domain.SessionHistoryModeResumeView ||
		service.getPageQuery.PageSize != 20 || service.getPageQuery.PageToken != "page-1" || !service.getPageQuery.IncludeRaw {
		t.Fatalf("unexpected message page body or input: %#v %#v", pageBody, service.getPageQuery)
	}
	if !strings.Contains(pageRaw, `"resolved_checkpoint_id":"cp-2"`) || strings.Contains(pageRaw, `"ResolvedCheckpointID"`) {
		t.Fatalf("expected snake_case message page response, got %s", pageRaw)
	}

	messagesResp, err := http.Get(server.URL + "/api/v1/sessions/thread-1/messages?agent_name=assistant&mode=resume_view&page_size=20&page_token=page-1")
	if err != nil {
		t.Fatalf("GET messages: %v", err)
	}
	assertStatus(t, messagesResp, http.StatusOK)
	messagesBody := decodeBody[sessionMessagesResponse](t, messagesResp)
	if len(messagesBody.Messages) != 1 || messagesBody.Messages[0].Text != "hello" || messagesBody.NextPageToken != "page-2" {
		t.Fatalf("unexpected messages body: %#v", messagesBody)
	}
	if service.getMessagesQuery != (domain.SessionMessageQuery{
		AgentName: "assistant",
		ThreadID:  "thread-1",
		Mode:      domain.SessionHistoryModeResumeView,
		PageSize:  20,
		PageToken: "page-1",
	}) {
		t.Fatalf("unexpected messages input: %#v", service)
	}

	latestResp, err := http.Get(server.URL + "/api/v1/sessions/latest?agent_name=assistant")
	if err != nil {
		t.Fatalf("GET latest session: %v", err)
	}
	assertStatus(t, latestResp, http.StatusOK)
	latestBody := decodeBody[sessionSummaryResponse](t, latestResp)
	if latestBody.ThreadID != "thread-9" || service.getLatestAgentName != "assistant" {
		t.Fatalf("unexpected latest session body or input: %#v %#v", latestBody, service)
	}

	deleteReq, err := http.NewRequest(http.MethodDelete, server.URL+"/api/v1/sessions/thread-1?agent_name=assistant", nil)
	if err != nil {
		t.Fatalf("NewRequest delete: %v", err)
	}
	deleteResp, err := http.DefaultClient.Do(deleteReq)
	if err != nil {
		t.Fatalf("DELETE session: %v", err)
	}
	assertStatus(t, deleteResp, http.StatusNoContent)
	deleteResp.Body.Close()
	if service.deleteLocator != (domain.SessionLocator{AgentName: "assistant", ThreadID: "thread-1"}) {
		t.Fatalf("unexpected delete input: %#v", service)
	}
}

func TestHTTPHandlerDelegatesResourceCRUD(t *testing.T) {
	service := &fakeAgentService{
		upsertModelResp: domain.ModelConfig{
			Name:        "default-openai",
			Description: "default openai model",
			Spec: domain.ModelSpec{
				Provider:    "openai",
				Model:       "gpt-5",
				BaseURL:     "https://api.openai.com/v1",
				APIKeyEnv:   "OPENAI_API_KEY",
				ExtraParams: map[string]string{"temperature": "0.2"},
			},
			Status: domain.AuthoredStatusPublished,
		},
		getModelResp:   domain.ModelConfig{Name: "default-openai", Spec: domain.ModelSpec{Provider: "openai", Model: "gpt-5"}},
		listModelsResp: []domain.ModelConfig{{Name: "default-openai"}},
		listModelsPage: domain.ResourcePage[domain.ModelConfig]{
			Items: []domain.ModelConfig{{Name: "default-openai"}},
			PageMetadata: domain.PageMetadata{
				PageSize:   1,
				PageNumber: 2,
				TotalSize:  3,
				TotalPages: 3,
			},
		},
		upsertSkillResp: domain.Skill{
			Name:        "research",
			Description: "research skill",
			Tags:        []string{"web"},
			Content:     "# SKILL",
			Files:       []domain.SkillFile{{Path: "scripts/run.sh", Content: "echo hi"}},
			Status:      domain.AuthoredStatusPublished,
		},
		getSkillResp:   domain.Skill{Name: "research", Description: "research skill"},
		listSkillsResp: []domain.Skill{{Name: "research"}},
		listSkillsPage: domain.ResourcePage[domain.Skill]{
			Items: []domain.Skill{{Name: "research"}},
			PageMetadata: domain.PageMetadata{
				PageSize:   1,
				PageNumber: 2,
				TotalSize:  3,
				TotalPages: 3,
			},
		},
		upsertMCPResp: domain.MCPConfig{
			Name:      "github",
			Command:   "npx",
			Args:      []string{"server-github"},
			Env:       map[string]string{"GITHUB_TOKEN": "env:GITHUB_TOKEN"},
			Transport: "stdio",
			Status:    domain.AuthoredStatusPublished,
		},
		getMCPResp:   domain.MCPConfig{Name: "github", Command: "npx"},
		listMCPsResp: []domain.MCPConfig{{Name: "github"}},
		listMCPsPage: domain.ResourcePage[domain.MCPConfig]{
			Items: []domain.MCPConfig{{Name: "github"}},
			PageMetadata: domain.PageMetadata{
				PageSize:   1,
				PageNumber: 2,
				TotalSize:  3,
				TotalPages: 3,
			},
		},
		upsertAgentResp: domain.AuthoredAgentSpec{
			Name:      "assistant",
			Version:   "1.0.0",
			ModelRef:  "default-openai",
			Prompt:    domain.PromptSpec{System: "You are helpful."},
			SkillRefs: []string{"research"},
			MCPRefs:   []string{"github"},
			Status:    domain.AuthoredStatusPublished,
		},
		getAgentResp:   domain.AuthoredAgentSpec{Name: "assistant", ModelRef: "default-openai"},
		listAgentsResp: []domain.AuthoredAgentSpec{{Name: "assistant", ModelRef: "default-openai"}},
		listAgentsPage: domain.ResourcePage[domain.AuthoredAgentSpec]{
			Items: []domain.AuthoredAgentSpec{{Name: "assistant", ModelRef: "default-openai"}},
			PageMetadata: domain.PageMetadata{
				PageSize:   1,
				PageNumber: 2,
				TotalSize:  3,
				TotalPages: 3,
			},
		},
	}
	handler, err := NewHTTPHandler(service, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	modelReq, err := http.NewRequest(
		http.MethodPut,
		server.URL+"/api/v1/models/default-openai",
		strings.NewReader(`{"description":"default openai model","provider":"openai","model":"gpt-5","base_url":"https://api.openai.com/v1","api_key_env":"OPENAI_API_KEY","extra_params":{"temperature":"0.2"},"status":"published"}`),
	)
	if err != nil {
		t.Fatalf("NewRequest model: %v", err)
	}
	modelReq.Header.Set("Content-Type", "application/json")
	modelResp, err := http.DefaultClient.Do(modelReq)
	if err != nil {
		t.Fatalf("PUT model: %v", err)
	}
	assertStatus(t, modelResp, http.StatusOK)
	modelBody, modelRaw := decodeBodyWithRaw[modelConfigResponse](t, modelResp)
	if modelBody.Name != "default-openai" || service.upsertModelReq.Name != "default-openai" || service.upsertModelReq.Spec.Model != "gpt-5" {
		t.Fatalf("unexpected model body or input: %#v %#v", modelBody, service.upsertModelReq)
	}
	if !strings.Contains(modelRaw, `"name":"default-openai"`) || strings.Contains(modelRaw, `"Name"`) {
		t.Fatalf("expected snake_case model response, got %s", modelRaw)
	}

	modelsResp, err := http.Get(server.URL + "/api/v1/models?page_size=1&page_number=2")
	if err != nil {
		t.Fatalf("GET models: %v", err)
	}
	assertStatus(t, modelsResp, http.StatusOK)
	modelsBody := decodeBody[modelConfigsListResponse](t, modelsResp)
	if len(modelsBody.Models) != 1 || modelsBody.Models[0].Name != "default-openai" ||
		modelsBody.PageSize != 1 || modelsBody.PageNumber != 2 ||
		modelsBody.TotalSize != 3 || modelsBody.TotalPages != 3 {
		t.Fatalf("unexpected models body: %#v", modelsBody)
	}
	if service.listModelsQuery != (domain.PageQuery{PageSize: 1, PageNumber: 2}) {
		t.Fatalf("unexpected model page query: %#v", service.listModelsQuery)
	}

	getModelResp, err := http.Get(server.URL + "/api/v1/models/default-openai")
	if err != nil {
		t.Fatalf("GET model: %v", err)
	}
	assertStatus(t, getModelResp, http.StatusOK)
	if decodeBody[modelConfigResponse](t, getModelResp).Name != "default-openai" || service.getModelName != "default-openai" {
		t.Fatalf("unexpected get model input: %#v", service)
	}

	deleteModelReq, err := http.NewRequest(http.MethodDelete, server.URL+"/api/v1/models/default-openai", nil)
	if err != nil {
		t.Fatalf("NewRequest delete model: %v", err)
	}
	deleteModelResp, err := http.DefaultClient.Do(deleteModelReq)
	if err != nil {
		t.Fatalf("DELETE model: %v", err)
	}
	assertStatus(t, deleteModelResp, http.StatusNoContent)
	deleteModelResp.Body.Close()
	if service.deleteModelName != "default-openai" {
		t.Fatalf("unexpected delete model input: %#v", service)
	}

	skillReq, err := http.NewRequest(
		http.MethodPut,
		server.URL+"/api/v1/skills/research",
		strings.NewReader(`{"description":"research skill","tags":["web"],"content":"# SKILL","files":[{"path":"scripts/run.sh","content":"echo hi"}],"status":"published"}`),
	)
	if err != nil {
		t.Fatalf("NewRequest skill: %v", err)
	}
	skillReq.Header.Set("Content-Type", "application/json")
	skillResp, err := http.DefaultClient.Do(skillReq)
	if err != nil {
		t.Fatalf("PUT skill: %v", err)
	}
	assertStatus(t, skillResp, http.StatusOK)
	skillBody, skillRaw := decodeBodyWithRaw[skillResponse](t, skillResp)
	if skillBody.Name != "research" || service.upsertSkillReq.Name != "research" || len(service.upsertSkillReq.Files) != 1 {
		t.Fatalf("unexpected skill body or input: %#v %#v", skillBody, service.upsertSkillReq)
	}
	if !strings.Contains(skillRaw, `"name":"research"`) || strings.Contains(skillRaw, `"Name"`) {
		t.Fatalf("expected snake_case skill response, got %s", skillRaw)
	}

	skillsResp, err := http.Get(server.URL + "/api/v1/skills?page_size=1&page_number=2")
	if err != nil {
		t.Fatalf("GET skills: %v", err)
	}
	assertStatus(t, skillsResp, http.StatusOK)
	skillsBody := decodeBody[skillsListResponse](t, skillsResp)
	if len(skillsBody.Skills) != 1 || skillsBody.Skills[0].Name != "research" ||
		skillsBody.PageSize != 1 || skillsBody.PageNumber != 2 ||
		skillsBody.TotalSize != 3 || skillsBody.TotalPages != 3 {
		t.Fatalf("unexpected skills body: %#v", skillsBody)
	}
	if service.listSkillsQuery != (domain.PageQuery{PageSize: 1, PageNumber: 2}) {
		t.Fatalf("unexpected skill page query: %#v", service.listSkillsQuery)
	}

	getSkillResp, err := http.Get(server.URL + "/api/v1/skills/research")
	if err != nil {
		t.Fatalf("GET skill: %v", err)
	}
	assertStatus(t, getSkillResp, http.StatusOK)
	if decodeBody[skillResponse](t, getSkillResp).Name != "research" || service.getSkillName != "research" {
		t.Fatalf("unexpected get skill input: %#v", service)
	}

	deleteSkillReq, err := http.NewRequest(http.MethodDelete, server.URL+"/api/v1/skills/research", nil)
	if err != nil {
		t.Fatalf("NewRequest delete skill: %v", err)
	}
	deleteSkillResp, err := http.DefaultClient.Do(deleteSkillReq)
	if err != nil {
		t.Fatalf("DELETE skill: %v", err)
	}
	assertStatus(t, deleteSkillResp, http.StatusNoContent)
	deleteSkillResp.Body.Close()
	if service.deleteSkillName != "research" {
		t.Fatalf("unexpected delete skill input: %#v", service)
	}

	mcpReq, err := http.NewRequest(
		http.MethodPut,
		server.URL+"/api/v1/mcps/github",
		strings.NewReader(`{"command":"npx","args":["server-github"],"env":{"GITHUB_TOKEN":"env:GITHUB_TOKEN"},"transport":"stdio","status":"published"}`),
	)
	if err != nil {
		t.Fatalf("NewRequest mcp: %v", err)
	}
	mcpReq.Header.Set("Content-Type", "application/json")
	mcpResp, err := http.DefaultClient.Do(mcpReq)
	if err != nil {
		t.Fatalf("PUT mcp: %v", err)
	}
	assertStatus(t, mcpResp, http.StatusOK)
	if decodeBody[mcpConfigResponse](t, mcpResp).Name != "github" || service.upsertMCPReq.Name != "github" {
		t.Fatalf("unexpected mcp upsert input: %#v", service)
	}

	listMCPResp, err := http.Get(server.URL + "/api/v1/mcps?page_size=1&page_number=2")
	if err != nil {
		t.Fatalf("GET mcps: %v", err)
	}
	assertStatus(t, listMCPResp, http.StatusOK)
	listMCPBody := decodeBody[mcpConfigsListResponse](t, listMCPResp)
	if len(listMCPBody.MCPs) != 1 || listMCPBody.PageSize != 1 || listMCPBody.PageNumber != 2 ||
		listMCPBody.TotalSize != 3 || listMCPBody.TotalPages != 3 {
		t.Fatalf("unexpected mcp list body: %#v", listMCPBody)
	}
	if service.listMCPsQuery != (domain.PageQuery{PageSize: 1, PageNumber: 2}) {
		t.Fatalf("unexpected mcp page query: %#v", service.listMCPsQuery)
	}

	getMCPResp, err := http.Get(server.URL + "/api/v1/mcps/github")
	if err != nil {
		t.Fatalf("GET mcp: %v", err)
	}
	assertStatus(t, getMCPResp, http.StatusOK)
	if decodeBody[mcpConfigResponse](t, getMCPResp).Name != "github" || service.getMCPName != "github" {
		t.Fatalf("unexpected get mcp input: %#v", service)
	}

	deleteMCPReq, err := http.NewRequest(http.MethodDelete, server.URL+"/api/v1/mcps/github", nil)
	if err != nil {
		t.Fatalf("NewRequest delete mcp: %v", err)
	}
	deleteMCPResp, err := http.DefaultClient.Do(deleteMCPReq)
	if err != nil {
		t.Fatalf("DELETE mcp: %v", err)
	}
	assertStatus(t, deleteMCPResp, http.StatusNoContent)
	deleteMCPResp.Body.Close()
	if service.deleteMCPName != "github" {
		t.Fatalf("unexpected delete mcp input: %#v", service)
	}

	agentReq, err := http.NewRequest(
		http.MethodPut,
		server.URL+"/api/v1/agents/assistant",
		strings.NewReader(`{"version":"1.0.0","model_ref":"default-openai","prompt":{"system":"You are helpful."},"skill_refs":["research"],"mcp_refs":["github"],"status":"published"}`),
	)
	if err != nil {
		t.Fatalf("NewRequest agent: %v", err)
	}
	agentReq.Header.Set("Content-Type", "application/json")
	agentResp, err := http.DefaultClient.Do(agentReq)
	if err != nil {
		t.Fatalf("PUT agent: %v", err)
	}
	assertStatus(t, agentResp, http.StatusOK)
	agentBody, agentRaw := decodeBodyWithRaw[agentSpecResponse](t, agentResp)
	if agentBody.Name != "assistant" || agentBody.ModelRef != "default-openai" || service.upsertAgentReq.Name != "assistant" || service.upsertAgentReq.ModelRef != "default-openai" {
		t.Fatalf("unexpected agent body or input: %#v %#v", agentBody, service.upsertAgentReq)
	}
	if !strings.Contains(agentRaw, `"name":"assistant"`) || strings.Contains(agentRaw, `"WorkspaceName"`) || strings.Contains(agentRaw, `"workspace_name"`) {
		t.Fatalf("expected snake_case agent response, got %s", agentRaw)
	}

	listAgentsResp, err := http.Get(server.URL + "/api/v1/agents?page_size=1&page_number=2")
	if err != nil {
		t.Fatalf("GET agents: %v", err)
	}
	assertStatus(t, listAgentsResp, http.StatusOK)
	listAgentsBody := decodeBody[agentSpecsListResponse](t, listAgentsResp)
	if len(listAgentsBody.Agents) != 1 || listAgentsBody.PageSize != 1 || listAgentsBody.PageNumber != 2 ||
		listAgentsBody.TotalSize != 3 || listAgentsBody.TotalPages != 3 {
		t.Fatalf("unexpected agent list body: %#v", listAgentsBody)
	}
	if service.listAgentsQuery != (domain.PageQuery{PageSize: 1, PageNumber: 2}) {
		t.Fatalf("unexpected agent page query: %#v", service.listAgentsQuery)
	}

	getAgentResp, err := http.Get(server.URL + "/api/v1/agents/assistant")
	if err != nil {
		t.Fatalf("GET agent: %v", err)
	}
	assertStatus(t, getAgentResp, http.StatusOK)
	if body := decodeBody[agentSpecResponse](t, getAgentResp); body.Name != "assistant" || body.ModelRef != "default-openai" || service.getAgentName != "assistant" {
		t.Fatalf("unexpected get agent input: %#v", service)
	}

	deleteAgentReq, err := http.NewRequest(http.MethodDelete, server.URL+"/api/v1/agents/assistant", nil)
	if err != nil {
		t.Fatalf("NewRequest delete agent: %v", err)
	}
	deleteAgentResp, err := http.DefaultClient.Do(deleteAgentReq)
	if err != nil {
		t.Fatalf("DELETE agent: %v", err)
	}
	assertStatus(t, deleteAgentResp, http.StatusNoContent)
	deleteAgentResp.Body.Close()
	if service.deleteAgentName != "assistant" {
		t.Fatalf("unexpected delete agent input: %#v", service)
	}
}

func TestHTTPHandlerReturnsBadRequestForInvalidSessionQuery(t *testing.T) {
	handler, err := NewHTTPHandler(&fakeAgentService{}, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	resp, err := http.Get(server.URL + "/api/v1/sessions?page_size=abc")
	if err != nil {
		t.Fatalf("GET sessions: %v", err)
	}
	assertStatus(t, resp, http.StatusBadRequest)
	body := decodeBody[errorResponse](t, resp)
	if !strings.Contains(body.Error, "page_size") {
		t.Fatalf("unexpected error body: %#v", body)
	}
}

func TestHTTPHandlerReturnsBadRequestForInvalidResourcePageQuery(t *testing.T) {
	handler, err := NewHTTPHandler(&fakeAgentService{}, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	resp, err := http.Get(server.URL + "/api/v1/models?page_number=abc")
	if err != nil {
		t.Fatalf("GET models: %v", err)
	}
	assertStatus(t, resp, http.StatusBadRequest)
	body := decodeBody[errorResponse](t, resp)
	if !strings.Contains(body.Error, "page_number") {
		t.Fatalf("unexpected error body: %#v", body)
	}
}

func TestHTTPHandlerRequiresAgentNameForThreadScopedSessionQuery(t *testing.T) {
	handler, err := NewHTTPHandler(&fakeAgentService{}, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	resp, err := http.Get(server.URL + "/api/v1/sessions/thread-1")
	if err != nil {
		t.Fatalf("GET session: %v", err)
	}
	assertStatus(t, resp, http.StatusBadRequest)
	body := decodeBody[errorResponse](t, resp)
	if !strings.Contains(body.Error, "agent_name") {
		t.Fatalf("unexpected error body: %#v", body)
	}
}

func TestHTTPHandlerMapsServiceNotFoundTo404(t *testing.T) {
	service := &fakeAgentService{
		getSessionErr: registrypkg.ErrNotFound,
	}
	handler, err := NewHTTPHandler(service, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	resp, err := http.Get(server.URL + "/api/v1/sessions/thread-404?agent_name=assistant")
	if err != nil {
		t.Fatalf("GET session: %v", err)
	}
	assertStatus(t, resp, http.StatusNotFound)
	resp.Body.Close()
}

func TestHTTPHandlerMapsRegistryConflictTo409(t *testing.T) {
	service := &fakeAgentService{
		deleteSkillErr: registrypkg.ErrConflict,
	}
	handler, err := NewHTTPHandler(service, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	req, err := http.NewRequest(http.MethodDelete, server.URL+"/api/v1/skills/research", nil)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("DELETE skill: %v", err)
	}
	assertStatus(t, resp, http.StatusConflict)
	resp.Body.Close()
}

func TestHTTPHandlerMapsRegistryInvalidTo400(t *testing.T) {
	service := &fakeAgentService{
		upsertAgentErr: registrypkg.ErrInvalid,
	}
	handler, err := NewHTTPHandler(service, nil)
	if err != nil {
		t.Fatalf("NewHTTPHandler: %v", err)
	}

	server := httptest.NewServer(handler)
	defer server.Close()

	req, err := http.NewRequest(
		http.MethodPut,
		server.URL+"/api/v1/agents/assistant",
		strings.NewReader(`{"version":"1.0.0","model_ref":"default-openai","prompt":{"system":"You are helpful."},"skill_refs":["research"],"status":"published"}`),
	)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("PUT agent: %v", err)
	}
	assertStatus(t, resp, http.StatusBadRequest)
	resp.Body.Close()
}

func waitForSignal(t *testing.T, signal <-chan struct{}, name string) {
	t.Helper()

	select {
	case <-signal:
	case <-time.After(2 * time.Second):
		t.Fatalf("timed out waiting for %s signal", name)
	}
}

func assertStatus(t *testing.T, resp *http.Response, want int) {
	t.Helper()

	if resp.StatusCode != want {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("unexpected status: got=%d want=%d body=%s", resp.StatusCode, want, string(body))
	}
}

func decodeBody[T any](t *testing.T, resp *http.Response) T {
	t.Helper()
	value, _ := decodeBodyWithRaw[T](t, resp)
	return value
}

func decodeBodyWithRaw[T any](t *testing.T, resp *http.Response) (T, string) {
	t.Helper()
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}

	var value T
	if err := json.Unmarshal(body, &value); err != nil {
		t.Fatalf("decode body %s: %v", string(body), err)
	}
	return value, string(body)
}
