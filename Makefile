.PHONY: help install test lint lint-fix format format-fix reformat all clean build

# Project variables
PROJECT_DIR := source-sapreadtable
UV := uv
PYTEST_FLAGS := --cov=source_sapreadtable --cov-report=term-missing --cov-fail-under=90

help:
	@echo "Available commands:"
	@echo "  make install          - Install dependencies using uv"
	@echo "  make test             - Run all tests"
	@echo "  make lint             - Lint code with Ruff (no fixes)"
	@echo "  make lint-fix         - Lint code with Ruff and auto-fix"
	@echo "  make format           - Check formatting with Ruff"
	@echo "  make format-fix       - Format code with Ruff"
	@echo "  make reformat         - Run format-fix and lint-fix"
	@echo "  make clean            - Remove build artifacts and virtual environments"
	@echo "  make build            - Build the docker image"

install:
	@echo "Installing dependencies in $(PROJECT_DIR)..."
	@cd $(PROJECT_DIR) && $(UV) sync

test: install
	@echo "Running all tests..."
	@cd $(PROJECT_DIR) && $(UV) run pytest $(PYTEST_FLAGS)

lint:
	@echo "Linting..."
	@cd $(PROJECT_DIR) && $(UV) run ruff check .

lint-fix:
	@echo "Linting with fixes..."
	@cd $(PROJECT_DIR) && $(UV) run ruff check . --fix

format:
	@echo "Formatting..."
	@cd $(PROJECT_DIR) && $(UV) run ruff format . --check

format-fix:
	@echo "Formatting with fixes..."
	@cd $(PROJECT_DIR) && $(UV) run ruff format .

reformat: format-fix lint-fix
	@echo "Formatted and linted with fixes."

all: install format lint test

clean:
	@echo "Cleaning..."
	@rm -rf $(PROJECT_DIR)/.venv
	@rm -rf $(PROJECT_DIR)/.ruff_cache
	@rm -rf $(PROJECT_DIR)/.pytest_cache
	@rm -rf $(PROJECT_DIR)/dist
	@rm -rf $(PROJECT_DIR)/*.egg-info
	@find . -type d -name "__pycache__" -exec rm -rf {} +

build:
	@echo "Building Docker image..."
	@cd $(PROJECT_DIR) && docker build . -t airbyte/source-sapreadtable:dev
