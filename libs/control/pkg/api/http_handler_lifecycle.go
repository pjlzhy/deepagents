package api

import (
	"agentctl/pkg/domain"
	"archive/zip"
	"errors"
	"fmt"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

func (h *HTTPHandler) registerLifecycleRoutes(api *gin.RouterGroup) {
	api.GET("/health", h.handleHealth)

	agents := api.Group("/agents")
	agents.POST("/:name/ensure_runnable", h.handleEnsureRunnable)
	agents.GET("/:name/graph", h.handleGetAgentGraph)
	agents.POST("/:name/workspace/files", h.handleUploadWorkspaceFiles)
	agents.POST("/:name/workspace/files/download", h.handleDownloadWorkspaceFiles)
	agents.GET("/:name/workspace/files", h.handleListWorkspaceFiles)
}

func (h *HTTPHandler) handleHealth(c *gin.Context) {
	resp, err := h.service.Health(c.Request.Context())
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPHealthResponse(resp))
}

func (h *HTTPHandler) handleEnsureRunnable(c *gin.Context) {
	agentName := strings.TrimSpace(c.Param("name"))

	if err := h.service.EnsureRunnable(c.Request.Context(), agentName); err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	c.Status(http.StatusAccepted)
}

func (h *HTTPHandler) handleGetAgentGraph(c *gin.Context) {
	agentName := strings.TrimSpace(c.Param("name"))
	xrayDepth := int32(0)
	if raw := strings.TrimSpace(c.Query("xray_depth")); raw != "" {
		value, err := strconv.Atoi(raw)
		if err != nil {
			writeJSONError(c.Writer, http.StatusBadRequest, errors.New("xray_depth must be an integer"))
			return
		}
		if value < 0 {
			writeJSONError(c.Writer, http.StatusBadRequest, errors.New("xray_depth must be non-negative"))
			return
		}
		xrayDepth = int32(value)
	}

	graph, err := h.service.GetAgentGraph(c.Request.Context(), agentName, xrayDepth)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}

	writeRawJSON(c.Writer, http.StatusOK, graph)
}

func (h *HTTPHandler) handleUploadWorkspaceFiles(c *gin.Context) {
	agentName := strings.TrimSpace(c.Param("name"))
	request, cleanup, err := decodeWorkspaceUploadRequest(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	defer cleanup()
	request.AgentName = agentName

	response, err := h.service.UploadWorkspaceFiles(c.Request.Context(), request)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusCreated, newHTTPWorkspaceUploadResponse(response))
}

func (h *HTTPHandler) handleDownloadWorkspaceFiles(c *gin.Context) {
	agentName := strings.TrimSpace(c.Param("name"))
	body, err := decodeJSON[struct {
		ThreadID string   `json:"thread_id"`
		Paths    []string `json:"paths"`
	}](c.Request, false)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	if len(body.Paths) == 0 {
		writeJSONError(c.Writer, http.StatusBadRequest, errors.New("paths must not be empty"))
		return
	}
	if strings.TrimSpace(body.ThreadID) == "" {
		writeJSONError(c.Writer, http.StatusBadRequest, errors.New("thread_id must not be empty"))
		return
	}

	if len(body.Paths) == 1 {
		h.streamSingleWorkspaceFileDownload(c, domain.WorkspaceFileDownloadRequest{
			AgentName: agentName,
			ThreadID:  strings.TrimSpace(body.ThreadID),
			Path:      body.Paths[0],
		})
		return
	}
	h.streamWorkspaceArchiveDownload(c, agentName, strings.TrimSpace(body.ThreadID), body.Paths)
}

func (h *HTTPHandler) handleListWorkspaceFiles(c *gin.Context) {
	agentName := strings.TrimSpace(c.Param("name"))
	threadID := strings.TrimSpace(c.Query("thread_id"))
	if threadID == "" {
		writeJSONError(c.Writer, http.StatusBadRequest, errors.New("thread_id query parameter is required"))
		return
	}
	path := strings.TrimSpace(c.Query("path"))
	if path == "" {
		path = "."
	}

	response, err := h.service.ListWorkspaceFiles(c.Request.Context(), domain.WorkspaceListRequest{
		AgentName: agentName,
		ThreadID:  threadID,
		Path:      path,
	})
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPWorkspaceListResponse(response))
}

func (h *HTTPHandler) streamSingleWorkspaceFileDownload(
	c *gin.Context,
	req domain.WorkspaceFileDownloadRequest,
) {
	filename := filepath.Base(req.Path)
	if filename == "" || filename == "." || filename == ".." {
		filename = "download"
	}

	c.Writer.Header().Set("Content-Type", "application/octet-stream")
	c.Writer.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%q", filename))
	if err := h.service.DownloadWorkspaceFile(c.Request.Context(), req, c.Writer); err != nil {
		writeServiceError(c.Writer, err)
		return
	}
}

func (h *HTTPHandler) streamWorkspaceArchiveDownload(
	c *gin.Context,
	agentName string,
	threadID string,
	paths []string,
) {
	filename := fmt.Sprintf("workspace-%s.zip", threadID)
	c.Writer.Header().Set("Content-Type", "application/zip")
	c.Writer.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%q", filename))

	archive := zip.NewWriter(c.Writer)
	defer archive.Close()

	for _, path := range paths {
		trimmedPath := strings.TrimSpace(path)
		if trimmedPath == "" {
			continue
		}
		entryWriter, err := archive.Create(trimmedPath)
		if err != nil {
			writeJSONError(c.Writer, http.StatusInternalServerError, err)
			return
		}
		if err := h.service.DownloadWorkspaceFile(
			c.Request.Context(),
			domain.WorkspaceFileDownloadRequest{
				AgentName: agentName,
				ThreadID:  threadID,
				Path:      trimmedPath,
			},
			entryWriter,
		); err != nil {
			writeServiceError(c.Writer, err)
			return
		}
	}
}
