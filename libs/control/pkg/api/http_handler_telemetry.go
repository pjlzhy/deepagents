package api

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

func (h *HTTPHandler) registerTelemetryRoutes(api *gin.RouterGroup) {
	telemetry := api.Group("/telemetry")
	telemetry.GET("/runs", h.handleListTelemetryRuns)
	telemetry.GET("/runs/:run_id", h.handleGetTelemetryRun)
	telemetry.GET("/runs/:run_id/snapshot", h.handleGetTelemetryRunSnapshot)
	telemetry.GET("/runs/:run_id/events", h.handleListTelemetryEvents)
}

func (h *HTTPHandler) handleListTelemetryRuns(c *gin.Context) {
	query, err := decodeTelemetryRunsQuery(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	page, err := h.service.ListTelemetryRuns(c.Request.Context(), query)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}

	items := make([]telemetryRunResponse, 0, len(page.Items))
	for _, item := range page.Items {
		items = append(items, newHTTPTelemetryRunResponse(item))
	}

	writeJSON(c.Writer, http.StatusOK, telemetryRunsListResponse{
		Runs:         items,
		pageResponse: newHTTPPageResponse(page.PageMetadata),
	})
}

func (h *HTTPHandler) handleGetTelemetryRun(c *gin.Context) {
	runID := strings.TrimSpace(c.Param("run_id"))
	run, err := h.service.GetTelemetryRun(c.Request.Context(), runID)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPTelemetryRunResponse(run))
}

func (h *HTTPHandler) handleGetTelemetryRunSnapshot(c *gin.Context) {
	query, err := decodeTelemetryRunSnapshotQuery(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	page, err := h.service.GetTelemetryRunSnapshot(
		c.Request.Context(),
		query.RunID,
		query.Position,
		query.MessageQuery,
	)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPSessionMessagePageResponse(page))
}

func (h *HTTPHandler) handleListTelemetryEvents(c *gin.Context) {
	runID := strings.TrimSpace(c.Param("run_id"))
	query, err := decodeResourcePageQuery(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	page, err := h.service.ListTelemetryEvents(c.Request.Context(), runID, query)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}

	items := make([]httpTelemetryEvent, 0, len(page.Items))
	for _, item := range page.Items {
		items = append(items, newHTTPTelemetryEventRecord(item))
	}

	writeJSON(c.Writer, http.StatusOK, telemetryEventsListResponse{
		Events:       items,
		pageResponse: newHTTPPageResponse(page.PageMetadata),
	})
}
