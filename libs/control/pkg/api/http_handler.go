package api

import (
	"agentctl/pkg/domain"
	"agentctl/pkg/orchestrator"
	registrypkg "agentctl/pkg/registry"
	"agentctl/pkg/runtimeclient"
	"agentctl/pkg/skillpackage"
	"agentctl/pkg/streamproxy"
	"agentctl/pkg/telemetry"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/gin-contrib/sse"
	"github.com/gin-gonic/gin"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

const runSessionHeader = "X-Deepagents-Run-Session-ID"

var (
	errRunSessionNotFound = errors.New("run session not found")
	errRunSessionClosed   = errors.New("run session is closed")
	errRunSessionBusy     = errors.New("run session control queue is full")
)

// HTTPHandler exposes the northbound HTTP/SSE transport.
type HTTPHandler struct {
	service     AgentService
	newProxy    func() streamproxy.Proxy
	runSessions *runSessionRegistry
	engine      *gin.Engine
}

// NewHTTPHandler creates a new HTTP/SSE northbound handler.
func NewHTTPHandler(
	service AgentService,
	proxyFactory func() streamproxy.Proxy,
) (*HTTPHandler, error) {
	if service == nil {
		return nil, errors.New("api service must not be nil")
	}
	if proxyFactory == nil {
		proxyFactory = func() streamproxy.Proxy {
			return streamproxy.NewDefaultProxy(nil)
		}
	}
	if gin.Mode() == gin.DebugMode && strings.TrimSpace(os.Getenv(gin.EnvGinMode)) == "" {
		gin.SetMode(gin.ReleaseMode)
	}

	handler := &HTTPHandler{
		service:     service,
		newProxy:    proxyFactory,
		runSessions: newRunSessionRegistry(),
		engine:      gin.New(),
	}
	handler.registerRoutes()
	return handler, nil
}

// Handler returns the underlying HTTP handler.
func (h *HTTPHandler) Handler() http.Handler {
	return h.engine
}

// ServeHTTP dispatches one northbound HTTP request.
func (h *HTTPHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h.engine.ServeHTTP(w, r)
}

func (h *HTTPHandler) registerRoutes() {
	api := h.engine.Group("/api/v1")

	h.registerLifecycleRoutes(api)
	h.registerRunRoutes(api)
	h.registerTelemetryRoutes(api)
	h.registerSessionRoutes(api)
	h.registerResourceRoutes(api)
}

func prepareSSEHeaders(w http.ResponseWriter, sessionID string) {
	w.Header().Set("Content-Type", sse.ContentType)
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.Header().Set(runSessionHeader, sessionID)
	w.WriteHeader(http.StatusOK)
	if flusher, ok := w.(http.Flusher); ok {
		flusher.Flush()
	}
}

type runSessionRegistry struct {
	mu       sync.RWMutex
	sessions map[string]*sseRunDownstream
}

func newRunSessionRegistry() *runSessionRegistry {
	return &runSessionRegistry{
		sessions: make(map[string]*sseRunDownstream),
	}
}

func (r *runSessionRegistry) Store(sessionID string, downstream *sseRunDownstream) {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.sessions[sessionID] = downstream
}

func (r *runSessionRegistry) Load(sessionID string) (*sseRunDownstream, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	downstream, ok := r.sessions[sessionID]
	if !ok {
		return nil, errRunSessionNotFound
	}
	return downstream, nil
}

func (r *runSessionRegistry) Delete(sessionID string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	delete(r.sessions, sessionID)
}

type sseRunDownstream struct {
	writer    http.ResponseWriter
	flusher   http.Flusher
	writeMu   sync.Mutex
	controlMu sync.Mutex
	closed    bool

	decisions chan streamproxy.DecisionEnvelope
	cancels   chan streamproxy.CancelSignal
}

type telemetryEventRecorder interface {
	RecordTelemetryEvent(ctx context.Context, event runtimeclient.TelemetryEvent) error
}

type recordingTelemetryDownstream struct {
	downstream *sseRunDownstream
	recorder   telemetryEventRecorder
}

func newSSERunDownstream(w http.ResponseWriter) (*sseRunDownstream, error) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		return nil, errors.New("response writer must support flushing")
	}

	return &sseRunDownstream{
		writer:    w,
		flusher:   flusher,
		decisions: make(chan streamproxy.DecisionEnvelope, 8),
		cancels:   make(chan streamproxy.CancelSignal, 8),
	}, nil
}

func (d *sseRunDownstream) SendEvent(ctx context.Context, event runtimeclient.AgentEvent) error {
	return d.SendEnvelope(ctx, string(event.Type), newHTTPAgentEvent(event))
}

func (d *sseRunDownstream) SendTelemetryEvent(ctx context.Context, event runtimeclient.TelemetryEvent) error {
	return d.SendEnvelope(ctx, event.EventType, newHTTPTelemetryEvent(event))
}

func (d *sseRunDownstream) SendEnvelope(ctx context.Context, eventName string, value any) error {
	if err := ctx.Err(); err != nil {
		return err
	}

	d.writeMu.Lock()
	defer d.writeMu.Unlock()

	if err := sse.Encode(d.writer, sse.Event{
		Event: eventName,
		Data:  value,
	}); err != nil {
		return fmt.Errorf("encode sse payload: %w", err)
	}
	d.flusher.Flush()
	return nil
}

func (d *sseRunDownstream) HITLDecisions() <-chan streamproxy.DecisionEnvelope {
	return d.decisions
}

func (d *sseRunDownstream) CancelRequests() <-chan streamproxy.CancelSignal {
	return d.cancels
}

func (d *recordingTelemetryDownstream) SendTelemetryEvent(
	ctx context.Context,
	event runtimeclient.TelemetryEvent,
) error {
	if d.recorder != nil {
		if err := d.recorder.RecordTelemetryEvent(ctx, event); err != nil {
			return err
		}
	}
	return d.downstream.SendTelemetryEvent(ctx, event)
}

func (d *recordingTelemetryDownstream) HITLDecisions() <-chan streamproxy.DecisionEnvelope {
	return d.downstream.HITLDecisions()
}

func (d *recordingTelemetryDownstream) CancelRequests() <-chan streamproxy.CancelSignal {
	return d.downstream.CancelRequests()
}

func (d *sseRunDownstream) EnqueueDecision(decision streamproxy.DecisionEnvelope) error {
	d.controlMu.Lock()
	defer d.controlMu.Unlock()

	if d.closed {
		return errRunSessionClosed
	}

	select {
	case d.decisions <- decision:
		return nil
	default:
		return errRunSessionBusy
	}
}

func (d *sseRunDownstream) EnqueueCancel(signal streamproxy.CancelSignal) error {
	d.controlMu.Lock()
	defer d.controlMu.Unlock()

	if d.closed {
		return errRunSessionClosed
	}

	select {
	case d.cancels <- signal:
		return nil
	default:
		return errRunSessionBusy
	}
}

func (d *sseRunDownstream) Close() {
	d.controlMu.Lock()
	defer d.controlMu.Unlock()

	if d.closed {
		return
	}
	d.closed = true
	close(d.decisions)
	close(d.cancels)
}

type runStreamRequest struct {
	Message  string            `json:"message"`
	ThreadID string            `json:"thread_id,omitempty"`
	Metadata map[string]string `json:"metadata,omitempty"`
}

type workspaceUploadFileResponse struct {
	Path  string `json:"path,omitempty"`
	Error string `json:"error,omitempty"`
}

type workspaceUploadResponse struct {
	ThreadID string                        `json:"thread_id,omitempty"`
	Files    []workspaceUploadFileResponse `json:"files"`
}

type workspaceDownloadFileResponse struct {
	Path          string `json:"path,omitempty"`
	ContentBase64 string `json:"content_base64,omitempty"`
	Error         string `json:"error,omitempty"`
}

type workspaceDownloadResponse struct {
	ThreadID string                          `json:"thread_id,omitempty"`
	Files    []workspaceDownloadFileResponse `json:"files"`
}

type workspaceFileInfoResponse struct {
	Path       string `json:"path,omitempty"`
	IsDir      bool   `json:"is_dir,omitempty"`
	Size       int64  `json:"size,omitempty"`
	ModifiedAt string `json:"modified_at,omitempty"`
}

type workspaceListResponse struct {
	ThreadID string                      `json:"thread_id,omitempty"`
	Files    []workspaceFileInfoResponse `json:"files"`
}

type threadArtifactResponse struct {
	ID            string `json:"id,omitempty"`
	Type          string `json:"type,omitempty"`
	Path          string `json:"path,omitempty"`
	Title         string `json:"title,omitempty"`
	ContentType   string `json:"content_type,omitempty"`
	Language      string `json:"language,omitempty"`
	CreatedByTool string `json:"created_by_tool,omitempty"`
	CreatedAt     string `json:"created_at,omitempty"`
	ModifiedAt    string `json:"modified_at,omitempty"`
	Size          int64  `json:"size,omitempty"`
}

type listArtifactsResponse struct {
	ThreadID  string                   `json:"thread_id,omitempty"`
	Artifacts []threadArtifactResponse `json:"artifacts"`
}

type cancelRequest struct {
	Reason string `json:"reason,omitempty"`
}

type hitlDecisionRequest struct {
	InterruptID string            `json:"interrupt_id"`
	Decisions   []decisionRequest `json:"decisions"`
}

type decisionRequest struct {
	Type         string              `json:"type"`
	Message      string              `json:"message,omitempty"`
	EditedAction *httpDecisionAction `json:"edited_action,omitempty"`
}

type errorResponse struct {
	Error string `json:"error"`
}

type httpAgentEvent struct {
	Type           string              `json:"type"`
	RunID          string              `json:"run_id,omitempty"`
	AgentName      string              `json:"agent_name,omitempty"`
	Timestamp      string              `json:"timestamp,omitempty"`
	ThreadID       string              `json:"thread_id,omitempty"`
	Text           string              `json:"text,omitempty"`
	ToolName       string              `json:"tool_name,omitempty"`
	ToolCallID     string              `json:"tool_call_id,omitempty"`
	InterruptID    string              `json:"interrupt_id,omitempty"`
	Reason         string              `json:"reason,omitempty"`
	ErrorMessage   string              `json:"error_message,omitempty"`
	Payload        json.RawMessage     `json:"payload,omitempty"`
	ActionRequests []httpActionRequest `json:"action_requests,omitempty"`
	ReviewConfigs  []httpReviewConfig  `json:"review_configs,omitempty"`
}

type httpTelemetryEvent struct {
	RunID       string          `json:"run_id,omitempty"`
	AgentName   string          `json:"agent_name,omitempty"`
	Timestamp   string          `json:"timestamp,omitempty"`
	EventID     string          `json:"event_id,omitempty"`
	Attempt     int32           `json:"attempt,omitempty"`
	Seq         int64           `json:"seq,omitempty"`
	Namespace   []string        `json:"namespace,omitempty"`
	StreamMode  string          `json:"stream_mode,omitempty"`
	EventType   string          `json:"event_type,omitempty"`
	NodeName    string          `json:"node_name,omitempty"`
	TaskID      string          `json:"task_id,omitempty"`
	ModelCallID string          `json:"model_call_id,omitempty"`
	ToolCallID  string          `json:"tool_call_id,omitempty"`
	InterruptID string          `json:"interrupt_id,omitempty"`
	MessageID   string          `json:"message_id,omitempty"`
	Metadata    json.RawMessage `json:"metadata,omitempty"`
	Payload     json.RawMessage `json:"payload,omitempty"`
	PublicEvent json.RawMessage `json:"public_event,omitempty"`
}

type telemetryRunResponse struct {
	RunID            string          `json:"run_id,omitempty"`
	AgentName        string          `json:"agent_name,omitempty"`
	ThreadID         string          `json:"thread_id,omitempty"`
	RuntimeTarget    string          `json:"runtime_target,omitempty"`
	Status           string          `json:"status,omitempty"`
	RequestMetadata  json.RawMessage `json:"request_metadata,omitempty"`
	TraceContext     json.RawMessage `json:"trace_context,omitempty"`
	GraphSnapshotID  string          `json:"graph_snapshot_id,omitempty"`
	ReasoningSummary string          `json:"reasoning_summary,omitempty"`
	NodeStepCount    int32           `json:"node_step_count,omitempty"`
	ModelStepCount   int32           `json:"model_step_count,omitempty"`
	ToolStepCount    int32           `json:"tool_step_count,omitempty"`
	HitlWaitCount    int32           `json:"hitl_wait_count,omitempty"`
	ErrorCount       int32           `json:"error_count,omitempty"`
	EventCount       int32           `json:"event_count,omitempty"`
	StartedAt        string          `json:"started_at,omitempty"`
	FinishedAt       string          `json:"finished_at,omitempty"`
	LastEventAt      string          `json:"last_event_at,omitempty"`
	CreatedAt        string          `json:"created_at,omitempty"`
	UpdatedAt        string          `json:"updated_at,omitempty"`
}

type telemetryStepResponse struct {
	StepID          string            `json:"step_id,omitempty"`
	RunID           string            `json:"run_id,omitempty"`
	ParentStepID    string            `json:"parent_step_id,omitempty"`
	Kind            string            `json:"kind,omitempty"`
	Title           string            `json:"title,omitempty"`
	Namespace       []string          `json:"namespace,omitempty"`
	Status          string            `json:"status,omitempty"`
	StartedAt       string            `json:"started_at,omitempty"`
	FinishedAt      string            `json:"finished_at,omitempty"`
	Depth           int32             `json:"depth,omitempty"`
	Step            int32             `json:"step,omitempty"`
	Input           json.RawMessage   `json:"input,omitempty"`
	Output          json.RawMessage   `json:"output,omitempty"`
	Error           string            `json:"error,omitempty"`
	Triggers        []string          `json:"triggers,omitempty"`
	Reasoning       []string          `json:"reasoning,omitempty"`
	Messages        []string          `json:"messages,omitempty"`
	Updates         []json.RawMessage `json:"updates,omitempty"`
	Custom          []json.RawMessage `json:"custom,omitempty"`
	RelatedEventIDs []string          `json:"related_event_ids,omitempty"`
	Order           int32             `json:"order,omitempty"`
	Synthetic       bool              `json:"synthetic,omitempty"`
}

type httpActionRequest struct {
	Name        string          `json:"name"`
	Description string          `json:"description,omitempty"`
	Arguments   json.RawMessage `json:"arguments,omitempty"`
}

type httpDecisionAction struct {
	Name      string          `json:"name"`
	Arguments json.RawMessage `json:"arguments,omitempty"`
}

type httpReviewConfig struct {
	ActionName       string          `json:"action_name"`
	AllowedDecisions []string        `json:"allowed_decisions,omitempty"`
	ArgsSchema       json.RawMessage `json:"args_schema,omitempty"`
}

type decodedHITLDecisionRequest struct {
	InterruptID string
	Decisions   []runtimeclient.ToolDecision
}

type healthResponse struct {
	Status              string  `json:"status,omitempty"`
	AssembledAgentCount int32   `json:"assembled_agent_count,omitempty"`
	InstalledAgentCount int32   `json:"installed_agent_count,omitempty"`
	RunningAgentCount   int32   `json:"running_agent_count,omitempty"`
	UptimeSeconds       float32 `json:"uptime_seconds,omitempty"`
	Ready               bool    `json:"ready"`
}

type sessionSummaryResponse struct {
	ThreadID           string `json:"thread_id,omitempty"`
	AgentName          string `json:"agent_name,omitempty"`
	LatestCheckpointID string `json:"latest_checkpoint_id,omitempty"`
	MessageCount       int32  `json:"message_count,omitempty"`
	CheckpointCount    int32  `json:"checkpoint_count,omitempty"`
	InitialPrompt      string `json:"initial_prompt,omitempty"`
	HistoryMode        string `json:"history_mode,omitempty"`
	AgentStatus        string `json:"agent_status,omitempty"`
	UpdatedAt          string `json:"updated_at,omitempty"`
}

type sessionMessageResponse struct {
	Index        int32           `json:"index,omitempty"`
	CheckpointID string          `json:"checkpoint_id,omitempty"`
	Role         string          `json:"role,omitempty"`
	Text         string          `json:"text,omitempty"`
	Content      string          `json:"content,omitempty"`
	ToolCallID   string          `json:"tool_call_id,omitempty"`
	ToolName     string          `json:"tool_name,omitempty"`
	IsError      bool            `json:"is_error,omitempty"`
	Raw          json.RawMessage `json:"raw,omitempty"`
	CreatedAt    string          `json:"created_at,omitempty"`
}

type sessionMessagePageResponse struct {
	ThreadID             string                   `json:"thread_id,omitempty"`
	ResolvedCheckpointID string                   `json:"resolved_checkpoint_id,omitempty"`
	ActualMode           string                   `json:"actual_mode,omitempty"`
	TotalMessageCount    int32                    `json:"total_message_count,omitempty"`
	Messages             []sessionMessageResponse `json:"messages"`
	NextPageToken        string                   `json:"next_page_token,omitempty"`
}

type sessionListResponse struct {
	Sessions      []sessionSummaryResponse `json:"sessions"`
	NextPageToken string                   `json:"next_page_token,omitempty"`
}

type sessionMessagesResponse struct {
	Messages      []sessionMessageResponse `json:"messages"`
	NextPageToken string                   `json:"next_page_token,omitempty"`
}

type telemetryRunsListResponse struct {
	Runs []telemetryRunResponse `json:"runs"`
	pageResponse
}

type telemetryStepsListResponse struct {
	Steps []telemetryStepResponse `json:"steps"`
}

type telemetryEventsListResponse struct {
	Events []httpTelemetryEvent `json:"events"`
	pageResponse
}

type pageResponse struct {
	PageSize   int32 `json:"page_size,omitempty"`
	PageNumber int32 `json:"page_number,omitempty"`
	TotalSize  int32 `json:"total_size,omitempty"`
	TotalPages int32 `json:"total_pages,omitempty"`
}

type skillFilePayload struct {
	Path    string `json:"path,omitempty"`
	Content string `json:"content,omitempty"`
}

type skillUpsertRequest struct {
	Description string             `json:"description,omitempty"`
	Tags        []string           `json:"tags,omitempty"`
	Content     string             `json:"content,omitempty"`
	Files       []skillFilePayload `json:"files,omitempty"`
	Status      string             `json:"status,omitempty"`
}

type skillManifestPayload struct {
	Path   string `json:"path,omitempty"`
	Size   int64  `json:"size,omitempty"`
	SHA256 string `json:"sha256,omitempty"`
}

type skillResponse struct {
	Name        string             `json:"name,omitempty"`
	Description string             `json:"description,omitempty"`
	Tags        []string           `json:"tags,omitempty"`
	Content     string             `json:"content,omitempty"`
	Files       []skillFilePayload `json:"files,omitempty"`
	Status      string             `json:"status,omitempty"`
	CreatedAt   string             `json:"created_at,omitempty"`
	UpdatedAt   string             `json:"updated_at,omitempty"`
}

type skillSummaryResponse struct {
	Name           string `json:"name,omitempty"`
	Description    string `json:"description,omitempty"`
	Status         string `json:"status,omitempty"`
	CreatedAt      string `json:"created_at,omitempty"`
	UpdatedAt      string `json:"updated_at,omitempty"`
	License        any    `json:"license,omitempty"`
	Compatibility  any    `json:"compatibility,omitempty"`
	Metadata       any    `json:"metadata,omitempty"`
	AllowedTools   any    `json:"allowed_tools,omitempty"`
	FileCount      int    `json:"file_count,omitempty"`
	SnapshotDigest string `json:"snapshot_digest,omitempty"`
}

type skillDetailResponse struct {
	Name           string                 `json:"name,omitempty"`
	Description    string                 `json:"description,omitempty"`
	Status         string                 `json:"status,omitempty"`
	CreatedAt      string                 `json:"created_at,omitempty"`
	UpdatedAt      string                 `json:"updated_at,omitempty"`
	License        any                    `json:"license,omitempty"`
	Compatibility  any                    `json:"compatibility,omitempty"`
	Metadata       any                    `json:"metadata,omitempty"`
	AllowedTools   any                    `json:"allowed_tools,omitempty"`
	FileCount      int                    `json:"file_count,omitempty"`
	SnapshotDigest string                 `json:"snapshot_digest,omitempty"`
	SkillMD        string                 `json:"skill_md,omitempty"`
	Frontmatter    map[string]any         `json:"frontmatter,omitempty"`
	FileManifest   []skillManifestPayload `json:"file_manifest"`
}

type skillsListResponse struct {
	Skills []skillSummaryResponse `json:"skills"`
	pageResponse
}

type mcpConfigUpsertRequest struct {
	Command     string            `json:"command,omitempty"`
	Args        []string          `json:"args,omitempty"`
	Env         map[string]string `json:"env,omitempty"`
	Transport   string            `json:"transport,omitempty"`
	Description string            `json:"description,omitempty"`
	Status      string            `json:"status,omitempty"`
}

type mcpConfigResponse struct {
	Name        string            `json:"name,omitempty"`
	Command     string            `json:"command,omitempty"`
	Args        []string          `json:"args,omitempty"`
	Env         map[string]string `json:"env,omitempty"`
	Transport   string            `json:"transport,omitempty"`
	Description string            `json:"description,omitempty"`
	Status      string            `json:"status,omitempty"`
	CreatedAt   string            `json:"created_at,omitempty"`
	UpdatedAt   string            `json:"updated_at,omitempty"`
}

type mcpConfigsListResponse struct {
	MCPs []mcpConfigResponse `json:"mcps"`
	pageResponse
}

type modelConfigUpsertRequest struct {
	Description string            `json:"description,omitempty"`
	Provider    string            `json:"provider,omitempty"`
	Model       string            `json:"model,omitempty"`
	BaseURL     string            `json:"base_url,omitempty"`
	APIKey      string            `json:"api_key,omitempty"`
	APIKeyEnv   string            `json:"api_key_env,omitempty"`
	ExtraParams map[string]string `json:"extra_params,omitempty"`
	Status      string            `json:"status,omitempty"`
}

type modelConfigResponse struct {
	Name        string            `json:"name,omitempty"`
	Description string            `json:"description,omitempty"`
	Provider    string            `json:"provider,omitempty"`
	Model       string            `json:"model,omitempty"`
	BaseURL     string            `json:"base_url,omitempty"`
	APIKey      string            `json:"api_key,omitempty"`
	APIKeyEnv   string            `json:"api_key_env,omitempty"`
	ExtraParams map[string]string `json:"extra_params,omitempty"`
	Status      string            `json:"status,omitempty"`
	CreatedAt   string            `json:"created_at,omitempty"`
	UpdatedAt   string            `json:"updated_at,omitempty"`
}

type modelConfigsListResponse struct {
	Models []modelConfigResponse `json:"models"`
	pageResponse
}

type promptSpecPayload struct {
	System string `json:"system,omitempty"`
}

type modelSpecPayload struct {
	Provider    string            `json:"provider,omitempty"`
	Model       string            `json:"model,omitempty"`
	BaseURL     string            `json:"base_url,omitempty"`
	APIKey      string            `json:"api_key,omitempty"`
	APIKeyEnv   string            `json:"api_key_env,omitempty"`
	ExtraParams map[string]string `json:"extra_params,omitempty"`
}

type subagentSpecPayload struct {
	Name         string   `json:"name,omitempty"`
	Description  string   `json:"description,omitempty"`
	SystemPrompt string   `json:"system_prompt,omitempty"`
	ModelRef     string   `json:"model_ref,omitempty"`
	SkillRefs    []string `json:"skill_refs,omitempty"`
}

type sandboxExecutionPolicyPayload struct {
	CommandTimeoutSeconds int32 `json:"command_timeout_seconds,omitempty"`
	SetupTimeoutSeconds   int32 `json:"setup_timeout_seconds,omitempty"`
	StartupTimeoutSeconds int32 `json:"startup_timeout_seconds,omitempty"`
	MaxOutputBytes        int64 `json:"max_output_bytes,omitempty"`
}

type sandboxEnvVarPayload struct {
	Name  string `json:"name,omitempty"`
	Value string `json:"value,omitempty"`
}

type imageReferencePayload struct {
	Reference  string `json:"reference,omitempty"`
	PullPolicy string `json:"pull_policy,omitempty"`
}

type dockerResourceSpecPayload struct {
	CPU       string `json:"cpu,omitempty"`
	Memory    string `json:"memory,omitempty"`
	ShmSize   string `json:"shm_size,omitempty"`
	PidsLimit int64  `json:"pids_limit,omitempty"`
}

type dockerSandboxSpecPayload struct {
	Image     imageReferencePayload     `json:"image"`
	Resources dockerResourceSpecPayload `json:"resources"`
}

type kubernetesResourceRequirementsPayload struct {
	Requests map[string]string `json:"requests,omitempty"`
	Limits   map[string]string `json:"limits,omitempty"`
}

type kubernetesSandboxSpecPayload struct {
	Image     imageReferencePayload                 `json:"image"`
	Resources kubernetesResourceRequirementsPayload `json:"resources"`
}

type sandboxSpecPayload struct {
	Image         string                         `json:"image,omitempty"`
	Resources     map[string]string              `json:"resources,omitempty"`
	Init          []string                       `json:"init,omitempty"`
	Execution     *sandboxExecutionPolicyPayload `json:"execution,omitempty"`
	Env           []sandboxEnvVarPayload         `json:"env,omitempty"`
	SetupCommands []string                       `json:"setup_commands,omitempty"`
	Local         *struct{}                      `json:"local,omitempty"`
	Docker        *dockerSandboxSpecPayload      `json:"docker,omitempty"`
	Kubernetes    *kubernetesSandboxSpecPayload  `json:"kubernetes,omitempty"`
}

type sandboxConfigUpsertRequest struct {
	Description string             `json:"description,omitempty"`
	Spec        sandboxSpecPayload `json:"spec"`
	Status      string             `json:"status,omitempty"`
}

type sandboxConfigResponse struct {
	Name        string             `json:"name,omitempty"`
	Description string             `json:"description,omitempty"`
	Spec        sandboxSpecPayload `json:"spec"`
	Status      string             `json:"status,omitempty"`
	CreatedAt   string             `json:"created_at,omitempty"`
	UpdatedAt   string             `json:"updated_at,omitempty"`
}

type sandboxConfigsListResponse struct {
	Sandboxes []sandboxConfigResponse `json:"sandboxes"`
	pageResponse
}

type agentSpecUpsertRequest struct {
	Version     string                `json:"version,omitempty"`
	Description string                `json:"description,omitempty"`
	Tags        []string              `json:"tags,omitempty"`
	ModelRef    string                `json:"model_ref,omitempty"`
	Prompt      promptSpecPayload     `json:"prompt"`
	SkillRefs   []string              `json:"skill_refs,omitempty"`
	MCPRefs     []string              `json:"mcp_refs,omitempty"`
	SandboxRef  string                `json:"sandbox_ref,omitempty"`
	Subagents   []subagentSpecPayload `json:"subagents,omitempty"`
	InterruptOn []string              `json:"interrupt_on,omitempty"`
	Status      string                `json:"status,omitempty"`
}

type agentSpecResponse struct {
	Name        string                `json:"name,omitempty"`
	Version     string                `json:"version,omitempty"`
	Description string                `json:"description,omitempty"`
	Tags        []string              `json:"tags,omitempty"`
	ModelRef    string                `json:"model_ref,omitempty"`
	Prompt      promptSpecPayload     `json:"prompt"`
	SkillRefs   []string              `json:"skill_refs,omitempty"`
	MCPRefs     []string              `json:"mcp_refs,omitempty"`
	SandboxRef  string                `json:"sandbox_ref,omitempty"`
	Subagents   []subagentSpecPayload `json:"subagents,omitempty"`
	InterruptOn []string              `json:"interrupt_on,omitempty"`
	Status      string                `json:"status,omitempty"`
	CreatedAt   string                `json:"created_at,omitempty"`
	UpdatedAt   string                `json:"updated_at,omitempty"`
}

type agentSpecsListResponse struct {
	Agents []agentSpecResponse `json:"agents"`
	pageResponse
}

type listSessionsQuery struct {
	AgentName string
	PageSize  int32
	PageToken string
}

type latestSessionQuery struct {
	AgentName string
}

func decodeRunStreamRequest(r *http.Request) (domain.RunRequest, error) {
	request, err := decodeJSON[runStreamRequest](r, false)
	if err != nil {
		return domain.RunRequest{}, err
	}
	return domain.RunRequest{
		Message:  request.Message,
		ThreadID: request.ThreadID,
		Metadata: request.Metadata,
	}, nil
}

func decodeCancelRequest(r *http.Request) (cancelRequest, error) {
	return decodeJSON[cancelRequest](r, true)
}

func decodeHITLDecisionRequest(r *http.Request) (decodedHITLDecisionRequest, error) {
	request, err := decodeJSON[hitlDecisionRequest](r, false)
	if err != nil {
		return decodedHITLDecisionRequest{}, err
	}
	if strings.TrimSpace(request.InterruptID) == "" {
		return decodedHITLDecisionRequest{}, errors.New("interrupt_id must not be empty")
	}

	decisions := make([]runtimeclient.ToolDecision, 0, len(request.Decisions))
	for _, decision := range request.Decisions {
		decisionType := strings.ToLower(strings.TrimSpace(decision.Type))
		if decisionType == "" {
			return decodedHITLDecisionRequest{}, errors.New("decision.type must not be empty")
		}

		item := runtimeclient.ToolDecision{
			Type:    decisionType,
			Message: decision.Message,
		}
		if decision.EditedAction != nil {
			item.EditedAction = &runtimeclient.Action{
				Name:      strings.TrimSpace(decision.EditedAction.Name),
				Arguments: decision.EditedAction.Arguments,
			}
		}

		switch decisionType {
		case "approve":
		case "reject":
		case "edit":
			if item.EditedAction == nil {
				return decodedHITLDecisionRequest{}, errors.New("edit decision must include edited_action")
			}
			if item.EditedAction.Name == "" {
				return decodedHITLDecisionRequest{}, errors.New("edited_action.name must not be empty")
			}
		default:
			return decodedHITLDecisionRequest{}, fmt.Errorf("unsupported decision.type %q", decision.Type)
		}

		decisions = append(decisions, item)
	}

	return decodedHITLDecisionRequest{
		InterruptID: strings.TrimSpace(request.InterruptID),
		Decisions:   decisions,
	}, nil
}

func decodeSessionMessagePageQuery(c *gin.Context) (domain.SessionMessageQuery, error) {
	locator, err := decodeSessionLocator(c)
	if err != nil {
		return domain.SessionMessageQuery{}, err
	}
	mode, err := parseSessionHistoryMode(c.Query("mode"))
	if err != nil {
		return domain.SessionMessageQuery{}, err
	}
	pageSize, err := parsePageSize(c.Request, "page_size")
	if err != nil {
		return domain.SessionMessageQuery{}, err
	}
	includeRaw, err := parseOptionalBool(c.Request, "include_raw")
	if err != nil {
		return domain.SessionMessageQuery{}, err
	}

	return domain.SessionMessageQuery{
		AgentName:    locator.AgentName,
		ThreadID:     locator.ThreadID,
		CheckpointID: strings.TrimSpace(c.Query("checkpoint_id")),
		Mode:         mode,
		PageSize:     pageSize,
		PageToken:    strings.TrimSpace(c.Query("page_token")),
		IncludeRaw:   includeRaw,
	}, nil
}

func decodeListSessionsQuery(c *gin.Context) (listSessionsQuery, error) {
	pageSize, err := parsePageSize(c.Request, "page_size")
	if err != nil {
		return listSessionsQuery{}, err
	}
	return listSessionsQuery{
		AgentName: strings.TrimSpace(c.Query("agent_name")),
		PageSize:  pageSize,
		PageToken: strings.TrimSpace(c.Query("page_token")),
	}, nil
}

func decodeLatestSessionQuery(c *gin.Context) latestSessionQuery {
	return latestSessionQuery{
		AgentName: strings.TrimSpace(c.Query("agent_name")),
	}
}

func decodeSessionMessagesQuery(c *gin.Context) (domain.SessionMessageQuery, error) {
	locator, err := decodeSessionLocator(c)
	if err != nil {
		return domain.SessionMessageQuery{}, err
	}
	mode, err := parseSessionHistoryMode(c.Query("mode"))
	if err != nil {
		return domain.SessionMessageQuery{}, err
	}
	pageSize, err := parsePageSize(c.Request, "page_size")
	if err != nil {
		return domain.SessionMessageQuery{}, err
	}
	return domain.SessionMessageQuery{
		AgentName: locator.AgentName,
		ThreadID:  locator.ThreadID,
		Mode:      mode,
		PageSize:  pageSize,
		PageToken: strings.TrimSpace(c.Query("page_token")),
	}, nil
}

func decodeSessionLocator(c *gin.Context) (domain.SessionLocator, error) {
	agentName := strings.TrimSpace(c.Query("agent_name"))
	if agentName == "" {
		return domain.SessionLocator{}, errors.New("agent_name must not be empty")
	}

	threadID := strings.TrimSpace(c.Param("thread_id"))
	if threadID == "" {
		return domain.SessionLocator{}, errors.New("thread_id must not be empty")
	}

	return domain.SessionLocator{
		AgentName: agentName,
		ThreadID:  threadID,
	}, nil
}

func decodeResourcePageQuery(r *http.Request) (domain.PageQuery, error) {
	pageSize, err := parsePageSize(r, "page_size")
	if err != nil {
		return domain.PageQuery{}, err
	}
	pageNumber, err := parsePageNumber(r, "page_number")
	if err != nil {
		return domain.PageQuery{}, err
	}
	return domain.PageQuery{
		PageSize:   pageSize,
		PageNumber: pageNumber,
	}, nil
}

func decodeModelConfigRequest(c *gin.Context) (domain.ModelConfig, error) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		return domain.ModelConfig{}, err
	}
	request, err := decodeJSON[modelConfigUpsertRequest](c.Request, false)
	if err != nil {
		return domain.ModelConfig{}, err
	}
	status, err := parseOptionalAuthoredStatus(request.Status)
	if err != nil {
		return domain.ModelConfig{}, err
	}

	return domain.ModelConfig{
		Name:        name,
		Description: request.Description,
		Spec: newDomainModelSpec(modelSpecPayload{
			Provider:    request.Provider,
			Model:       request.Model,
			BaseURL:     request.BaseURL,
			APIKey:      request.APIKey,
			APIKeyEnv:   request.APIKeyEnv,
			ExtraParams: request.ExtraParams,
		}),
		Status: status,
	}, nil
}

func decodeSkillRequest(c *gin.Context) (domain.Skill, error) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		return domain.Skill{}, err
	}
	request, err := decodeJSON[skillUpsertRequest](c.Request, false)
	if err != nil {
		return domain.Skill{}, err
	}
	status, err := parseOptionalAuthoredStatus(request.Status)
	if err != nil {
		return domain.Skill{}, err
	}

	files := make([]domain.SkillFile, 0, len(request.Files))
	for _, file := range request.Files {
		files = append(files, domain.SkillFile{
			Path:    strings.TrimSpace(file.Path),
			Content: file.Content,
		})
	}

	return domain.Skill{
		Name:        name,
		Description: request.Description,
		Tags:        trimStrings(request.Tags),
		Content:     request.Content,
		Files:       files,
		Status:      status,
	}, nil
}

type decodedSkillPackageUploadRequest struct {
	Content []byte
	Status  domain.AuthoredStatus
}

func decodeSkillPackageUploadRequest(r *http.Request) (decodedSkillPackageUploadRequest, error) {
	if err := r.ParseMultipartForm(32 << 20); err != nil {
		return decodedSkillPackageUploadRequest{}, fmt.Errorf("parse multipart form: %w", err)
	}

	file, _, err := r.FormFile("package")
	if err != nil {
		file, _, err = r.FormFile("file")
		if err != nil {
			return decodedSkillPackageUploadRequest{}, errors.New("multipart field \"package\" must contain the skill zip")
		}
	}
	defer file.Close()

	content, err := io.ReadAll(file)
	if err != nil {
		return decodedSkillPackageUploadRequest{}, fmt.Errorf("read skill package upload: %w", err)
	}

	status, err := parseOptionalAuthoredStatus(r.FormValue("status"))
	if err != nil {
		return decodedSkillPackageUploadRequest{}, err
	}
	return decodedSkillPackageUploadRequest{
		Content: content,
		Status:  status,
	}, nil
}

func decodeWorkspaceUploadRequest(r *http.Request) (domain.WorkspaceUploadRequest, error) {
	if err := r.ParseMultipartForm(64 << 20); err != nil {
		return domain.WorkspaceUploadRequest{}, fmt.Errorf("parse multipart form: %w", err)
	}
	if r.MultipartForm != nil {
		defer func() {
			_ = r.MultipartForm.RemoveAll()
		}()
	}

	uploadedFiles := make([]domain.WorkspaceUploadFile, 0)
	if r.MultipartForm != nil {
		for _, field := range []string{"files", "file"} {
			for _, header := range r.MultipartForm.File[field] {
				item, err := newWorkspaceUploadFile(header)
				if err != nil {
					return domain.WorkspaceUploadRequest{}, err
				}
				uploadedFiles = append(uploadedFiles, item)
			}
		}
	}
	if len(uploadedFiles) == 0 {
		return domain.WorkspaceUploadRequest{}, errors.New("multipart field \"files\" must contain at least one file")
	}

	return domain.WorkspaceUploadRequest{
		ThreadID: strings.TrimSpace(r.FormValue("thread_id")),
		Files:    uploadedFiles,
	}, nil
}

func newWorkspaceUploadFile(header *multipart.FileHeader) (domain.WorkspaceUploadFile, error) {
	if header == nil {
		return domain.WorkspaceUploadFile{}, errors.New("workspace upload file header must not be nil")
	}
	file, err := header.Open()
	if err != nil {
		return domain.WorkspaceUploadFile{}, fmt.Errorf("open workspace upload: %w", err)
	}
	defer file.Close()

	content, err := io.ReadAll(file)
	if err != nil {
		return domain.WorkspaceUploadFile{}, fmt.Errorf("read workspace upload: %w", err)
	}

	name := strings.TrimSpace(filepath.Base(header.Filename))
	if name == "" || name == "." || name == ".." {
		return domain.WorkspaceUploadFile{}, errors.New("uploaded file must have a valid filename")
	}
	return domain.WorkspaceUploadFile{
		Path:    name,
		Content: content,
	}, nil
}

func decodeMCPConfigRequest(c *gin.Context) (domain.MCPConfig, error) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		return domain.MCPConfig{}, err
	}
	request, err := decodeJSON[mcpConfigUpsertRequest](c.Request, false)
	if err != nil {
		return domain.MCPConfig{}, err
	}
	status, err := parseOptionalAuthoredStatus(request.Status)
	if err != nil {
		return domain.MCPConfig{}, err
	}

	return domain.MCPConfig{
		Name:        name,
		Command:     strings.TrimSpace(request.Command),
		Args:        trimStrings(request.Args),
		Env:         request.Env,
		Transport:   strings.TrimSpace(request.Transport),
		Description: request.Description,
		Status:      status,
	}, nil
}

func decodeSandboxConfigRequest(c *gin.Context) (domain.SandboxConfig, error) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		return domain.SandboxConfig{}, err
	}
	request, err := decodeJSON[sandboxConfigUpsertRequest](c.Request, false)
	if err != nil {
		return domain.SandboxConfig{}, err
	}
	status, err := parseOptionalAuthoredStatus(request.Status)
	if err != nil {
		return domain.SandboxConfig{}, err
	}
	spec, err := newDomainSandboxSpec(&request.Spec)
	if err != nil {
		return domain.SandboxConfig{}, err
	}

	return domain.SandboxConfig{
		Name:        name,
		Description: request.Description,
		Spec:        spec,
		Status:      status,
	}, nil
}

func decodeAgentSpecRequest(c *gin.Context) (domain.AuthoredAgentSpec, error) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		return domain.AuthoredAgentSpec{}, err
	}
	request, err := decodeJSON[agentSpecUpsertRequest](c.Request, false)
	if err != nil {
		return domain.AuthoredAgentSpec{}, err
	}
	status, err := parseOptionalAuthoredStatus(request.Status)
	if err != nil {
		return domain.AuthoredAgentSpec{}, err
	}
	subagents := make([]domain.SubagentSpec, 0, len(request.Subagents))
	for _, subagent := range request.Subagents {
		subagents = append(subagents, domain.SubagentSpec{
			Name:         strings.TrimSpace(subagent.Name),
			Description:  subagent.Description,
			SystemPrompt: subagent.SystemPrompt,
			ModelRef:     strings.TrimSpace(subagent.ModelRef),
			SkillRefs:    trimStrings(subagent.SkillRefs),
		})
	}

	return domain.AuthoredAgentSpec{
		Name:        name,
		Version:     strings.TrimSpace(request.Version),
		Description: request.Description,
		Tags:        trimStrings(request.Tags),
		ModelRef:    strings.TrimSpace(request.ModelRef),
		Prompt:      domain.PromptSpec{System: request.Prompt.System},
		SkillRefs:   trimStrings(request.SkillRefs),
		MCPRefs:     trimStrings(request.MCPRefs),
		SandboxRef:  strings.TrimSpace(request.SandboxRef),
		Subagents:   subagents,
		InterruptOn: trimStrings(request.InterruptOn),
		Status:      status,
	}, nil
}

func decodeResourceName(c *gin.Context, key string) (string, error) {
	name := strings.TrimSpace(c.Param(key))
	if name == "" {
		return "", fmt.Errorf("%s must not be empty", key)
	}
	return name, nil
}

func parsePageSize(r *http.Request, key string) (int32, error) {
	rawValue := strings.TrimSpace(r.URL.Query().Get(key))
	if rawValue == "" {
		return 0, nil
	}

	value, err := strconv.ParseInt(rawValue, 10, 32)
	if err != nil {
		return 0, fmt.Errorf("%s must be a valid integer", key)
	}
	if value < 0 {
		return 0, fmt.Errorf("%s must be non-negative", key)
	}
	return int32(value), nil
}

func parsePageNumber(r *http.Request, key string) (int32, error) {
	rawValue := strings.TrimSpace(r.URL.Query().Get(key))
	if rawValue == "" {
		return 0, nil
	}

	value, err := strconv.ParseInt(rawValue, 10, 32)
	if err != nil {
		return 0, fmt.Errorf("%s must be a valid integer", key)
	}
	if value < 0 {
		return 0, fmt.Errorf("%s must be non-negative", key)
	}
	return int32(value), nil
}

func parseOptionalBool(r *http.Request, key string) (bool, error) {
	rawValue := strings.TrimSpace(r.URL.Query().Get(key))
	if rawValue == "" {
		return false, nil
	}

	value, err := strconv.ParseBool(rawValue)
	if err != nil {
		return false, fmt.Errorf("%s must be a valid boolean", key)
	}
	return value, nil
}

func parseSessionHistoryMode(rawValue string) (domain.SessionHistoryMode, error) {
	mode := domain.SessionHistoryMode(strings.TrimSpace(rawValue))
	switch mode {
	case "":
		return "", nil
	case domain.SessionHistoryModeResumeView, domain.SessionHistoryModeFullTranscript:
		return mode, nil
	default:
		return "", fmt.Errorf("unsupported session history mode %q", rawValue)
	}
}

func parseOptionalAuthoredStatus(rawValue string) (domain.AuthoredStatus, error) {
	status := domain.AuthoredStatus(strings.TrimSpace(rawValue))
	if status == "" {
		return "", nil
	}
	if !status.Valid() {
		return "", fmt.Errorf("unsupported authored status %q", rawValue)
	}
	return status, nil
}

func decodeJSON[T any](r *http.Request, allowEmpty bool) (T, error) {
	var zero T
	if allowEmpty && r.Body == nil {
		return zero, nil
	}
	if allowEmpty && r.ContentLength == 0 {
		return zero, nil
	}

	defer r.Body.Close()

	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()

	var value T
	if err := decoder.Decode(&value); err != nil {
		return zero, fmt.Errorf("decode request body: %w", err)
	}
	return value, nil
}

func writeJSON(w http.ResponseWriter, statusCode int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	_ = json.NewEncoder(w).Encode(value)
}

func writeRawJSON(w http.ResponseWriter, statusCode int, payload []byte) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	_, _ = w.Write(payload)
}

func writeJSONError(w http.ResponseWriter, statusCode int, err error) {
	writeJSON(w, statusCode, errorResponse{Error: err.Error()})
}

func writeServiceError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, registrypkg.ErrNotFound), errors.Is(err, runtimeclient.ErrNotFound), errors.Is(err, telemetry.ErrRunNotFound):
		writeJSONError(w, http.StatusNotFound, err)
	case errors.Is(err, registrypkg.ErrConflict):
		writeJSONError(w, http.StatusConflict, err)
	case errors.Is(err, registrypkg.ErrInvalid):
		writeJSONError(w, http.StatusBadRequest, err)
	case errors.Is(err, orchestrator.ErrEmptyAgentName):
		writeJSONError(w, http.StatusBadRequest, err)
	default:
		writeJSONError(w, http.StatusInternalServerError, err)
	}
}

func writeSessionControlError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, errRunSessionClosed):
		writeJSONError(w, http.StatusGone, err)
	case errors.Is(err, errRunSessionBusy):
		writeJSONError(w, http.StatusConflict, err)
	default:
		writeJSONError(w, http.StatusInternalServerError, err)
	}
}

func newHTTPAgentEvent(event runtimeclient.AgentEvent) httpAgentEvent {
	actionRequests := make([]httpActionRequest, 0, len(event.Actions))
	for _, action := range event.Actions {
		actionRequests = append(actionRequests, httpActionRequest{
			Name:        action.Name,
			Description: action.Description,
			Arguments:   action.Arguments,
		})
	}
	reviewConfigs := make([]httpReviewConfig, 0, len(event.ReviewConfigs))
	for _, config := range event.ReviewConfigs {
		reviewConfigs = append(reviewConfigs, httpReviewConfig{
			ActionName:       config.ActionName,
			AllowedDecisions: config.AllowedDecisions,
			ArgsSchema:       config.ArgsSchema,
		})
	}

	response := httpAgentEvent{
		Type:           string(event.Type),
		RunID:          event.RunID,
		AgentName:      event.AgentName,
		ThreadID:       event.ThreadID,
		Text:           event.Text,
		ToolName:       event.ToolName,
		ToolCallID:     event.ToolCallID,
		InterruptID:    event.InterruptID,
		Reason:         event.Reason,
		ErrorMessage:   event.ErrorMessage,
		Payload:        event.Payload,
		ActionRequests: actionRequests,
		ReviewConfigs:  reviewConfigs,
	}
	if !event.Timestamp.IsZero() {
		response.Timestamp = event.Timestamp.UTC().Format("2006-01-02T15:04:05.999999999Z07:00")
	}
	return response
}

func newHTTPTelemetryEvent(event runtimeclient.TelemetryEvent) httpTelemetryEvent {
	response := httpTelemetryEvent{
		RunID:       event.RunID,
		AgentName:   event.AgentName,
		EventID:     event.EventID,
		Attempt:     event.Attempt,
		Seq:         event.Seq,
		Namespace:   event.Namespace,
		StreamMode:  event.StreamMode,
		EventType:   event.EventType,
		NodeName:    event.NodeName,
		TaskID:      event.TaskID,
		ModelCallID: event.ModelCallID,
		ToolCallID:  event.ToolCallID,
		InterruptID: event.InterruptID,
		MessageID:   event.MessageID,
		Metadata:    event.Metadata,
		Payload:     event.Payload,
	}
	if !event.Timestamp.IsZero() {
		response.Timestamp = event.Timestamp.UTC().Format("2006-01-02T15:04:05.999999999Z07:00")
	}
	if event.PublicEvent != nil {
		payload, err := json.Marshal(newHTTPAgentEvent(*event.PublicEvent))
		if err == nil {
			response.PublicEvent = payload
		}
	}
	return response
}

func newHTTPTelemetryEventRecord(event domain.TelemetryEventRecord) httpTelemetryEvent {
	response := httpTelemetryEvent{
		RunID:       event.RunID,
		AgentName:   event.AgentName,
		Timestamp:   formatOptionalTime(event.Timestamp),
		EventID:     event.EventID,
		Attempt:     event.Attempt,
		Seq:         event.Seq,
		Namespace:   event.Namespace,
		StreamMode:  event.StreamMode,
		EventType:   event.EventType,
		NodeName:    event.NodeName,
		TaskID:      event.TaskID,
		ModelCallID: event.ModelCallID,
		ToolCallID:  event.ToolCallID,
		InterruptID: event.InterruptID,
		MessageID:   event.MessageID,
		Metadata:    event.Metadata,
		Payload:     event.Payload,
		PublicEvent: event.PublicEvent,
	}
	return response
}

func newHTTPTelemetryRunResponse(run domain.TelemetryRun) telemetryRunResponse {
	return telemetryRunResponse{
		RunID:            run.RunID,
		AgentName:        run.AgentName,
		ThreadID:         run.ThreadID,
		RuntimeTarget:    run.RuntimeTarget,
		Status:           string(run.Status),
		RequestMetadata:  run.RequestMetadata,
		TraceContext:     run.TraceContext,
		GraphSnapshotID:  run.GraphSnapshotID,
		ReasoningSummary: run.ReasoningSummary,
		NodeStepCount:    run.NodeStepCount,
		ModelStepCount:   run.ModelStepCount,
		ToolStepCount:    run.ToolStepCount,
		HitlWaitCount:    run.HitlWaitCount,
		ErrorCount:       run.ErrorCount,
		EventCount:       run.EventCount,
		StartedAt:        formatOptionalTime(run.StartedAt),
		FinishedAt:       formatOptionalTime(run.FinishedAt),
		LastEventAt:      formatOptionalTime(run.LastEventAt),
		CreatedAt:        formatOptionalTime(run.CreatedAt),
		UpdatedAt:        formatOptionalTime(run.UpdatedAt),
	}
}

func newHTTPTelemetryStepResponse(step domain.TelemetryStep) telemetryStepResponse {
	return telemetryStepResponse{
		StepID:          step.StepID,
		RunID:           step.RunID,
		ParentStepID:    step.ParentStepID,
		Kind:            string(step.Kind),
		Title:           step.Title,
		Namespace:       step.Namespace,
		Status:          string(step.Status),
		StartedAt:       formatOptionalTime(step.StartedAt),
		FinishedAt:      formatOptionalTime(step.FinishedAt),
		Depth:           step.Depth,
		Step:            step.Step,
		Input:           step.Input,
		Output:          step.Output,
		Error:           step.Error,
		Triggers:        step.Triggers,
		Reasoning:       step.Reasoning,
		Messages:        step.Messages,
		Updates:         step.Updates,
		Custom:          step.Custom,
		RelatedEventIDs: step.RelatedEventIDs,
		Order:           step.Order,
		Synthetic:       step.Synthetic,
	}
}

func newHTTPHealthResponse(resp runtimeclient.HealthResponse) healthResponse {
	return healthResponse{
		Status:              resp.Status,
		AssembledAgentCount: resp.AssembledAgentCount,
		InstalledAgentCount: resp.InstalledAgentCount,
		RunningAgentCount:   resp.RunningAgentCount,
		UptimeSeconds:       resp.UptimeSeconds,
		Ready:               resp.Ready,
	}
}

func newHTTPWorkspaceUploadResponse(resp domain.WorkspaceUploadResponse) workspaceUploadResponse {
	files := make([]workspaceUploadFileResponse, 0, len(resp.Files))
	for _, item := range resp.Files {
		files = append(files, workspaceUploadFileResponse{
			Path:  item.Path,
			Error: item.Error,
		})
	}
	return workspaceUploadResponse{
		ThreadID: resp.ThreadID,
		Files:    files,
	}
}

func newHTTPWorkspaceDownloadResponse(resp domain.WorkspaceDownloadResponse) workspaceDownloadResponse {
	files := make([]workspaceDownloadFileResponse, 0, len(resp.Files))
	for _, item := range resp.Files {
		encoded := ""
		if item.Content != nil {
			encoded = base64.StdEncoding.EncodeToString(item.Content)
		}
		files = append(files, workspaceDownloadFileResponse{
			Path:          item.Path,
			ContentBase64: encoded,
			Error:         item.Error,
		})
	}
	return workspaceDownloadResponse{
		ThreadID: resp.ThreadID,
		Files:    files,
	}
}

func newHTTPWorkspaceListResponse(resp domain.WorkspaceListResponse) workspaceListResponse {
	files := make([]workspaceFileInfoResponse, 0, len(resp.Files))
	for _, item := range resp.Files {
		files = append(files, workspaceFileInfoResponse{
			Path:       item.Path,
			IsDir:      item.IsDir,
			Size:       item.Size,
			ModifiedAt: item.ModifiedAt,
		})
	}
	return workspaceListResponse{
		ThreadID: resp.ThreadID,
		Files:    files,
	}
}

func newHTTPListArtifactsResponse(resp domain.ListArtifactsResponse) listArtifactsResponse {
	artifacts := make([]threadArtifactResponse, 0, len(resp.Artifacts))
	for _, item := range resp.Artifacts {
		artifacts = append(artifacts, threadArtifactResponse{
			ID:            item.ID,
			Type:          item.Type,
			Path:          item.Path,
			Title:         item.Title,
			ContentType:   item.ContentType,
			Language:      item.Language,
			CreatedByTool: item.CreatedByTool,
			CreatedAt:     item.CreatedAt,
			ModifiedAt:    item.ModifiedAt,
			Size:          item.Size,
		})
	}
	return listArtifactsResponse{
		ThreadID:  resp.ThreadID,
		Artifacts: artifacts,
	}
}

func newHTTPSessionSummaryResponse(session domain.SessionSummary) sessionSummaryResponse {
	return sessionSummaryResponse{
		ThreadID:           session.ThreadID,
		AgentName:          session.AgentName,
		LatestCheckpointID: session.LatestCheckpointID,
		MessageCount:       session.MessageCount,
		CheckpointCount:    session.CheckpointCount,
		InitialPrompt:      session.InitialPrompt,
		HistoryMode:        string(session.HistoryMode),
		AgentStatus:        string(session.AgentStatus),
		UpdatedAt:          formatOptionalTime(session.UpdatedAt),
	}
}

func newHTTPSessionSummaryResponses(sessions []domain.SessionSummary) []sessionSummaryResponse {
	responses := make([]sessionSummaryResponse, 0, len(sessions))
	for _, session := range sessions {
		responses = append(responses, newHTTPSessionSummaryResponse(session))
	}
	return responses
}

func newHTTPSessionMessageResponse(message domain.SessionMessage) sessionMessageResponse {
	return sessionMessageResponse{
		Index:        message.Index,
		CheckpointID: message.CheckpointID,
		Role:         string(message.Role),
		Text:         message.Text,
		Content:      message.Content,
		ToolCallID:   message.ToolCallID,
		ToolName:     message.ToolName,
		IsError:      message.IsError,
		Raw:          message.Raw,
		CreatedAt:    formatOptionalTime(message.CreatedAt),
	}
}

func newHTTPSessionMessageResponses(messages []domain.SessionMessage) []sessionMessageResponse {
	responses := make([]sessionMessageResponse, 0, len(messages))
	for _, message := range messages {
		responses = append(responses, newHTTPSessionMessageResponse(message))
	}
	return responses
}

func newHTTPSessionMessagePageResponse(page domain.SessionMessagePage) sessionMessagePageResponse {
	return sessionMessagePageResponse{
		ThreadID:             page.ThreadID,
		ResolvedCheckpointID: page.ResolvedCheckpointID,
		ActualMode:           string(page.ActualMode),
		TotalMessageCount:    page.TotalMessageCount,
		Messages:             newHTTPSessionMessageResponses(page.Messages),
		NextPageToken:        page.NextPageToken,
	}
}

func newHTTPPageResponse(metadata domain.PageMetadata) pageResponse {
	return pageResponse{
		PageSize:   metadata.PageSize,
		PageNumber: metadata.PageNumber,
		TotalSize:  metadata.TotalSize,
		TotalPages: metadata.TotalPages,
	}
}

func newHTTPSkillResponse(skill domain.Skill) skillResponse {
	return skillResponse{
		Name:        skill.Name,
		Description: skill.Description,
		Tags:        skill.Tags,
		Content:     skill.Content,
		Files:       newHTTPSkillFiles(skill.Files),
		Status:      string(skill.Status),
		CreatedAt:   formatOptionalTime(skill.CreatedAt),
		UpdatedAt:   formatOptionalTime(skill.UpdatedAt),
	}
}

func newHTTPSkillSummaryResponse(skill domain.Skill) skillSummaryResponse {
	description := skillpackage.Describe(skill)
	return skillSummaryResponse{
		Name:           description.Frontmatter.Name,
		Description:    description.Frontmatter.Description,
		Status:         string(skill.Status),
		CreatedAt:      formatOptionalTime(skill.CreatedAt),
		UpdatedAt:      formatOptionalTime(skill.UpdatedAt),
		License:        description.Frontmatter.License,
		Compatibility:  description.Frontmatter.Compatibility,
		Metadata:       description.Frontmatter.Metadata,
		AllowedTools:   description.Frontmatter.AllowedTools,
		FileCount:      description.FileCount,
		SnapshotDigest: description.SnapshotDigest,
	}
}

func newHTTPSkillSummaryResponses(skills []domain.Skill) []skillSummaryResponse {
	responses := make([]skillSummaryResponse, 0, len(skills))
	for _, skill := range skills {
		responses = append(responses, newHTTPSkillSummaryResponse(skill))
	}
	return responses
}

func newHTTPSkillDetailResponse(skill domain.Skill) skillDetailResponse {
	description := skillpackage.Describe(skill)
	return skillDetailResponse{
		Name:           description.Frontmatter.Name,
		Description:    description.Frontmatter.Description,
		Status:         string(skill.Status),
		CreatedAt:      formatOptionalTime(skill.CreatedAt),
		UpdatedAt:      formatOptionalTime(skill.UpdatedAt),
		License:        description.Frontmatter.License,
		Compatibility:  description.Frontmatter.Compatibility,
		Metadata:       description.Frontmatter.Metadata,
		AllowedTools:   description.Frontmatter.AllowedTools,
		FileCount:      description.FileCount,
		SnapshotDigest: description.SnapshotDigest,
		SkillMD:        skill.Content,
		Frontmatter:    description.Frontmatter.Raw,
		FileManifest:   newHTTPSkillManifest(description.Manifest),
	}
}

func newHTTPSkillManifest(entries []skillpackage.FileManifestEntry) []skillManifestPayload {
	payloads := make([]skillManifestPayload, 0, len(entries))
	for _, entry := range entries {
		payloads = append(payloads, skillManifestPayload{
			Path:   entry.Path,
			Size:   entry.Size,
			SHA256: entry.SHA256,
		})
	}
	return payloads
}

func newHTTPSkillFiles(files []domain.SkillFile) []skillFilePayload {
	payloads := make([]skillFilePayload, 0, len(files))
	for _, file := range files {
		payloads = append(payloads, skillFilePayload{
			Path:    file.Path,
			Content: file.Content,
		})
	}
	return payloads
}

func newHTTPMCPConfigResponse(config domain.MCPConfig) mcpConfigResponse {
	return mcpConfigResponse{
		Name:        config.Name,
		Command:     config.Command,
		Args:        config.Args,
		Env:         config.Env,
		Transport:   config.Transport,
		Description: config.Description,
		Status:      string(config.Status),
		CreatedAt:   formatOptionalTime(config.CreatedAt),
		UpdatedAt:   formatOptionalTime(config.UpdatedAt),
	}
}

func newHTTPMCPConfigResponses(configs []domain.MCPConfig) []mcpConfigResponse {
	responses := make([]mcpConfigResponse, 0, len(configs))
	for _, config := range configs {
		responses = append(responses, newHTTPMCPConfigResponse(config))
	}
	return responses
}

func newHTTPModelConfigResponse(config domain.ModelConfig) modelConfigResponse {
	return modelConfigResponse{
		Name:        config.Name,
		Description: config.Description,
		Provider:    config.Spec.Provider,
		Model:       config.Spec.Model,
		BaseURL:     config.Spec.BaseURL,
		APIKey:      maskSecret(config.Spec.APIKey),
		APIKeyEnv:   config.Spec.APIKeyEnv,
		ExtraParams: config.Spec.ExtraParams,
		Status:      string(config.Status),
		CreatedAt:   formatOptionalTime(config.CreatedAt),
		UpdatedAt:   formatOptionalTime(config.UpdatedAt),
	}
}

func newHTTPModelConfigResponses(configs []domain.ModelConfig) []modelConfigResponse {
	responses := make([]modelConfigResponse, 0, len(configs))
	for _, config := range configs {
		responses = append(responses, newHTTPModelConfigResponse(config))
	}
	return responses
}

func newHTTPSandboxConfigResponse(config domain.SandboxConfig) sandboxConfigResponse {
	return sandboxConfigResponse{
		Name:        config.Name,
		Description: config.Description,
		Spec:        newHTTPSandboxSpec(config.Spec),
		Status:      string(config.Status),
		CreatedAt:   formatOptionalTime(config.CreatedAt),
		UpdatedAt:   formatOptionalTime(config.UpdatedAt),
	}
}

func newHTTPSandboxConfigResponses(configs []domain.SandboxConfig) []sandboxConfigResponse {
	responses := make([]sandboxConfigResponse, 0, len(configs))
	for _, config := range configs {
		responses = append(responses, newHTTPSandboxConfigResponse(config))
	}
	return responses
}

func newHTTPAgentSpecResponse(spec domain.AuthoredAgentSpec) agentSpecResponse {
	return agentSpecResponse{
		Name:        spec.Name,
		Version:     spec.Version,
		Description: spec.Description,
		Tags:        spec.Tags,
		ModelRef:    spec.ModelRef,
		Prompt:      promptSpecPayload{System: spec.Prompt.System},
		SkillRefs:   spec.SkillRefs,
		MCPRefs:     spec.MCPRefs,
		SandboxRef:  spec.SandboxRef,
		Subagents:   newHTTPSubagentSpecs(spec.Subagents),
		InterruptOn: spec.InterruptOn,
		Status:      string(spec.Status),
		CreatedAt:   formatOptionalTime(spec.CreatedAt),
		UpdatedAt:   formatOptionalTime(spec.UpdatedAt),
	}
}

func newHTTPAgentSpecResponses(specs []domain.AuthoredAgentSpec) []agentSpecResponse {
	responses := make([]agentSpecResponse, 0, len(specs))
	for _, spec := range specs {
		responses = append(responses, newHTTPAgentSpecResponse(spec))
	}
	return responses
}

func newHTTPModelSpec(spec domain.ModelSpec) modelSpecPayload {
	return modelSpecPayload{
		Provider:    spec.Provider,
		Model:       spec.Model,
		BaseURL:     spec.BaseURL,
		APIKey:      maskSecret(spec.APIKey),
		APIKeyEnv:   spec.APIKeyEnv,
		ExtraParams: spec.ExtraParams,
	}
}

func newHTTPSubagentSpecs(specs []domain.SubagentSpec) []subagentSpecPayload {
	payloads := make([]subagentSpecPayload, 0, len(specs))
	for _, spec := range specs {
		payloads = append(payloads, subagentSpecPayload{
			Name:         spec.Name,
			Description:  spec.Description,
			SystemPrompt: spec.SystemPrompt,
			ModelRef:     spec.ModelRef,
			SkillRefs:    spec.SkillRefs,
		})
	}
	return payloads
}

func newHTTPSandboxSpec(spec domain.SandboxSpec) sandboxSpecPayload {
	payload := sandboxSpecPayload{}
	if spec.Execution != (domain.SandboxExecutionPolicy{}) {
		payload.Execution = &sandboxExecutionPolicyPayload{
			CommandTimeoutSeconds: spec.Execution.CommandTimeoutSeconds,
			SetupTimeoutSeconds:   spec.Execution.SetupTimeoutSeconds,
			StartupTimeoutSeconds: spec.Execution.StartupTimeoutSeconds,
			MaxOutputBytes:        spec.Execution.MaxOutputBytes,
		}
	}
	if len(spec.Env) > 0 {
		payload.Env = make([]sandboxEnvVarPayload, 0, len(spec.Env))
		for _, item := range spec.Env {
			payload.Env = append(payload.Env, sandboxEnvVarPayload{
				Name:  item.Name,
				Value: item.Value,
			})
		}
	}
	payload.SetupCommands = cloneStringSlice(spec.SetupCommands)
	switch {
	case spec.Local != nil:
		payload.Local = &struct{}{}
	case spec.Docker != nil:
		payload.Docker = &dockerSandboxSpecPayload{
			Image: imageReferencePayload{
				Reference:  spec.Docker.Image.Reference,
				PullPolicy: string(spec.Docker.Image.PullPolicy),
			},
			Resources: dockerResourceSpecPayload{
				CPU:       spec.Docker.Resources.CPU,
				Memory:    spec.Docker.Resources.Memory,
				ShmSize:   spec.Docker.Resources.ShmSize,
				PidsLimit: spec.Docker.Resources.PidsLimit,
			},
		}
	case spec.Kubernetes != nil:
		payload.Kubernetes = &kubernetesSandboxSpecPayload{
			Image: imageReferencePayload{
				Reference:  spec.Kubernetes.Image.Reference,
				PullPolicy: string(spec.Kubernetes.Image.PullPolicy),
			},
			Resources: kubernetesResourceRequirementsPayload{
				Requests: cloneStringMap(spec.Kubernetes.Resources.Requests),
				Limits:   cloneStringMap(spec.Kubernetes.Resources.Limits),
			},
		}
	}
	return payload
}

func newDomainModelSpec(spec modelSpecPayload) domain.ModelSpec {
	return domain.ModelSpec{
		Provider:    strings.TrimSpace(spec.Provider),
		Model:       strings.TrimSpace(spec.Model),
		BaseURL:     strings.TrimSpace(spec.BaseURL),
		APIKey:      strings.TrimSpace(spec.APIKey),
		APIKeyEnv:   strings.TrimSpace(spec.APIKeyEnv),
		ExtraParams: spec.ExtraParams,
	}
}

func newDomainSandboxSpec(spec *sandboxSpecPayload) (domain.SandboxSpec, error) {
	if spec == nil {
		return domain.SandboxSpec{}, nil
	}
	if spec.Local != nil || spec.Docker != nil || spec.Kubernetes != nil || spec.Execution != nil ||
		len(spec.Env) > 0 || len(spec.SetupCommands) > 0 {
		domainSpec := domain.SandboxSpec{
			Env:           make([]domain.SandboxEnvVar, 0, len(spec.Env)),
			SetupCommands: trimStrings(spec.SetupCommands),
		}
		if spec.Execution != nil {
			domainSpec.Execution = domain.SandboxExecutionPolicy{
				CommandTimeoutSeconds: spec.Execution.CommandTimeoutSeconds,
				SetupTimeoutSeconds:   spec.Execution.SetupTimeoutSeconds,
				StartupTimeoutSeconds: spec.Execution.StartupTimeoutSeconds,
				MaxOutputBytes:        spec.Execution.MaxOutputBytes,
			}
		}
		for _, item := range spec.Env {
			domainSpec.Env = append(domainSpec.Env, domain.SandboxEnvVar{
				Name:  strings.TrimSpace(item.Name),
				Value: item.Value,
			})
		}
		switch {
		case spec.Local != nil:
			domainSpec.Local = &domain.LocalSandboxSpec{}
		case spec.Docker != nil:
			domainSpec.Docker = &domain.DockerSandboxSpec{
				Image: domain.ImageReference{
					Reference:  strings.TrimSpace(spec.Docker.Image.Reference),
					PullPolicy: domain.ImagePullPolicy(strings.TrimSpace(spec.Docker.Image.PullPolicy)),
				},
				Resources: domain.DockerResourceSpec{
					CPU:       strings.TrimSpace(spec.Docker.Resources.CPU),
					Memory:    strings.TrimSpace(spec.Docker.Resources.Memory),
					ShmSize:   strings.TrimSpace(spec.Docker.Resources.ShmSize),
					PidsLimit: spec.Docker.Resources.PidsLimit,
				},
			}
		case spec.Kubernetes != nil:
			domainSpec.Kubernetes = &domain.KubernetesSandboxSpec{
				Image: domain.ImageReference{
					Reference:  strings.TrimSpace(spec.Kubernetes.Image.Reference),
					PullPolicy: domain.ImagePullPolicy(strings.TrimSpace(spec.Kubernetes.Image.PullPolicy)),
				},
				Resources: domain.KubernetesResourceRequirements{
					Requests: cloneStringMap(spec.Kubernetes.Resources.Requests),
					Limits:   cloneStringMap(spec.Kubernetes.Resources.Limits),
				},
			}
		}
		normalized, err := domain.NormalizeSandboxSpec(domainSpec)
		if err != nil {
			return domain.SandboxSpec{}, err
		}
		return normalized, nil
	}
	if strings.TrimSpace(spec.Image) == "" && len(spec.Resources) == 0 && len(spec.Init) == 0 {
		return domain.SandboxSpec{}, nil
	}
	legacy, err := domain.LegacySandboxSpec(
		strings.TrimSpace(spec.Image),
		cloneStringMap(spec.Resources),
		trimStrings(spec.Init),
	)
	if err != nil {
		return domain.SandboxSpec{}, err
	}
	return legacy, nil
}

func trimStrings(values []string) []string {
	trimmed := make([]string, 0, len(values))
	for _, value := range values {
		trimmed = append(trimmed, strings.TrimSpace(value))
	}
	return trimmed
}

func cloneStringSlice(values []string) []string {
	cloned := make([]string, 0, len(values))
	cloned = append(cloned, values...)
	return cloned
}

func cloneStringMap(values map[string]string) map[string]string {
	if len(values) == 0 {
		return nil
	}
	cloned := make(map[string]string, len(values))
	for key, value := range values {
		cloned[key] = value
	}
	return cloned
}

func formatOptionalTime(value time.Time) string {
	if value.IsZero() {
		return ""
	}
	return value.UTC().Format(time.RFC3339Nano)
}

// maskSecret masks a secret value for safe display over the API.
// Shows first 4 and last 4 characters; short values are fully masked.
func maskSecret(value string) string {
	if value == "" {
		return ""
	}
	n := len(value)
	if n <= 8 {
		return strings.Repeat("*", n)
	}
	return value[:4] + strings.Repeat("*", n-8) + value[n-4:]
}

func newRunSessionID() (string, error) {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("generate run session id: %w", err)
	}
	return hex.EncodeToString(buffer), nil
}
