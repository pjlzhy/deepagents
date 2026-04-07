package api

import (
	registrypkg "agentctl/pkg/registry"
	"agentctl/pkg/skillpackage"
	"errors"
	"fmt"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
)

func (h *HTTPHandler) registerResourceRoutes(api *gin.RouterGroup) {
	models := api.Group("/models")
	models.GET("", h.handleListModelConfigs)
	models.PUT("/:name", h.handleUpsertModelConfig)
	models.GET("/:name", h.handleGetModelConfig)
	models.DELETE("/:name", h.handleDeleteModelConfig)

	skills := api.Group("/skills")
	skills.GET("", h.handleListSkills)
	skills.POST("/package", h.handleCreateSkillPackage)
	skills.PUT("/:name", h.handleUpsertSkill)
	skills.GET("/:name", h.handleGetSkill)
	skills.PUT("/:name/package", h.handleReplaceSkillPackage)
	skills.GET("/:name/package", h.handleDownloadSkillPackage)
	skills.DELETE("/:name", h.handleDeleteSkill)

	mcps := api.Group("/mcps")
	mcps.GET("", h.handleListMCPConfigs)
	mcps.PUT("/:name", h.handleUpsertMCPConfig)
	mcps.GET("/:name", h.handleGetMCPConfig)
	mcps.DELETE("/:name", h.handleDeleteMCPConfig)

	sandboxes := api.Group("/sandboxes")
	sandboxes.GET("", h.handleListSandboxConfigs)
	sandboxes.PUT("/:name", h.handleUpsertSandboxConfig)
	sandboxes.GET("/:name", h.handleGetSandboxConfig)
	sandboxes.DELETE("/:name", h.handleDeleteSandboxConfig)

	agents := api.Group("/agents")
	agents.GET("", h.handleListAgentSpecs)
	agents.PUT("/:name", h.handleUpsertAgentSpec)
	agents.GET("/:name", h.handleGetAgentSpec)
	agents.DELETE("/:name", h.handleDeleteAgentSpec)
}

func (h *HTTPHandler) handleListModelConfigs(c *gin.Context) {
	query, err := decodeResourcePageQuery(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	page, err := h.service.ListModelConfigsPage(c.Request.Context(), query)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, modelConfigsListResponse{
		Models:       newHTTPModelConfigResponses(page.Items),
		pageResponse: newHTTPPageResponse(page.PageMetadata),
	})
}

func (h *HTTPHandler) handleUpsertModelConfig(c *gin.Context) {
	config, err := decodeModelConfigRequest(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	stored, err := h.service.UpsertModelConfig(c.Request.Context(), config)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPModelConfigResponse(stored))
}

func (h *HTTPHandler) handleGetModelConfig(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	config, err := h.service.GetModelConfig(c.Request.Context(), name)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPModelConfigResponse(config))
}

func (h *HTTPHandler) handleDeleteModelConfig(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	if err := h.service.DeleteModelConfig(c.Request.Context(), name); err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	c.Status(http.StatusNoContent)
}

func (h *HTTPHandler) handleListSkills(c *gin.Context) {
	query, err := decodeResourcePageQuery(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	page, err := h.service.ListSkillsPage(c.Request.Context(), query)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, skillsListResponse{
		Skills:       newHTTPSkillSummaryResponses(page.Items),
		pageResponse: newHTTPPageResponse(page.PageMetadata),
	})
}

func (h *HTTPHandler) handleCreateSkillPackage(c *gin.Context) {
	upload, err := decodeSkillPackageUploadRequest(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	snapshot, err := skillpackage.ParseZip(upload.Content, skillpackage.ParseOptions{
		Status: upload.Status,
	})
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	if _, err := h.service.GetSkill(c.Request.Context(), snapshot.Skill.Name); err == nil {
		writeJSONError(c.Writer, http.StatusConflict, fmt.Errorf("skill %q already exists", snapshot.Skill.Name))
		return
	} else if !errors.Is(err, registrypkg.ErrNotFound) {
		writeServiceError(c.Writer, err)
		return
	}

	stored, err := h.service.UpsertSkill(c.Request.Context(), snapshot.Skill)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusCreated, newHTTPSkillDetailResponse(stored))
}

func (h *HTTPHandler) handleUpsertSkill(c *gin.Context) {
	skill, err := decodeSkillRequest(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	stored, err := h.service.UpsertSkill(c.Request.Context(), skill)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPSkillResponse(stored))
}

func (h *HTTPHandler) handleGetSkill(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	skill, err := h.service.GetSkill(c.Request.Context(), name)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPSkillDetailResponse(skill))
}

func (h *HTTPHandler) handleReplaceSkillPackage(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	current, err := h.service.GetSkill(c.Request.Context(), name)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}

	upload, err := decodeSkillPackageUploadRequest(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	status := upload.Status
	if status == "" {
		status = current.Status
	}

	snapshot, err := skillpackage.ParseZip(upload.Content, skillpackage.ParseOptions{
		ExpectedName: name,
		Status:       status,
	})
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	stored, err := h.service.UpsertSkill(c.Request.Context(), snapshot.Skill)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPSkillDetailResponse(stored))
}

func (h *HTTPHandler) handleDownloadSkillPackage(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	skill, err := h.service.GetSkill(c.Request.Context(), name)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}

	archive, err := skillpackage.BuildZip(skill)
	if err != nil {
		writeJSONError(c.Writer, http.StatusInternalServerError, err)
		return
	}

	filename := fmt.Sprintf("%s.zip", skill.Name)
	c.Header("Content-Type", "application/zip")
	c.Header("Content-Disposition", fmt.Sprintf("attachment; filename=%q", filename))
	c.Header("Content-Length", strconv.Itoa(len(archive)))
	c.Status(http.StatusOK)
	_, _ = c.Writer.Write(archive)
}

func (h *HTTPHandler) handleDeleteSkill(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	if err := h.service.DeleteSkill(c.Request.Context(), name); err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	c.Status(http.StatusNoContent)
}

func (h *HTTPHandler) handleListMCPConfigs(c *gin.Context) {
	query, err := decodeResourcePageQuery(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	page, err := h.service.ListMCPConfigsPage(c.Request.Context(), query)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, mcpConfigsListResponse{
		MCPs:         newHTTPMCPConfigResponses(page.Items),
		pageResponse: newHTTPPageResponse(page.PageMetadata),
	})
}

func (h *HTTPHandler) handleUpsertMCPConfig(c *gin.Context) {
	config, err := decodeMCPConfigRequest(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	stored, err := h.service.UpsertMCPConfig(c.Request.Context(), config)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPMCPConfigResponse(stored))
}

func (h *HTTPHandler) handleGetMCPConfig(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	config, err := h.service.GetMCPConfig(c.Request.Context(), name)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPMCPConfigResponse(config))
}

func (h *HTTPHandler) handleDeleteMCPConfig(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	if err := h.service.DeleteMCPConfig(c.Request.Context(), name); err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	c.Status(http.StatusNoContent)
}

func (h *HTTPHandler) handleListSandboxConfigs(c *gin.Context) {
	query, err := decodeResourcePageQuery(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	page, err := h.service.ListSandboxConfigsPage(c.Request.Context(), query)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, sandboxConfigsListResponse{
		Sandboxes:    newHTTPSandboxConfigResponses(page.Items),
		pageResponse: newHTTPPageResponse(page.PageMetadata),
	})
}

func (h *HTTPHandler) handleUpsertSandboxConfig(c *gin.Context) {
	config, err := decodeSandboxConfigRequest(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	stored, err := h.service.UpsertSandboxConfig(c.Request.Context(), config)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPSandboxConfigResponse(stored))
}

func (h *HTTPHandler) handleGetSandboxConfig(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	config, err := h.service.GetSandboxConfig(c.Request.Context(), name)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPSandboxConfigResponse(config))
}

func (h *HTTPHandler) handleDeleteSandboxConfig(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	if err := h.service.DeleteSandboxConfig(c.Request.Context(), name); err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	c.Status(http.StatusNoContent)
}

func (h *HTTPHandler) handleListAgentSpecs(c *gin.Context) {
	query, err := decodeResourcePageQuery(c.Request)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}

	page, err := h.service.ListAgentSpecsPage(c.Request.Context(), query)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, agentSpecsListResponse{
		Agents:       newHTTPAgentSpecResponses(page.Items),
		pageResponse: newHTTPPageResponse(page.PageMetadata),
	})
}

func (h *HTTPHandler) handleUpsertAgentSpec(c *gin.Context) {
	spec, err := decodeAgentSpecRequest(c)
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	stored, err := h.service.UpsertAgentSpec(c.Request.Context(), spec)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPAgentSpecResponse(stored))
}

func (h *HTTPHandler) handleGetAgentSpec(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	spec, err := h.service.GetAgentSpec(c.Request.Context(), name)
	if err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	writeJSON(c.Writer, http.StatusOK, newHTTPAgentSpecResponse(spec))
}

func (h *HTTPHandler) handleDeleteAgentSpec(c *gin.Context) {
	name, err := decodeResourceName(c, "name")
	if err != nil {
		writeJSONError(c.Writer, http.StatusBadRequest, err)
		return
	}
	if err := h.service.DeleteAgentSpec(c.Request.Context(), name); err != nil {
		writeServiceError(c.Writer, err)
		return
	}
	c.Status(http.StatusNoContent)
}
