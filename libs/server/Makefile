.PHONY: lint format type typecheck test help

.DEFAULT_GOAL := help

TEST_FILE ?= tests/unit_tests
PYTHON_FILES ?= deepagents_server/ tests/

test: ## Run unit tests
	uv run --group test pytest $(TEST_FILE)

lint: ## Run linters and type checker
	[ "$(PYTHON_FILES)" = "" ] || uv run --group test ruff format $(PYTHON_FILES) --diff
	[ "$(PYTHON_FILES)" = "" ] || uv run --group test ruff check $(PYTHON_FILES) --diff
	$(MAKE) type PYTHON_FILES="$(PYTHON_FILES)"

type: ## Run type checker
	[ "$(PYTHON_FILES)" = "" ] || uv run --group test ty check $(PYTHON_FILES)

format: ## Run code formatters
	[ "$(PYTHON_FILES)" = "" ] || uv run --group test ruff format $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || uv run --group test ruff check --fix $(PYTHON_FILES)

help: ## Show this help message
	@echo "Usage: make [target] [TEST_FILE=path/to/tests/]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
