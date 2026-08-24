SHELL := /bin/bash

DEV_COMPOSE := docker compose --env-file deployment/env/versions.env \
	-f deployment/compose/compose.dev.yaml
MOCK_COMPOSE := docker compose --env-file deployment/env/versions.env \
	-f deployment/compose/compose.mock.yaml
ISAAC_ENV_FILE ?= deployment/env/.env
ISAAC_COMPOSE := docker compose --env-file deployment/env/versions.env \
	--env-file $(ISAAC_ENV_FILE) -f deployment/compose/compose.isaac.yaml
BASE_PATHS := packages agents tasks evaluators tests
COLCON_ENV := COLCON_DEFAULTS_FILE=$(CURDIR)/colcon.defaults.yaml

CURRENT_USER := $(shell id -un)
export HOST_UID := $(shell id -u $(CURRENT_USER))
export HOST_GID := $(shell id -g $(CURRENT_USER))

.PHONY: help dev-image dev-shell dev-list dev-build dev-test dev-lint dev-check \
	mock-image mock-e2e isaac-config isaac-image isaac-up isaac-gui isaac-down isaac-smoke \
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
	@echo "  make mock-image Build the CPU mock runtime image"
	@echo "  make mock-e2e   Run and validate the three-container mock stack"
	@echo "  make isaac-config Validate the Isaac Compose configuration"
	@echo "  make isaac-image Build the pinned Isaac env image"
	@echo "  make isaac-up    Start the Isaac env using the configured mode"
	@echo "  make isaac-gui   Build and run the Isaac GUI until Ctrl-C"
	@echo "  make isaac-down  Stop the Isaac validation stack"
	@echo "  make isaac-smoke Run the manual GPU/ROS 2 Bridge smoke"

dev-image:
	$(DEV_COMPOSE) build dev

dev-shell:
	$(DEV_COMPOSE) run --rm dev bash

dev-list:
	$(DEV_COMPOSE) run --rm dev make list-local

dev-build:
	$(DEV_COMPOSE) run --rm dev make build-local

dev-test:
	$(DEV_COMPOSE) run --rm dev make test-local

dev-lint:
	$(DEV_COMPOSE) run --rm dev make lint-local

dev-check:
	$(DEV_COMPOSE) run --rm dev make check-local

mock-image:
	$(MOCK_COMPOSE) build experiment

mock-e2e:
	tools/e2e/run_mock_compose.sh

isaac-config:
	$(ISAAC_COMPOSE) config --quiet

isaac-image:
	$(ISAAC_COMPOSE) build env

isaac-up:
	$(ISAAC_COMPOSE) up --detach env

isaac-gui:
	RH_ISAAC_ENV_FILE=$(ISAAC_ENV_FILE) tools/dev/run_isaac_gui.sh

isaac-down:
	$(ISAAC_COMPOSE) down --remove-orphans

isaac-smoke:
	RH_ISAAC_ENV_FILE=$(ISAAC_ENV_FILE) tools/e2e/run_isaac_bridge_smoke.sh

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
	python3 tools/validation/check_isaac_skeleton.py
	bash -n deployment/docker/env/entrypoint.sh \
		simulators/isaac/scripts/launch.sh tools/dev/run_isaac_gui.sh \
		tools/e2e/run_isaac_bridge_smoke.sh
	ruff check tools tests packages agents tasks evaluators simulators

check-local: lint-local list-local test-local
