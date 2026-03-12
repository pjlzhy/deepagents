.PHONY: format lint type typecheck test help

.DEFAULT_GOAL := help

TEST_FILE ?= tests/unit_tests/

test: ## Run unit tests
	uv run --group test pytest --disable-socket --allow-unix-socket $(TEST_FILE) \
		--cov=deepagents_runtime \
		--cov-report=term-missing

lint: ## Run linters and type checker
	uv run --all-groups ruff check deepagents_runtime tests
	uv run --all-groups ruff format deepagents_runtime tests --diff
	$(MAKE) type

type: ## Run type checker
	uv run --all-groups ty check deepagents_runtime

format: ## Run code formatters
	uv run --all-groups ruff format deepagents_runtime tests
	uv run --all-groups ruff check --fix deepagents_runtime tests

help: ## Show this help message
	@echo "Usage: make [target] [TEST_FILE=path/to/tests/]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
