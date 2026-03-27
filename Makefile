.PHONY: dev setup-hermes test lint typecheck run format clean clean-all docker-build docker-up docker-down docker-logs test-gui test-gui-e2e test-gui-a11y test-all docker-gui-build docker-gui-up docker-gui-down docker-gui-logs

dev:                             ## Install all dev dependencies
	uv sync --all-extras --group dev

setup-hermes:                    ## Configure Hermes for your hardware (GPU, models, providers)
	uv run sophia lectures setup

test:                            ## Run test suite with coverage
	uv run pytest --tb=short -q --cov=src/sophia --cov-fail-under=85

lint:                            ## Lint and format check
	uv run ruff check . && uv run ruff format --check .

typecheck:                       ## Type check with pyright
	uv run pyright

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

docker-up:                       ## Start services (detached)
	docker compose up -d

docker-down:                     ## Stop services
	docker compose down

docker-logs:                     ## Tail service logs
	docker compose logs -f

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
	docker build -f Dockerfile.gui -t sophia-gui:latest .

docker-gui-up:                   ## Start GUI service (detached)
	docker compose -f docker-compose.gui.yml up -d

docker-gui-down:                 ## Stop GUI service
	docker compose -f docker-compose.gui.yml down

docker-gui-logs:                 ## Tail GUI service logs
	docker compose -f docker-compose.gui.yml logs -f
