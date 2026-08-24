.PHONY: help install-dev check-pytest test test-parallel test-docker-db test-unit test-integration test-phase1 test-file test-k test-sharding test-sharding-integration

PYTHON ?= python
PYTEST ?= $(PYTHON) -m pytest
PYTEST_FLAGS ?= -q
TEST_DB_HOST ?= localhost
TEST_DB_PORT ?= 5432
TEST_DB_NAME ?= efficientai
# Dedicated DB for test-docker-db / local Postgres runs (matches CI; not the dev DB).
TEST_DOCKER_DB_NAME ?= efficientai_test
TEST_DB_USER ?= efficientai
TEST_DB_PASSWORD ?= password
TEST_DATABASE_URL ?= postgresql://$(TEST_DB_USER):$(TEST_DB_PASSWORD)@$(TEST_DB_HOST):$(TEST_DB_PORT)/$(TEST_DB_NAME)

help: ## Show available make targets
	@echo "Available targets:"
	@echo "  make install-dev       - install project + dev dependencies"
	@echo "  make test              - run all tests under tests/"
	@echo "  make test-parallel     - run all tests with pytest-xdist (-n auto)"
	@echo "  make test-docker-db    - run tests against running Docker Compose Postgres"
	@echo "  make test-unit         - run unit tests (marker: unit)"
	@echo "  make test-integration  - run integration tests (marker: integration)"
	@echo "  make test-phase1       - run current Phase 1 suites"
	@echo "  make test-file FILE=...- run a specific test file/path"
	@echo "  make test-sharding       - run call-import db_sharding tests (unit; no integration marker)"
	@echo "  make test-sharding-integration - run 2-shard Postgres integration tests (CI)"

install-dev: ## Install project and dev dependencies
	$(PYTHON) -m pip install -e ".[dev]"

check-pytest:
	@$(PYTHON) -c "import pytest" >/dev/null 2>&1 || ( \
		echo "pytest is not installed in the current environment."; \
		echo "Run: make install-dev"; \
		echo "or:  $(PYTHON) -m pip install pytest pytest-asyncio pytest-cov pytest-mock"; \
		exit 1; \
	)

check-pytest-xdist: check-pytest
	@$(PYTHON) -c "import xdist" >/dev/null 2>&1 || ( \
		echo "pytest-xdist is not installed in the current environment."; \
		echo "Run: make install-dev"; \
		echo "or:  $(PYTHON) -m pip install pytest-xdist"; \
		exit 1; \
	)

test: check-pytest ## Run the full test suite
	$(PYTEST) tests $(PYTEST_FLAGS) $(PYTEST_ARGS)

test-parallel: check-pytest-xdist ## Run the full test suite in parallel (pytest-xdist)
	$(PYTEST) tests $(PYTEST_FLAGS) -n auto --dist loadscope $(PYTEST_ARGS)

test-docker-db: check-pytest ## Run tests against running Docker Compose Postgres
	@PGPASSWORD="$(TEST_DB_PASSWORD)" psql -h "$(TEST_DB_HOST)" -p "$(TEST_DB_PORT)" -U "$(TEST_DB_USER)" -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$(TEST_DOCKER_DB_NAME)'" | grep -q 1 \
	|| PGPASSWORD="$(TEST_DB_PASSWORD)" psql -h "$(TEST_DB_HOST)" -p "$(TEST_DB_PORT)" -U "$(TEST_DB_USER)" -d postgres -c "CREATE DATABASE \"$(TEST_DOCKER_DB_NAME)\";"
	TEST_DATABASE_URL="postgresql://$(TEST_DB_USER):$(TEST_DB_PASSWORD)@$(TEST_DB_HOST):$(TEST_DB_PORT)/$(TEST_DOCKER_DB_NAME)" \
	DATABASE_URL="postgresql://$(TEST_DB_USER):$(TEST_DB_PASSWORD)@$(TEST_DB_HOST):$(TEST_DB_PORT)/$(TEST_DOCKER_DB_NAME)" \
	POSTGRES_HOST="$(TEST_DB_HOST)" POSTGRES_PORT="$(TEST_DB_PORT)" POSTGRES_DB="$(TEST_DOCKER_DB_NAME)" \
	POSTGRES_USER="$(TEST_DB_USER)" POSTGRES_PASSWORD="$(TEST_DB_PASSWORD)" \
	$(PYTEST) tests $(PYTEST_FLAGS) $(PYTEST_ARGS)

test-unit: check-pytest ## Run tests marked as unit
	$(PYTEST) -m "unit" tests $(PYTEST_FLAGS) $(PYTEST_ARGS)

test-integration: check-pytest ## Run tests marked as integration
	$(PYTEST) -m "integration" tests $(PYTEST_FLAGS) $(PYTEST_ARGS)

test-phase1: check-pytest ## Run Phase 1 test suites
	$(PYTEST) tests/test_core tests/test_models tests/test_utils tests/test_services/test_helpers $(PYTEST_FLAGS) $(PYTEST_ARGS)

test-file: check-pytest ## Run one test module/file; usage: make test-file FILE=tests/test_core/test_password.py
	@if [ -z "$(FILE)" ]; then echo "FILE is required. Example: make test-file FILE=tests/test_core/test_password.py"; exit 1; fi
	$(PYTEST) $(FILE) $(PYTEST_FLAGS) $(PYTEST_ARGS)

test-k: check-pytest ## Run tests by keyword expression; usage: make test-k K=password
	@if [ -z "$(K)" ]; then echo "K is required. Example: make test-k K=password"; exit 1; fi
	$(PYTEST) tests -k "$(K)" $(PYTEST_FLAGS) $(PYTEST_ARGS)

test-sharding: check-pytest ## Run db_sharding unit tests (excludes integration marker)
	$(PYTEST) tests/test_db_sharding -m "not integration" $(PYTEST_FLAGS) $(PYTEST_ARGS)

test-sharding-integration: check-pytest ## Run 2-shard Postgres sharding integration tests
	@if [ -z "$$SHARDING_INTEGRATION_TEST" ]; then export SHARDING_INTEGRATION_TEST=1; fi
	$(PYTEST) tests/test_db_sharding/test_sharding_postgres_integration.py -m integration $(PYTEST_FLAGS) $(PYTEST_ARGS)
