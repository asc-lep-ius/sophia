"""Production deployment policy tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).parents[2]
POLICY_SCRIPT = REPO_ROOT / "scripts" / "deployment_policy.py"
COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"
CADDY_ADAPT_LINE = (
    "RUN /usr/bin/caddy adapt --config /etc/caddy/Caddyfile "
    "--adapter caddyfile --pretty > /tmp/Caddyfile.json\n"
)
DEPLOY_SMOKE_LINE = (
    '    - python3 scripts/deploy_smoke.py --base-url "$SOPHIA_PRODUCTION_URL" '
    '--sse-path "${SOPHIA_SMOKE_SSE_PATH:-/api/events}"\n'
)
VALID_PROXY_DOCKERFILE = (
    """ARG CADDY_VERSION=2.11.3
ARG XCADDY_VERSION=v0.4.5
ARG RATELIMIT_VERSION=16aecbbcb8ca07dc1c671e263379606ff9493c55

FROM caddy:${CADDY_VERSION}-builder AS builder
RUN go install github.com/caddyserver/xcaddy/cmd/xcaddy@${XCADDY_VERSION} && \\
        /go/bin/xcaddy build v${CADDY_VERSION} \\
            --output /usr/bin/caddy \\
            --with github.com/mholt/caddy-ratelimit@${RATELIMIT_VERSION}

FROM caddy:${CADDY_VERSION}
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
RUN /usr/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
"""
    + CADDY_ADAPT_LINE
)
VALID_GITLAB_CI = (
    "docker-proxy-build:\n"
    "  script:\n"
    "    - docker buildx build --file proxy/Dockerfile "
    "--tag ${LOCAL_REGISTRY}/proxy:${CI_COMMIT_SHA} --push proxy\n"
    "deploy:production:\n"
    "  resource_group: production\n"
    "  environment:\n"
    "    name: production\n"
    "    url: $SOPHIA_PRODUCTION_URL\n"
    "    deployment_tier: production\n"
    "  script:\n"
    '    - test -n "$SOPHIA_PRODUCTION_URL"\n'
    "    - ssh deploy.example deploy\n"
    f"{DEPLOY_SMOKE_LINE}"
    "  rules:\n"
    "    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'\n"
    "      when: manual\n"
    "    - when: never\n"
)
VALID_DEPLOYMENT_DOC = """
# Deployment

## Litestream Backups And Restore Drills

Use litestream/litestream:0.5.11. Every drill validates study_sessions,
student_flashcards, self_explanations, review_schedule, deadline_cache,
card_review_attempts, score_at_last_review, last_reviewed_at, review_count,
reviewed_at, next_review_at, and due_at.

The smoke check uses litestream snapshots and /api/metrics. Alert when the
litestream service is unhealthy because that is stopped replication. Run the
snapshot check weekly, a full restore monthly, and a restore after every schema
migration.

Validate with sqlite3, PRAGMA integrity_check, and
curl -f https://sophia.example.com/api/ready.
"""


def test_deployment_policy_passes_repository() -> None:
    result = _run_policy(REPO_ROOT)

    assert result.returncode == 0, result.stderr


def test_deployment_policy_rejects_non_proxy_published_ports(tmp_path: Path) -> None:
    compose = _valid_compose()
    compose["services"]["api"]["ports"] = ["8000:8000"]

    result = _run_policy_for_compose(tmp_path, compose)

    assert result.returncode == 1
    assert "api" in result.stderr
    assert "only proxy may publish ports" in result.stderr


def test_deployment_policy_rejects_unpinned_app_image_fallbacks(tmp_path: Path) -> None:
    compose = _valid_compose()
    compose["services"]["frontend"]["image"] = (
        "registry.example/sophia/frontend:${IMAGE_TAG:-phase0-local}"
    )

    result = _run_policy_for_compose(tmp_path, compose)

    assert result.returncode == 1
    assert "frontend" in result.stderr
    assert "phase0-local" in result.stderr


def test_deployment_policy_rejects_reusable_proxy_image_tag(tmp_path: Path) -> None:
    compose = _valid_compose()
    compose["services"]["proxy"]["image"] = (
        "registry.example/sophia/proxy:caddy-2.11.3-ratelimit-16aecbbcb8ca07dc1c671e263379606ff9493c55"
    )

    result = _run_policy_for_compose(tmp_path, compose)

    assert result.returncode == 1
    assert "proxy" in result.stderr
    assert "full commit SHA tag or sha256 digest" in result.stderr


def test_deployment_policy_rejects_proxy_dockerfile_without_caddy_validation(
    tmp_path: Path,
) -> None:
    proxy_dockerfile = VALID_PROXY_DOCKERFILE.replace(
        "RUN /usr/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile\n",
        "",
    )

    result = _run_policy_for_files(tmp_path, proxy_dockerfile=proxy_dockerfile)

    assert result.returncode == 1
    assert "proxy/Dockerfile" in result.stderr
    assert "validate and adapt /etc/caddy/Caddyfile" in result.stderr


def test_deployment_policy_rejects_proxy_dockerfile_without_caddy_adapt(
    tmp_path: Path,
) -> None:
    proxy_dockerfile = VALID_PROXY_DOCKERFILE.replace(CADDY_ADAPT_LINE, "")

    result = _run_policy_for_files(tmp_path, proxy_dockerfile=proxy_dockerfile)

    assert result.returncode == 1
    assert "proxy/Dockerfile" in result.stderr
    assert "validate and adapt /etc/caddy/Caddyfile" in result.stderr


def test_deployment_policy_rejects_static_proxy_ci_tag(tmp_path: Path) -> None:
    gitlab_ci = VALID_GITLAB_CI.replace(
        "${LOCAL_REGISTRY}/proxy:${CI_COMMIT_SHA}",
        "${LOCAL_REGISTRY}/proxy:caddy-2.11.3-ratelimit-16aecbbcb8ca07dc1c671e263379606ff9493c55",
    )

    result = _run_policy_for_files(tmp_path, gitlab_ci=gitlab_ci)

    assert result.returncode == 1
    assert ".gitlab-ci.yml" in result.stderr
    assert "proxy image with CI_COMMIT_SHA" in result.stderr


def test_deployment_policy_rejects_production_deploy_without_resource_group(
    tmp_path: Path,
) -> None:
    gitlab_ci = VALID_GITLAB_CI.replace("  resource_group: production\n", "")

    result = _run_policy_for_files(tmp_path, gitlab_ci=gitlab_ci)

    assert result.returncode == 1
    assert "deploy:production" in result.stderr
    assert "resource_group: production" in result.stderr


def test_deployment_policy_rejects_production_deploy_without_environment_tier(
    tmp_path: Path,
) -> None:
    gitlab_ci = VALID_GITLAB_CI.replace("    deployment_tier: production\n", "")

    result = _run_policy_for_files(tmp_path, gitlab_ci=gitlab_ci)

    assert result.returncode == 1
    assert "deploy:production" in result.stderr
    assert "deployment_tier: production" in result.stderr


def test_deployment_policy_rejects_production_deploy_without_post_deploy_smoke(
    tmp_path: Path,
) -> None:
    gitlab_ci = VALID_GITLAB_CI.replace(DEPLOY_SMOKE_LINE, "")

    result = _run_policy_for_files(tmp_path, gitlab_ci=gitlab_ci)

    assert result.returncode == 1
    assert "deploy:production" in result.stderr
    assert "scripts/deploy_smoke.py" in result.stderr


def test_deployment_policy_rejects_automatic_or_non_default_branch_deploy(
    tmp_path: Path,
) -> None:
    gitlab_ci = VALID_GITLAB_CI.replace(
        "    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'\n      when: manual\n",
        "    - if: '$CI_COMMIT_BRANCH'\n      when: on_success\n",
    )

    result = _run_policy_for_files(tmp_path, gitlab_ci=gitlab_ci)

    assert result.returncode == 1
    assert "deploy job must be manual and limited to the default branch" in result.stderr


def test_deployment_policy_rejects_source_bind_mounts(tmp_path: Path) -> None:
    compose = _valid_compose()
    compose["services"]["api"]["volumes"] = ["./src:/app/src:ro", "sophia-data:/data"]

    result = _run_policy_for_compose(tmp_path, compose)

    assert result.returncode == 1
    assert "api" in result.stderr
    assert "named volumes only" in result.stderr


def test_deployment_policy_requires_healthchecks(tmp_path: Path) -> None:
    compose = _valid_compose()
    del compose["services"]["litestream"]["healthcheck"]

    result = _run_policy_for_compose(tmp_path, compose)

    assert result.returncode == 1
    assert "litestream" in result.stderr
    assert "healthcheck is required" in result.stderr


def test_deployment_policy_requires_healthy_dependencies(tmp_path: Path) -> None:
    compose = _valid_compose()
    compose["services"]["proxy"]["depends_on"]["api"] = {"condition": "service_started"}

    result = _run_policy_for_compose(tmp_path, compose)

    assert result.returncode == 1
    assert "proxy" in result.stderr
    assert "api" in result.stderr
    assert "service_healthy" in result.stderr


def test_deployment_policy_checks_runtime_baselines(tmp_path: Path) -> None:
    compose = _valid_compose()
    compose["services"]["redis"]["image"] = "redis:7.4-alpine"
    compose["services"]["litestream"]["image"] = "litestream/litestream:0.3.13"

    result = _run_policy_for_compose(tmp_path, compose)

    assert result.returncode == 1
    assert "redis:8.6.3" in result.stderr
    assert "litestream/litestream:0.5.11" in result.stderr


def test_deployment_policy_requires_litestream_replica_environment(tmp_path: Path) -> None:
    compose = _valid_compose()
    del compose["services"]["litestream"]["environment"]["LITESTREAM_REPLICA_URL"]

    result = _run_policy_for_compose(tmp_path, compose)

    assert result.returncode == 1
    assert "litestream" in result.stderr
    assert "LITESTREAM_REPLICA_URL" in result.stderr


def test_deployment_policy_requires_litestream_replica_healthcheck(tmp_path: Path) -> None:
    compose = _valid_compose()
    compose["services"]["litestream"]["healthcheck"] = {"test": ["CMD", "litestream", "version"]}

    result = _run_policy_for_compose(tmp_path, compose)

    assert result.returncode == 1
    assert "litestream" in result.stderr
    assert "replica snapshots" in result.stderr


def test_deployment_policy_requires_restore_drill_learning_proofs(tmp_path: Path) -> None:
    deployment_doc = VALID_DEPLOYMENT_DOC.replace("card_review_attempts", "review_attempts")

    result = _run_policy_for_files(tmp_path, deployment_doc=deployment_doc)

    assert result.returncode == 1
    assert "DEPLOYMENT.md" in result.stderr
    assert "card_review_attempts" in result.stderr


def _run_policy_for_compose(
    tmp_path: Path,
    compose: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    return _run_policy_for_files(tmp_path, compose=compose)


def _run_policy_for_files(
    tmp_path: Path,
    *,
    compose: dict[str, Any] | None = None,
    proxy_dockerfile: str = VALID_PROXY_DOCKERFILE,
    gitlab_ci: str = VALID_GITLAB_CI,
    deployment_doc: str = VALID_DEPLOYMENT_DOC,
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "proxy").mkdir()
    (tmp_path / "proxy" / "Dockerfile").write_text(proxy_dockerfile, encoding="utf-8")
    (tmp_path / ".gitlab-ci.yml").write_text(gitlab_ci, encoding="utf-8")
    (tmp_path / "DEPLOYMENT.md").write_text(deployment_doc, encoding="utf-8")
    (tmp_path / "docker-compose.prod.yml").write_text(
        yaml.safe_dump(compose or _valid_compose(), sort_keys=False),
        encoding="utf-8",
    )
    return _run_policy(tmp_path)


def _run_policy(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(POLICY_SCRIPT), "--root", str(root), "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _valid_compose() -> dict[str, Any]:
    services: dict[str, Any] = {
        "proxy": _service(
            f"registry.example/sophia/proxy:{COMMIT_SHA}",
            ports=["80:80/tcp", "443:443/tcp"],
            volumes=["caddy-data:/data", "caddy-config:/config"],
            depends_on={
                "frontend": {"condition": "service_healthy"},
                "api": {"condition": "service_healthy"},
                "sophia-gui": {"condition": "service_healthy"},
            },
        ),
        "frontend": _service(
            f"registry.example/sophia/frontend:{COMMIT_SHA}",
            expose=["3000"],
        ),
        "api": _service(
            f"registry.example/sophia/api:{COMMIT_SHA}",
            expose=["8000"],
            volumes=["sophia-data:/data", "sophia-config:/config"],
            depends_on={"redis": {"condition": "service_healthy"}},
        ),
        "sophia-gui": _service(
            f"registry.example/sophia/nicegui:{COMMIT_SHA}",
            expose=["8080"],
            volumes=[
                "sophia-data:/data",
                "sophia-config:/config",
                "model-cache:/home/sophia/.cache/huggingface",
            ],
        ),
        "redis": _service(
            "redis:8.6.3-alpine",
            expose=["6379"],
            volumes=["redis-data:/data"],
        ),
        "litestream": _service(
            "litestream/litestream:0.5.11",
            volumes=["sophia-data:/data:ro", "litestream-state:/var/lib/litestream"],
            depends_on={"api": {"condition": "service_healthy"}},
            command=[
                'test -n "$$LITESTREAM_REPLICA_URL" && '
                'test -n "$$LITESTREAM_ACCESS_KEY_ID" && '
                'test -n "$$LITESTREAM_SECRET_ACCESS_KEY" && '
                'exec litestream replicate /data/sophia.db "$$LITESTREAM_REPLICA_URL"'
            ],
            environment={
                "LITESTREAM_REPLICA_URL": "${LITESTREAM_REPLICA_URL:-}",
                "LITESTREAM_ACCESS_KEY_ID": "${LITESTREAM_ACCESS_KEY_ID:-}",
                "LITESTREAM_SECRET_ACCESS_KEY": "${LITESTREAM_SECRET_ACCESS_KEY:-}",
                "LITESTREAM_REGION": "${LITESTREAM_REGION:-auto}",
                "LITESTREAM_ENDPOINT": "${LITESTREAM_ENDPOINT:-}",
            },
            healthcheck={
                "test": [
                    "CMD-SHELL",
                    'test -n "$$LITESTREAM_REPLICA_URL" && '
                    'litestream snapshots "$$LITESTREAM_REPLICA_URL" >/dev/null',
                ]
            },
        ),
    }
    return {
        "services": services,
        "volumes": {
            "sophia-data": None,
            "sophia-config": None,
            "model-cache": None,
            "redis-data": None,
            "caddy-data": None,
            "caddy-config": None,
            "litestream-state": None,
        },
    }


def _service(
    image: str,
    *,
    ports: list[str] | None = None,
    expose: list[str] | None = None,
    volumes: list[str] | None = None,
    depends_on: dict[str, dict[str, str]] | None = None,
    command: list[str] | None = None,
    environment: dict[str, str] | None = None,
    healthcheck: dict[str, Any] | None = None,
) -> dict[str, Any]:
    service: dict[str, Any] = {
        "image": image,
        "restart": "unless-stopped",
        "healthcheck": healthcheck or {"test": ["CMD", "true"]},
    }
    if ports is not None:
        service["ports"] = ports
    if expose is not None:
        service["expose"] = expose
    if volumes is not None:
        service["volumes"] = volumes
    if depends_on is not None:
        service["depends_on"] = depends_on
    if command is not None:
        service["command"] = command
    if environment is not None:
        service["environment"] = environment
    return service
