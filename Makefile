.PHONY: dev setup-hermes test lint typecheck openapi openapi.check blocking-audit secret-policy deployment-policy frontend.install frontend.check frontend.test frontend.a11y frontend.size run format clean clean-all docker-build docker-up docker-down docker-logs docker-config docker-prod-config docker-validate docker-build-api docker-build-frontend docker-build-nicegui deploy-config test-gui test-gui-e2e test-gui-a11y test-all docker-gui-build docker-gui-up docker-gui-down docker-gui-logs docker-gui-build-gpu docker-gui-up-gpu docker-gui-down-gpu

PROD_IMAGE_TAG ?= $(shell git rev-parse --verify HEAD)

dev:                             ## Install all dev dependencies
	uv sync --all-extras --group dev

setup-hermes:                    ## Configure Hermes for your hardware (GPU, models, providers)
	uv run sophia lectures setup

test:                            ## Run test suite with coverage
	uv run pytest --tb=short -q --cov=src/sophia --cov-fail-under=85

lint: secret-policy              ## Lint, secret policy, and format check
	uv run ruff check . && uv run ruff format --check .

typecheck:                       ## Type check with pyright
	uv run pyright

openapi:                         ## Export deterministic OpenAPI JSON for frontend clients
	uv run python scripts/export_openapi.py

openapi.check:                   ## Verify committed OpenAPI JSON is current
	uv run python scripts/export_openapi.py --check

blocking-audit:                  ## Audit async API routers for blocking I/O
	uv run python scripts/blocking_audit.py --check

secret-policy:                   ## Reject hard-coded production-like secret literals
	uv run python scripts/secret_policy.py --check

deployment-policy:               ## Validate production Compose image and topology policy
	uv run python scripts/deployment_policy.py --check

frontend.install:                ## Install frontend dependencies
	pnpm -C frontend install

frontend.check:                  ## Run frontend code generation, type checks, lint, unit tests, and size gate
	pnpm -C frontend run paraglide:check
	pnpm -C frontend run check
	pnpm -C frontend run lint
	pnpm -C frontend run test:unit
	pnpm -C frontend run size-limit

frontend.test:                   ## Run frontend unit and E2E tests
	pnpm -C frontend run test:unit
	pnpm -C frontend run test:e2e

frontend.a11y:                   ## Run frontend accessibility and German overflow gates
	pnpm -C frontend run test:e2e -- a11y.spec.ts de-overflow.spec.ts

run:                             ## Run sophia CLI
	uv run sophia

format:                          ## Format code with ruff
	uv run ruff format .

clean:                           ## Remove build artifacts (preserves .venv)
	rm -rf dist/ .pytest_cache/ .ruff_cache/ __pycache__/ .coverage coverage.xml

clean-all: clean                 ## Remove everything including .venv
	rm -rf .venv/

docker-build:                    ## Build Docker image
	docker compose build

docker-build-api:                ## Build API Docker image
	docker compose build api

docker-build-frontend:           ## Build frontend Docker image
	docker compose build frontend

docker-build-nicegui:            ## Build transitional NiceGUI Docker image
	docker build -f Dockerfile.nicegui -t sophia-nicegui:latest .

docker-up:                       ## Start services (detached)
	docker compose up -d

docker-down:                     ## Stop services
	docker compose down

docker-logs:                     ## Tail service logs
	docker compose logs -f

docker-config:                   ## Validate development Compose configuration
	docker compose config

docker-prod-config:              ## Validate production Compose configuration
	IMAGE_TAG=$(PROD_IMAGE_TAG) docker compose -f docker-compose.prod.yml config

docker-validate: docker-config docker-prod-config deployment-policy ## Validate all Compose configurations and deployment policy

deploy-config: docker-prod-config ## Alias for deployment configuration validation

docker-backup:                   ## Backup SQLite from Docker volume
	docker compose cp sophia:/data/sophia.db ./sophia-backup-$$(date +%Y%m%d).db
	@echo "Backup saved to sophia-backup-$$(date +%Y%m%d).db"

test-gui:                        ## Run GUI unit tests
	uv run pytest tests/unit/gui/ -v

test-gui-e2e:                    ## Run GUI E2E tests (Playwright)
	uv run pytest tests/integration/gui/ -m e2e -v

test-gui-a11y:                   ## Run accessibility tests
	uv run pytest tests/integration/gui/ -m e2e -k accessibility -v

test-all:                        ## Run all tests (unit + E2E)
	uv run pytest --tb=short -q && uv run pytest -m e2e --tb=short -q

docker-gui-build:                ## Build GUI Docker image
	docker compose build sophia-gui

docker-gui-up:                   ## Start GUI service (detached)
	docker compose up -d

docker-gui-down:                 ## Stop GUI service
	docker compose down

docker-gui-logs:                 ## Tail GUI service logs
	docker compose logs -f sophia-gui

docker-gui-build-gpu:            ## Build GPU Docker image (requires NVIDIA Container Toolkit)
	docker compose build sophia-gui-gpu

docker-gui-up-gpu:               ## Start GPU service (detached, requires NVIDIA Container Toolkit)
	docker compose --profile gpu up -d sophia-gui-gpu

docker-gui-down-gpu:             ## Stop GPU service
	docker compose --profile gpu down
