package api

import (
	"agentctl/pkg/domain"
	"errors"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

func (h *HTTPHandler) registerSessionRoutes(api *gin.RouterGroup) {
	sessions := api.Group("/sessions")
	sessions.GET("", h.handleListSessions)
	sessions.GET("/latest", h.handleGetLatestSession)
	sessions.GET("/:thread_id", h.handleGetSession)
	sessions.GET("/:thread_id/message_page", h.handleGetSessionMessagePage)
	sessions.GET("/:thread_id/messages", h.handleGetSessionMessages)
	sessions.DELETE("/:thread_id", h.handleDeleteSession)
	sessions.GET("/:thread_id/artifacts", h.handleListThreadArtifacts)
}

func (h *HTTPHandler) handleListSessions(c *gin.Context) {
	query, err := decodeListSessionsQuery(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	sessions, nextPageToken, err := h.service.ListSessions(
		c.Request.Context(),
		query.AgentName,
		query.PageSize,
		query.PageToken,
	)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}

	writeJSON(c.Writer, http.StatusOK, sessionListResponse{
		Sessions:      newHTTPSessionSummaryResponses(sessions),
		NextPageToken: nextPageToken,
	})
}

func (h *HTTPHandler) handleGetLatestSession(c *gin.Context) {
	query := decodeLatestSessionQuery(c)
	session, err := h.service.GetLatestSession(c.Request.Context(), query.AgentName)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPSessionSummaryResponse(session))
}

func (h *HTTPHandler) handleGetSession(c *gin.Context) {
	locator, err := decodeSessionLocator(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	session, err := h.service.GetSession(c.Request.Context(), locator)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPSessionSummaryResponse(session))
}

func (h *HTTPHandler) handleGetSessionMessagePage(c *gin.Context) {
	query, err := decodeSessionMessagePageQuery(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	page, err := h.service.GetSessionMessagePage(c.Request.Context(), query)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPSessionMessagePageResponse(page))
}

func (h *HTTPHandler) handleGetSessionMessages(c *gin.Context) {
	query, err := decodeSessionMessagesQuery(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	messages, nextPageToken, err := h.service.GetSessionMessages(c.Request.Context(), query)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}

	writeJSON(c.Writer, http.StatusOK, sessionMessagesResponse{
		Messages:      newHTTPSessionMessageResponses(messages),
		NextPageToken: nextPageToken,
	})
}

func (h *HTTPHandler) handleDeleteSession(c *gin.Context) {
	locator, err := decodeSessionLocator(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	if err := h.service.DeleteSession(c.Request.Context(), locator); err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	c.Status(http.StatusNoContent)
}

func (h *HTTPHandler) handleListThreadArtifacts(c *gin.Context) {
	threadID := strings.TrimSpace(c.Param("thread_id"))
	if threadID == "" {
		writeJSONError(c.Writer, http.StatusBadRequest, errors.New("thread_id is required"))
		return
	}
	agentName := strings.TrimSpace(c.Query("agent_name"))

	response, err := h.service.ListThreadArtifacts(c.Request.Context(), domain.ListArtifactsRequest{
		ThreadID:  threadID,
		AgentName: agentName,
	})
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPListArtifactsResponse(response))
}
