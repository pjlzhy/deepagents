package runtimeclient

import (
	"context"
	"errors"
	"fmt"

	"agentctl/pkg/domain"
	runtimev1 "agentctl/pkg/proto"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	grpcstatus "google.golang.org/grpc/status"
)

var (
	_ ResourceSyncClient  = (*GRPCClient)(nil)
	_ AgentExecutorClient = (*GRPCClient)(nil)
	_ SessionQueryClient  = (*GRPCClient)(nil)
)

// GRPCClient is the southbound runtime client backed by protobuf gRPC stubs.
type GRPCClient struct {
	conn         *grpc.ClientConn
	resourceSync runtimev1.ResourceSyncClient
	executor     runtimev1.AgentExecutorClient
	sessions     runtimev1.SessionQueryClient
}

// NewGRPCClient dials one runtime endpoint and returns a shared southbound client.
//
// When no dial options are provided, the client defaults to an insecure transport
// suitable for local development.
func NewGRPCClient(
	ctx context.Context,
	endpoint string,
	opts ...grpc.DialOption,
) (*GRPCClient, error) {
	if endpoint == "" {
		return nil, errors.New("endpoint must not be empty")
	}

	dialOptions := opts
	if len(dialOptions) == 0 {
		dialOptions = []grpc.DialOption{grpc.WithTransportCredentials(insecure.NewCredentials())}
	}

	conn, err := grpc.DialContext(ctx, endpoint, dialOptions...)
	if err != nil {
		return nil, fmt.Errorf("dial runtime endpoint %q: %w", endpoint, err)
	}

	return NewGRPCClientFromConn(conn)
}

// NewGRPCClientFromConn builds a southbound client from an existing gRPC connection.
func NewGRPCClientFromConn(conn *grpc.ClientConn) (*GRPCClient, error) {
	if conn == nil {
		return nil, errors.New("grpc connection must not be nil")
	}

	return &GRPCClient{
		conn:         conn,
		resourceSync: runtimev1.NewResourceSyncClient(conn),
		executor:     runtimev1.NewAgentExecutorClient(conn),
		sessions:     runtimev1.NewSessionQueryClient(conn),
	}, nil
}

// Close closes the shared runtime connection.
func (c *GRPCClient) Close() error {
	if c == nil || c.conn == nil {
		return nil
	}
	return c.conn.Close()
}

// SyncAgentSpec pushes a packaged runtime agent spec to the data plane.
func (c *GRPCClient) SyncAgentSpec(
	ctx context.Context,
	spec domain.RuntimeAgentSpec,
) (SyncResponse, error) {
	request, err := runtimeAgentSpecToProto(spec)
	if err != nil {
		return SyncResponse{}, err
	}

	response, err := c.resourceSync.SyncAgentSpec(ctx, request)
	if err != nil {
		return SyncResponse{}, normalizeRPCError("sync agent spec", err)
	}

	return SyncResponse{
		OK:      response.GetOk(),
		Message: response.GetMessage(),
	}, nil
}

// Assemble triggers agent compilation on the data plane.
func (c *GRPCClient) Assemble(
	ctx context.Context,
	agentName string,
) (AssembleResponse, error) {
	response, err := c.resourceSync.Assemble(ctx, &runtimev1.AssembleRequest{
		AgentName: agentName,
	})
	if err != nil {
		return AssembleResponse{}, normalizeRPCError("assemble agent", err)
	}

	return AssembleResponse{
		OK:      response.GetOk(),
		Message: response.GetMessage(),
		Status:  response.GetStatus(),
	}, nil
}

// RemoveAgent removes an installed runtime-side agent resource.
func (c *GRPCClient) RemoveAgent(
	ctx context.Context,
	agentName string,
) (SyncResponse, error) {
	response, err := c.resourceSync.RemoveResource(ctx, &runtimev1.RemoveResourceRequest{
		ResourceType: "agent",
		Name:         agentName,
	})
	if err != nil {
		return SyncResponse{}, normalizeRPCError("remove agent", err)
	}

	return SyncResponse{
		OK:      response.GetOk(),
		Message: response.GetMessage(),
	}, nil
}

// Health queries runtime readiness and live counters.
func (c *GRPCClient) Health(ctx context.Context) (HealthResponse, error) {
	response, err := c.resourceSync.Health(ctx, &runtimev1.HealthRequest{})
	if err != nil {
		return HealthResponse{}, normalizeRPCError("query runtime health", err)
	}

	return HealthResponse{
		Status:              response.GetStatus(),
		AssembledAgentCount: response.GetAssembledAgentCount(),
		InstalledAgentCount: response.GetInstalledAgentCount(),
		RunningAgentCount:   response.GetRunningAgentCount(),
		UptimeSeconds:       response.GetUptimeSeconds(),
		Ready:               response.GetReady(),
	}, nil
}

// OpenRun opens one southbound bidirectional run stream and sends the initial request.
func (c *GRPCClient) OpenRun(ctx context.Context, req domain.RunRequest) (RunStream, error) {
	stream, err := c.executor.Run(ctx)
	if err != nil {
		return nil, normalizeRPCError("open run stream", err)
	}

	if err := stream.Send(&runtimev1.ClientMessage{
		Payload: &runtimev1.ClientMessage_RunRequest{
			RunRequest: runRequestToProto(req),
		},
	}); err != nil {
		return nil, normalizeRPCError("send initial run request", err)
	}

	return newGRPCRunStream(stream), nil
}

// ListSessions lists recent sessions from the data plane.
func (c *GRPCClient) ListSessions(
	ctx context.Context,
	agentName string,
	pageSize int32,
	pageToken string,
) ([]domain.SessionSummary, string, error) {
	response, err := c.sessions.ListSessions(ctx, &runtimev1.ListSessionsRequest{
		AgentName: agentName,
		PageSize:  pageSize,
		PageToken: pageToken,
	})
	if err != nil {
		return nil, "", normalizeRPCError("list sessions", err)
	}

	sessions := make([]domain.SessionSummary, 0, len(response.GetSessions()))
	for _, session := range response.GetSessions() {
		sessions = append(sessions, sessionSummaryFromProto(session, 0))
	}
	return sessions, response.GetNextPageToken(), nil
}

// GetSession returns one session summary plus checkpoint count.
func (c *GRPCClient) GetSession(
	ctx context.Context,
	threadID string,
) (domain.SessionSummary, error) {
	response, err := c.sessions.GetSession(ctx, &runtimev1.GetSessionRequest{
		ThreadId: threadID,
	})
	if err != nil {
		return domain.SessionSummary{}, normalizeRPCError("get session", err)
	}
	if !response.GetFound() || response.GetSession() == nil {
		return domain.SessionSummary{}, ErrNotFound
	}

	session := response.GetSession()
	return sessionSummaryFromProto(session.GetSummary(), session.GetCheckpointCount()), nil
}

// GetSessionMessages returns one page of checkpoint-backed session messages.
func (c *GRPCClient) GetSessionMessages(
	ctx context.Context,
	threadID string,
	mode domain.SessionHistoryMode,
	pageSize int32,
	pageToken string,
) ([]domain.SessionMessage, string, error) {
	page, err := c.GetSessionMessagePage(ctx, domain.SessionMessageQuery{
		ThreadID:   threadID,
		Mode:       mode,
		PageSize:   pageSize,
		PageToken:  pageToken,
		IncludeRaw: true,
	})
	if err != nil {
		return nil, "", err
	}
	return page.Messages, page.NextPageToken, nil
}

// GetSessionMessagePage returns one full page of checkpoint-backed session history.
func (c *GRPCClient) GetSessionMessagePage(
	ctx context.Context,
	query domain.SessionMessageQuery,
) (domain.SessionMessagePage, error) {
	response, err := c.sessions.GetSessionMessages(ctx, &runtimev1.GetSessionMessagesRequest{
		ThreadId:      query.ThreadID,
		CheckpointId:  query.CheckpointID,
		PageSize:      query.PageSize,
		PageToken:     query.PageToken,
		RequestedMode: sessionHistoryModeToProto(query.Mode),
		IncludeRaw:    query.IncludeRaw,
	})
	if err != nil {
		return domain.SessionMessagePage{}, normalizeRPCError("get session messages", err)
	}

	return sessionMessagePageFromProto(response), nil
}

// GetLatestSession resolves the newest session, optionally filtered by agent.
func (c *GRPCClient) GetLatestSession(
	ctx context.Context,
	agentName string,
) (domain.SessionSummary, error) {
	response, err := c.sessions.GetLatestSession(ctx, &runtimev1.GetLatestSessionRequest{
		AgentName: agentName,
	})
	if err != nil {
		return domain.SessionSummary{}, normalizeRPCError("get latest session", err)
	}
	if !response.GetFound() || response.GetSession() == nil {
		return domain.SessionSummary{}, ErrNotFound
	}

	return sessionSummaryFromProto(response.GetSession(), 0), nil
}

// DeleteSession deletes one runtime-local session.
func (c *GRPCClient) DeleteSession(ctx context.Context, threadID string) error {
	response, err := c.sessions.DeleteSession(ctx, &runtimev1.DeleteSessionRequest{
		ThreadId: threadID,
	})
	if err != nil {
		return normalizeRPCError("delete session", err)
	}
	if !response.GetDeleted() {
		return ErrNotFound
	}
	return nil
}

func normalizeRPCError(action string, err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}

	status, ok := grpcstatus.FromError(err)
	if !ok {
		return fmt.Errorf("%s: %w", action, err)
	}

	switch status.Code() {
	case codes.NotFound:
		return fmt.Errorf("%s: %w", action, ErrNotFound)
	default:
		return fmt.Errorf("%s: %w", action, err)
	}
}
