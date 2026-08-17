SHELL := /bin/bash

COMPOSE := docker compose --env-file deployment/env/versions.env \
	-f deployment/compose/compose.dev.yaml
BASE_PATHS := packages agents tasks evaluators tests
COLCON_ENV := COLCON_DEFAULTS_FILE=$(CURDIR)/colcon.defaults.yaml

CURRENT_USER := $(shell id -un)
export HOST_UID := $(shell id -u $(CURRENT_USER))
export HOST_GID := $(shell id -g $(CURRENT_USER))

.PHONY: help dev-image dev-shell dev-list dev-build dev-test dev-lint dev-check \
	list-local build-local test-local lint-local check-local

help:
	@echo "RoboHarness development commands (Docker is the supported environment):"
	@echo "  make dev-image  Build the CPU development image"
	@echo "  make dev-shell  Open an interactive development shell"
	@echo "  make dev-list   Discover ROS packages"
	@echo "  make dev-build  Build all ROS packages"
	@echo "  make dev-test   Run ROS package tests"
	@echo "  make dev-lint   Run repository validation and lint"
	@echo "  make dev-check  Run the complete PR/CI check"

dev-image:
	$(COMPOSE) build dev

dev-shell:
	$(COMPOSE) run --rm dev bash

dev-list:
	$(COMPOSE) run --rm dev make list-local

dev-build:
	$(COMPOSE) run --rm dev make build-local

dev-test:
	$(COMPOSE) run --rm dev make test-local

dev-lint:
	$(COMPOSE) run --rm dev make lint-local

dev-check:
	$(COMPOSE) run --rm dev make check-local

# The *-local targets are internal entry points used inside the development image.
list-local:
	$(COLCON_ENV) colcon list --base-paths $(BASE_PATHS)

build-local:
	$(COLCON_ENV) colcon build --base-paths $(BASE_PATHS)

test-local: build-local
	mkdir -p .build/colcon/test-results
	$(COLCON_ENV) colcon test --base-paths $(BASE_PATHS)
	$(COLCON_ENV) colcon test-result --verbose

lint-local:
	python3 tools/validation/check_repository.py
	ruff check tools tests packages agents tasks evaluators

check-local: lint-local list-local test-local
