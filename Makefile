.PHONY: help install test test-unit test-integration lint format clean build run

# Project variables
PROJECT_DIR := source-sapreadtable
UV := uv

help:
	@echo "Available commands:"
	@echo "  make install          - Install dependencies using uv"
	@echo "  make test             - Run all tests"
	@echo "  make test-unit        - Run unit tests"
	@echo "  make test-integration - Run integration tests"
	@echo "  make lint             - Lint code with Ruff"
	@echo "  make format           - Format code with Ruff"
	@echo "  make clean            - Remove build artifacts and virtual environments"
	@echo "  make build            - Build the docker image"

install:
	@echo "Installing dependencies in $(PROJECT_DIR)..."
	@cd $(PROJECT_DIR) && $(UV) sync

test: install
	@echo "Running all tests..."
	@cd $(PROJECT_DIR) && $(UV) run pytest

test-unit: install
	@echo "Running unit tests..."
	@cd $(PROJECT_DIR) && $(UV) run pytest unit_tests

test-integration: install
	@echo "Running integration tests..."
	@cd $(PROJECT_DIR) && $(UV) run pytest integration_tests

lint:
	@echo "Linting..."
	@cd $(PROJECT_DIR) && $(UV) run ruff check .

format:
	@echo "Formatting..."
	@cd $(PROJECT_DIR) && $(UV) run ruff format .

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
