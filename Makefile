.PHONY: help install-dev check-pytest test test-docker-db test-unit test-integration test-phase1 test-file test-k

PYTHON ?= python
PYTEST ?= $(PYTHON) -m pytest
PYTEST_FLAGS ?= -q
TEST_DB_HOST ?= localhost
TEST_DB_PORT ?= 5432
TEST_DB_NAME ?= efficientai
TEST_DB_USER ?= efficientai
TEST_DB_PASSWORD ?= password
TEST_DATABASE_URL ?= postgresql://$(TEST_DB_USER):$(TEST_DB_PASSWORD)@$(TEST_DB_HOST):$(TEST_DB_PORT)/$(TEST_DB_NAME)

help: ## Show available make targets
	@echo "Available targets:"
	@echo "  make install-dev       - install project + dev dependencies"
	@echo "  make test              - run all tests under tests/"
	@echo "  make test-docker-db    - run tests against running Docker Compose Postgres"
	@echo "  make test-unit         - run unit tests (marker: unit)"
	@echo "  make test-integration  - run integration tests (marker: integration)"
	@echo "  make test-phase1       - run current Phase 1 suites"
	@echo "  make test-file FILE=...- run a specific test file/path"
	@echo "  make test-k K=...      - run tests matching expression"

install-dev: ## Install project and dev dependencies
	$(PYTHON) -m pip install -e ".[dev]"

check-pytest:
	@$(PYTHON) -c "import pytest" >/dev/null 2>&1 || ( \
		echo "pytest is not installed in the current environment."; \
		echo "Run: make install-dev"; \
		echo "or:  $(PYTHON) -m pip install pytest pytest-asyncio pytest-cov pytest-mock"; \
		exit 1; \
	)

test: check-pytest ## Run the full test suite
	$(PYTEST) tests $(PYTEST_FLAGS) $(PYTEST_ARGS)

test-docker-db: check-pytest ## Run tests against running Docker Compose Postgres
	TEST_DATABASE_URL="$(TEST_DATABASE_URL)" DATABASE_URL="$(TEST_DATABASE_URL)" \
	POSTGRES_HOST="$(TEST_DB_HOST)" POSTGRES_PORT="$(TEST_DB_PORT)" POSTGRES_DB="$(TEST_DB_NAME)" \
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
