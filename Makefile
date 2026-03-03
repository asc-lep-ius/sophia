.PHONY: dev test lint typecheck run clean clean-all docker-build docker-up docker-down docker-logs

dev:                             ## Install all dev dependencies
	uv sync --extra dev

test:                            ## Run test suite with coverage
	uv run pytest --tb=short -q --cov=src/sophia --cov-fail-under=85

lint:                            ## Lint and format check
	uv run ruff check . && uv run ruff format --check .

typecheck:                       ## Type check with pyright
	uv run pyright

run:                             ## Run sophia TUI
	uv run sophia

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
