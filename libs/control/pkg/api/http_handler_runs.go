package api

import (
	"agentctl/pkg/streamproxy"
	"context"
	"errors"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

func (h *HTTPHandler) registerRunRoutes(api *gin.RouterGroup) {
	agents := api.Group("/agents")
	agents.POST("/:name/runs/stream", h.handleRunStream)
	agents.POST("/:name/telemetry/stream", h.handleTelemetryStream)

	runSessions := api.Group("/run_sessions")
	runSessions.POST("/:session_id/cancel", h.handleRunCancel)
	runSessions.POST("/:session_id/hitl_decisions", h.handleRunHITLDecisions)
}

func (h *HTTPHandler) handleRunStream(c *gin.Context) {
	agentName := strings.TrimSpace(c.Param("name"))

	req, err := decodeRunStreamRequest(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	req.AgentName = agentName

	runStream, err := h.service.RunAgent(c.Request.Context(), req)
	if err != nil {
		writeJSONError(c.Writer, http.StatusInternalServerError, err)
		return
	}

	downstream, err := newSSERunDownstream(c.Writer)
	if err != nil {
		_ = runStream.Close()
		writeJSONError(c.Writer, http.StatusInternalServerError, err)
		return
	}

	sessionID, err := newRunSessionID()
	if err != nil {
		_ = runStream.Close()
		writeJSONError(c.Writer, http.StatusInternalServerError, err)
		return
	}

	h.runSessions.Store(sessionID, downstream)
	defer func() {
		h.runSessions.Delete(sessionID)
		downstream.Close()
	}()

	prepareSSEHeaders(c.Writer, sessionID)
	if err := downstream.SendEnvelope(
		c.Request.Context(),
		"run_session",
		map[string]string{"session_id": sessionID},
	); err != nil {
		return
	}

	proxy := h.newProxy()
	if proxy == nil {
		_ = downstream.SendEnvelope(
			c.Request.Context(),
			"transport_error",
			errorResponse{Error: "run proxy is not configured"},
		)
		return
	}

	if err := proxy.Proxy(c.Request.Context(), runStream, downstream); err != nil &&
		!errors.Is(err, context.Canceled) &&
		!errors.Is(err, context.DeadlineExceeded) {
		_ = downstream.SendEnvelope(
			c.Request.Context(),
			"transport_error",
			errorResponse{Error: err.Error()},
		)
	}
}

func (h *HTTPHandler) handleTelemetryStream(c *gin.Context) {
	agentName := strings.TrimSpace(c.Param("name"))

	req, err := decodeRunStreamRequest(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	req.AgentName = agentName

	telemetryStream, err := h.service.RunAgentTelemetry(c.Request.Context(), req)
	if err != nil {
		writeJSONError(c.Writer, http.StatusInternalServerError, err)
		return
	}

	downstream, err := newSSERunDownstream(c.Writer)
	if err != nil {
		_ = telemetryStream.Close()
		writeJSONError(c.Writer, http.StatusInternalServerError, err)
		return
	}

	sessionID, err := newRunSessionID()
	if err != nil {
		_ = telemetryStream.Close()
		writeJSONError(c.Writer, http.StatusInternalServerError, err)
		return
	}

	h.runSessions.Store(sessionID, downstream)
	defer func() {
		h.runSessions.Delete(sessionID)
		downstream.Close()
	}()

	prepareSSEHeaders(c.Writer, sessionID)
	if err := downstream.SendEnvelope(
		c.Request.Context(),
		"run_session",
		map[string]string{"session_id": sessionID},
	); err != nil {
		return
	}

	recordingDownstream := &recordingTelemetryDownstream{
		downstream: downstream,
		recorder:   h.service,
	}

	proxy := streamproxy.NewDefaultTelemetryProxy()
	if err := proxy.ProxyTelemetry(c.Request.Context(), telemetryStream, recordingDownstream); err != nil &&
		!errors.Is(err, context.Canceled) &&
		!errors.Is(err, context.DeadlineExceeded) {
		_ = downstream.SendEnvelope(
			c.Request.Context(),
			"transport_error",
			errorResponse{Error: err.Error()},
		)
	}
}

func (h *HTTPHandler) handleRunCancel(c *gin.Context) {
	sessionID := strings.TrimSpace(c.Param("session_id"))
	request, err := decodeCancelRequest(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	session, err := h.runSessions.Load(sessionID)
	if err != nil {
		writeJSONError(c.Writer, http.StatusNotFound, err)
		return
	}
	if err := session.EnqueueCancel(streamproxy.CancelSignal{Reason: request.Reason}); err != nil {
		writeSessionControlError(c.Writer, err)
		return
	}
	c.Status(http.StatusAccepted)
}

func (h *HTTPHandler) handleRunHITLDecisions(c *gin.Context) {
	sessionID := strings.TrimSpace(c.Param("session_id"))
	request, err := decodeHITLDecisionRequest(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	session, err := h.runSessions.Load(sessionID)
	if err != nil {
		writeJSONError(c.Writer, http.StatusNotFound, err)
		return
	}
	if err := session.EnqueueDecision(streamproxy.DecisionEnvelope{
		InterruptID: request.InterruptID,
		Decisions:   request.Decisions,
	}); err != nil {
		writeSessionControlError(c.Writer, err)
		return
	}
	c.Status(http.StatusAccepted)
}
