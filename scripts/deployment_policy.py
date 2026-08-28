"""Validate production Compose deployment policy."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

PROD_COMPOSE_FILE = Path("docker-compose.prod.yml")
PROXY_DOCKERFILE = Path("proxy/Dockerfile")
GITLAB_CI_FILE = Path(".gitlab-ci.yml")
DEPLOYMENT_DOC_FILE = Path("DEPLOYMENT.md")
APPLICATION_SERVICES = frozenset({"api", "frontend", "sophia-gui"})
DEPLOYABLE_IMAGE_SERVICES = APPLICATION_SERVICES | frozenset({"proxy"})
REQUIRED_DEPENDENCIES = {
    "proxy": frozenset({"api", "frontend", "sophia-gui"}),
    "api": frozenset({"redis"}),
    "litestream": frozenset({"api"}),
    "postgres-backup": frozenset({"postgres"}),
}
# Postgres is pinned by digest rather than by tag: 18.4 can be re-pushed, and a
# storage engine that changes underneath a running cluster is not a detail.
POSTGRES_DIGEST_SERVICES = frozenset({"postgres", "postgres-backup"})
FULL_COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}", re.IGNORECASE)
SHA256_DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}\b", re.IGNORECASE)
REQUIRED_COMMIT_TAG_PATTERN = re.compile(r"\$\{(?:IMAGE_TAG|CI_COMMIT_SHA):\?[^}]+\}")
PROXY_CADDYFILE_VALIDATION_PATTERN = re.compile(
    r"RUN\s+/usr/bin/caddy\s+validate\s+--config\s+/etc/caddy/Caddyfile\s+--adapter\s+caddyfile"
)
PROXY_CADDYFILE_ADAPT_PATTERN = re.compile(
    r"RUN\s+/usr/bin/caddy\s+adapt\s+--config\s+/etc/caddy/Caddyfile\s+--adapter\s+caddyfile"
)
CI_PROXY_COMMIT_SHA_TAG_PATTERN = re.compile(
    r"--tag\s+\$\{LOCAL_REGISTRY\}/proxy:\$\{CI_COMMIT_SHA\}(?:\s|$)"
)
DEPLOY_SMOKE_PATTERN = re.compile(
    r"python3\s+scripts/deploy_smoke\.py\s+--base-url\s+\"\$SOPHIA_PRODUCTION_URL\""
)
DEFAULT_BRANCH_CONDITION_PATTERN = re.compile(
    r"\$CI_COMMIT_BRANCH\s*==\s*\$CI_DEFAULT_BRANCH|\$CI_COMMIT_BRANCH\s*==\s*['\"]master['\"]"
)
UNSAFE_IMAGE_TOKENS = ("phase0-local", ":latest", "${image_tag:-latest}")
PATH_LIKE_PREFIXES = (".", "/", "~", "$", "..")
REQUIRED_LITESTREAM_ENV_VARS = frozenset(
    {
        "LITESTREAM_REPLICA_URL",
        "LITESTREAM_ACCESS_KEY_ID",
        "LITESTREAM_SECRET_ACCESS_KEY",
    }
)
REQUIRED_BACKUP_DOC_TERMS = {
    "restore-learning-progress": (
        "study_sessions",
        "student_flashcards",
        "self_explanations",
    ),
    "restore-due-schedule": (
        "review_schedule",
        "deadline_cache",
        "next_review_at",
        "due_at",
    ),
    "restore-grade-history": (
        "card_review_attempts",
        "score_at_last_review",
    ),
    "restore-review-event-continuity": (
        "last_reviewed_at",
        "review_count",
        "reviewed_at",
    ),
    "backup-metrics": (
        "/api/metrics",
        "litestream snapshots",
    ),
    "stopped-replication-alert": (
        "stopped replication",
        "litestream service is unhealthy",
    ),
    "restore-cadence": (
        "weekly",
        "monthly",
        "after every schema migration",
    ),
    "restore-validation": (
        "pragma integrity_check",
        "sqlite3",
        "curl -f https://sophia.example.com/api/ready",
    ),
    "postgres-backup-policy": (
        "pg_dump",
        "--format=custom",
        "encrypted off-host",
    ),
    "postgres-restore-drill": (
        "pg_restore",
        "make db.restore",
        "rto",
        "rpo",
    ),
    "postgres-cutover": (
        "stop writes",
        "sqlite_to_postgres",
        "--mode verify",
        "read-only sqlite fallback",
    ),
}


@dataclass(frozen=True, slots=True)
class DeploymentPolicyViolation:
    """A deterministic deployment policy violation."""

    path: Path
    service: str
    check: str
    message: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to scan. Defaults to the current directory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return a non-zero exit status when violations are found.",
    )
    args = parser.parse_args(argv)

    violations = scan_root(args.root)
    if violations:
        _write_violations(violations)
        return 1
    return 0


def scan_root(root: Path) -> list[DeploymentPolicyViolation]:
    """Scan production deployment policy under a repository root."""
    violations: list[DeploymentPolicyViolation] = []
    violations.extend(_scan_compose_file(root))
    violations.extend(_scan_proxy_dockerfile(root))
    violations.extend(_scan_gitlab_ci(root))
    violations.extend(_scan_deployment_docs(root))
    return sorted(
        violations,
        key=lambda violation: (str(violation.path), violation.service, violation.check),
    )


def _scan_compose_file(root: Path) -> list[DeploymentPolicyViolation]:
    """Scan the production Compose file under a repository root."""
    compose_path = root / PROD_COMPOSE_FILE
    if not compose_path.is_file():
        return [
            DeploymentPolicyViolation(
                path=PROD_COMPOSE_FILE,
                service="<compose>",
                check="compose-file",
                message="docker-compose.prod.yml is required",
            )
        ]

    compose = _mapping_or_none(_load_yaml(compose_path))
    if compose is None:
        return [
            DeploymentPolicyViolation(
                path=PROD_COMPOSE_FILE,
                service="<compose>",
                check="compose-file",
                message="docker-compose.prod.yml must contain a mapping",
            )
        ]

    return scan_compose(compose, PROD_COMPOSE_FILE)


def _scan_proxy_dockerfile(root: Path) -> list[DeploymentPolicyViolation]:
    """Ensure the proxy image validates the copied Caddyfile at build time."""
    dockerfile_path = root / PROXY_DOCKERFILE
    if not dockerfile_path.is_file():
        return [
            _violation(
                PROXY_DOCKERFILE,
                "proxy",
                "caddyfile-validation",
                "proxy Dockerfile is required",
            )
        ]

    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    custom_binary_copy = "COPY --from=builder /usr/bin/caddy /usr/bin/caddy"
    caddyfile_copy = "COPY Caddyfile /etc/caddy/Caddyfile"
    validation = PROXY_CADDYFILE_VALIDATION_PATTERN.search(dockerfile)
    adaptation = PROXY_CADDYFILE_ADAPT_PATTERN.search(dockerfile)

    custom_binary_index = dockerfile.find(custom_binary_copy)
    caddyfile_index = dockerfile.find(caddyfile_copy)
    validation_index = -1 if validation is None else validation.start()
    adaptation_index = -1 if adaptation is None else adaptation.start()
    if not (0 <= custom_binary_index < caddyfile_index < validation_index < adaptation_index):
        return [
            _violation(
                PROXY_DOCKERFILE,
                "proxy",
                "caddyfile-validation",
                "proxy Dockerfile must validate and adapt /etc/caddy/Caddyfile "
                "with the custom Caddy binary",
            )
        ]

    return []


def _scan_gitlab_ci(root: Path) -> list[DeploymentPolicyViolation]:
    """Ensure CI deploys serialized, smoke-checked production artifacts."""
    ci_path = root / GITLAB_CI_FILE
    if not ci_path.is_file():
        return [
            _violation(
                GITLAB_CI_FILE,
                "docker-proxy-build",
                "proxy-image-tag",
                ".gitlab-ci.yml is required",
            )
        ]

    ci_config = _mapping_or_none(_load_yaml(ci_path))
    if ci_config is None:
        return [
            _violation(
                GITLAB_CI_FILE,
                "docker-proxy-build",
                "proxy-image-tag",
                ".gitlab-ci.yml must contain a mapping",
            )
        ]

    violations: list[DeploymentPolicyViolation] = []
    violations.extend(_scan_proxy_build_ci(ci_config))
    violations.extend(_scan_production_deploy_ci(ci_config))
    return violations


def _scan_proxy_build_ci(ci_config: Mapping[str, Any]) -> list[DeploymentPolicyViolation]:
    proxy_build_job = _mapping(ci_config.get("docker-proxy-build"))
    script_lines = _script_lines(proxy_build_job.get("script"))
    if any(CI_PROXY_COMMIT_SHA_TAG_PATTERN.search(line) for line in script_lines):
        return []

    return [
        _violation(
            GITLAB_CI_FILE,
            "docker-proxy-build",
            "proxy-image-tag",
            "docker-proxy-build must push the proxy image with CI_COMMIT_SHA",
        )
    ]


def _scan_deployment_docs(root: Path) -> list[DeploymentPolicyViolation]:
    """Ensure restore drills prove the learning data Sophia must preserve."""
    deployment_doc_path = root / DEPLOYMENT_DOC_FILE
    if not deployment_doc_path.is_file():
        return [
            _violation(
                DEPLOYMENT_DOC_FILE,
                "litestream",
                "restore-drill-docs",
                "DEPLOYMENT.md must document Litestream restore drills",
            )
        ]

    doc_text = deployment_doc_path.read_text(encoding="utf-8").lower()
    violations: list[DeploymentPolicyViolation] = []
    for check, terms in REQUIRED_BACKUP_DOC_TERMS.items():
        missing_terms = [term for term in terms if term.lower() not in doc_text]
        if missing_terms:
            violations.append(
                _violation(
                    DEPLOYMENT_DOC_FILE,
                    "litestream",
                    check,
                    "restore drill docs must include: " + ", ".join(missing_terms),
                )
            )
    return violations


def _scan_production_deploy_ci(ci_config: Mapping[str, Any]) -> list[DeploymentPolicyViolation]:
    deploy_job = _mapping(ci_config.get("deploy:production"))
    if not deploy_job:
        return [
            _violation(
                GITLAB_CI_FILE,
                "deploy:production",
                "deploy-job",
                "deploy:production job is required",
            )
        ]

    violations: list[DeploymentPolicyViolation] = []
    if deploy_job.get("resource_group") != "production":
        violations.append(
            _violation(
                GITLAB_CI_FILE,
                "deploy:production",
                "resource_group",
                "production deploys must use resource_group: production",
            )
        )

    environment = _mapping(deploy_job.get("environment"))
    if environment.get("name") != "production":
        violations.append(
            _violation(
                GITLAB_CI_FILE,
                "deploy:production",
                "environment",
                "deploy job must declare environment name: production",
            )
        )
    if environment.get("deployment_tier") != "production":
        violations.append(
            _violation(
                GITLAB_CI_FILE,
                "deploy:production",
                "environment",
                "deploy job must declare deployment_tier: production",
            )
        )
    if environment.get("url") != "$SOPHIA_PRODUCTION_URL":
        violations.append(
            _violation(
                GITLAB_CI_FILE,
                "deploy:production",
                "environment",
                "deploy job must expose SOPHIA_PRODUCTION_URL as the production environment URL",
            )
        )

    script_lines = _script_lines(deploy_job.get("script"))
    if not any(line == 'test -n "$SOPHIA_PRODUCTION_URL"' for line in script_lines):
        violations.append(
            _violation(
                GITLAB_CI_FILE,
                "deploy:production",
                "smoke",
                "deploy job must require SOPHIA_PRODUCTION_URL before deploying",
            )
        )
    if not any(DEPLOY_SMOKE_PATTERN.search(line) for line in script_lines):
        violations.append(
            _violation(
                GITLAB_CI_FILE,
                "deploy:production",
                "smoke",
                "deploy job must run scripts/deploy_smoke.py after production deploy",
            )
        )

    if not _has_manual_default_branch_rule(deploy_job.get("rules")):
        violations.append(
            _violation(
                GITLAB_CI_FILE,
                "deploy:production",
                "rules",
                "deploy job must be manual and limited to the default branch",
            )
        )
    return violations


def scan_compose(
    compose: Mapping[str, Any],
    path: Path = PROD_COMPOSE_FILE,
) -> list[DeploymentPolicyViolation]:
    """Scan a loaded Compose mapping for production deployment policy."""
    services = _mapping(compose.get("services"))
    if not services:
        return [
            DeploymentPolicyViolation(
                path=path,
                service="<compose>",
                check="services",
                message="production Compose must define services",
            )
        ]

    volumes = frozenset(_mapping(compose.get("volumes")).keys())
    violations: list[DeploymentPolicyViolation] = []
    for service_name, service_value in services.items():
        service = _mapping(service_value)
        violations.extend(_scan_service(path, service_name, service, services, volumes))

    return sorted(violations, key=lambda violation: (violation.service, violation.check))


def _scan_service(
    path: Path,
    service_name: str,
    service: Mapping[str, Any],
    services: Mapping[str, Any],
    volumes: frozenset[str],
) -> list[DeploymentPolicyViolation]:
    violations: list[DeploymentPolicyViolation] = []
    violations.extend(_scan_ports(path, service_name, service))
    violations.extend(_scan_image(path, service_name, service))
    violations.extend(_scan_restart(path, service_name, service))
    violations.extend(_scan_healthcheck(path, service_name, service))
    violations.extend(_scan_volumes(path, service_name, service, volumes))
    violations.extend(_scan_dependencies(path, service_name, service, services))
    violations.extend(_scan_litestream_backup(path, service_name, service))
    return violations


def _scan_ports(
    path: Path,
    service_name: str,
    service: Mapping[str, Any],
) -> list[DeploymentPolicyViolation]:
    ports = service.get("ports")
    if ports and service_name != "proxy":
        return [
            _violation(path, service_name, "ports", "only proxy may publish ports in production")
        ]
    if service_name == "proxy" and not ports:
        return [_violation(path, service_name, "ports", "proxy must publish the public ports")]
    return []


def _scan_image(
    path: Path,
    service_name: str,
    service: Mapping[str, Any],
) -> list[DeploymentPolicyViolation]:
    violations: list[DeploymentPolicyViolation] = []
    image = service.get("image")
    if "build" in service:
        violations.append(
            _violation(path, service_name, "image", "production services must not build")
        )
    if not isinstance(image, str) or not image:
        violations.append(
            _violation(path, service_name, "image", "production services need images")
        )
        return violations

    unsafe_token = _unsafe_image_token(image)
    if unsafe_token is not None:
        violations.append(
            _violation(path, service_name, "image", f"image must not contain {unsafe_token}")
        )

    if service_name in DEPLOYABLE_IMAGE_SERVICES and not _is_commit_pinned_app_image(image):
        violations.append(
            _violation(
                path,
                service_name,
                "image",
                "deployable image must use a full commit SHA tag or sha256 digest",
            )
        )
    elif service_name == "redis" and not image.startswith("redis:8.6.3"):
        violations.append(
            _violation(path, service_name, "image", "redis baseline must be redis:8.6.3")
        )
    elif service_name in POSTGRES_DIGEST_SERVICES and not SHA256_DIGEST_PATTERN.search(image):
        violations.append(
            _violation(
                path,
                service_name,
                "image",
                "postgres images must be pinned by sha256 digest",
            )
        )
    elif service_name in POSTGRES_DIGEST_SERVICES and not image.startswith("postgres@"):
        violations.append(
            _violation(path, service_name, "image", "postgres baseline must be the postgres image")
        )
    elif service_name == "litestream" and image != "litestream/litestream:0.5.11":
        violations.append(
            _violation(
                path,
                service_name,
                "image",
                "litestream baseline must be litestream/litestream:0.5.11",
            )
        )
    return violations


def _scan_restart(
    path: Path,
    service_name: str,
    service: Mapping[str, Any],
) -> list[DeploymentPolicyViolation]:
    restart = service.get("restart")
    if not isinstance(restart, str) or restart in {"", "no"}:
        return [_violation(path, service_name, "restart", "restart policy is required")]
    return []


def _scan_healthcheck(
    path: Path,
    service_name: str,
    service: Mapping[str, Any],
) -> list[DeploymentPolicyViolation]:
    if not _mapping(service.get("healthcheck")):
        return [_violation(path, service_name, "healthcheck", "healthcheck is required")]
    return []


def _scan_volumes(
    path: Path,
    service_name: str,
    service: Mapping[str, Any],
    declared_volumes: frozenset[str],
) -> list[DeploymentPolicyViolation]:
    raw_service_volumes = service.get("volumes")
    if raw_service_volumes is None:
        return []
    service_volumes = _list_or_none(raw_service_volumes)
    if service_volumes is None:
        return [_violation(path, service_name, "volumes", "volumes must be a list")]

    violations: list[DeploymentPolicyViolation] = []
    for volume in service_volumes:
        source = _volume_source(volume)
        if source is None or _is_bind_mount_source(source) or source not in declared_volumes:
            violations.append(
                _violation(path, service_name, "volumes", "production uses named volumes only")
            )
    return violations


def _scan_dependencies(
    path: Path,
    service_name: str,
    service: Mapping[str, Any],
    services: Mapping[str, Any],
) -> list[DeploymentPolicyViolation]:
    raw_depends_on = service.get("depends_on")
    required_dependencies = REQUIRED_DEPENDENCIES.get(service_name, frozenset())
    if not required_dependencies and raw_depends_on is None:
        return []
    depends_on = _mapping_or_none(raw_depends_on)
    if depends_on is None:
        if required_dependencies:
            dependency_list = ", ".join(sorted(required_dependencies))
            return [
                _violation(
                    path,
                    service_name,
                    "depends_on",
                    f"depends_on must include healthy dependencies: {dependency_list}",
                )
            ]
        return [_violation(path, service_name, "depends_on", "depends_on must use mapping form")]

    violations: list[DeploymentPolicyViolation] = []
    missing_dependencies = required_dependencies.difference(depends_on.keys())
    if missing_dependencies:
        violations.append(
            _violation(
                path,
                service_name,
                "depends_on",
                f"missing healthy dependencies: {', '.join(sorted(missing_dependencies))}",
            )
        )

    for dependency_name, dependency_value in depends_on.items():
        dependency_service = _mapping(services.get(dependency_name))
        if not _mapping(dependency_service.get("healthcheck")):
            continue
        dependency = _mapping(dependency_value)
        if dependency.get("condition") != "service_healthy":
            violations.append(
                _violation(
                    path,
                    service_name,
                    "depends_on",
                    f"{dependency_name} dependency must use condition: service_healthy",
                )
            )
    return violations


def _scan_litestream_backup(
    path: Path,
    service_name: str,
    service: Mapping[str, Any],
) -> list[DeploymentPolicyViolation]:
    if service_name != "litestream":
        return []

    violations: list[DeploymentPolicyViolation] = []
    command = "\n".join(_script_lines(service.get("command")))
    required_command_parts = (
        "litestream replicate",
        "/data/sophia.db",
        "$$LITESTREAM_REPLICA_URL",
    )
    missing_command_parts = [part for part in required_command_parts if part not in command]
    if missing_command_parts:
        violations.append(
            _violation(
                path,
                service_name,
                "replication-command",
                "litestream must replicate /data/sophia.db to LITESTREAM_REPLICA_URL",
            )
        )

    environment = _environment_mapping(service.get("environment"))
    missing_env_vars = REQUIRED_LITESTREAM_ENV_VARS.difference(environment.keys())
    if missing_env_vars:
        violations.append(
            _violation(
                path,
                service_name,
                "replica-env",
                "missing replica environment: " + ", ".join(sorted(missing_env_vars)),
            )
        )

    healthcheck = _mapping(service.get("healthcheck"))
    healthcheck_command = " ".join(_script_lines(healthcheck.get("test")))
    if "litestream snapshots" not in healthcheck_command:
        violations.append(
            _violation(
                path,
                service_name,
                "replica-healthcheck",
                "litestream healthcheck must validate replica snapshots",
            )
        )

    if not _has_read_only_litestream_data_volume(service.get("volumes")):
        violations.append(
            _violation(
                path,
                service_name,
                "data-volume",
                "litestream must mount sophia-data at /data read-only",
            )
        )

    return violations


def _load_yaml(path: Path) -> object:
    return cast("object", yaml.safe_load(path.read_text(encoding="utf-8")))


def _mapping_or_none(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return cast("Mapping[str, Any]", value)
    return None


def _mapping(value: object) -> Mapping[str, Any]:
    mapping = _mapping_or_none(value)
    if mapping is not None:
        return mapping
    return {}


def _list_or_none(value: object) -> list[Any] | None:
    if isinstance(value, list):
        return cast("list[Any]", value)
    return None


def _script_lines(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    lines = _list_or_none(value)
    if lines is not None:
        return [line for line in lines if isinstance(line, str)]
    return []


def _has_manual_default_branch_rule(value: object) -> bool:
    rules = _list_or_none(value)
    if rules is None:
        return False

    for rule_value in rules:
        rule = _mapping(rule_value)
        condition = rule.get("if")
        if (
            isinstance(condition, str)
            and rule.get("when") == "manual"
            and DEFAULT_BRANCH_CONDITION_PATTERN.search(condition)
        ):
            return True
    return False


def _environment_mapping(value: object) -> Mapping[str, Any]:
    mapping = _mapping_or_none(value)
    if mapping is not None:
        return mapping

    lines = _list_or_none(value)
    if lines is None:
        return {}

    environment: dict[str, str] = {}
    for line in lines:
        if not isinstance(line, str):
            continue
        name, separator, setting = line.partition("=")
        environment[name] = setting if separator else ""
    return environment


def _has_read_only_litestream_data_volume(value: object) -> bool:
    service_volumes = _list_or_none(value)
    if service_volumes is None:
        return False

    for volume in service_volumes:
        if isinstance(volume, str) and volume == "sophia-data:/data:ro":
            return True
        volume_mapping = _mapping_or_none(volume)
        if volume_mapping is None:
            continue
        if (
            volume_mapping.get("source") == "sophia-data"
            and volume_mapping.get("target") == "/data"
            and volume_mapping.get("read_only") is True
        ):
            return True
    return False


def _volume_source(volume: object) -> str | None:
    if isinstance(volume, str):
        source, separator, _target = volume.partition(":")
        if not separator:
            return None
        return source
    volume_mapping = _mapping_or_none(volume)
    if volume_mapping is not None:
        if volume_mapping.get("type") == "bind":
            return None
        source = volume_mapping.get("source")
        if isinstance(source, str):
            return source
    return None


def _is_bind_mount_source(source: str) -> bool:
    return source.startswith(PATH_LIKE_PREFIXES)


def _unsafe_image_token(image: str) -> str | None:
    lowered = image.lower()
    for token in UNSAFE_IMAGE_TOKENS:
        if token in lowered:
            return token
    return None


def _is_commit_pinned_app_image(image: str) -> bool:
    if SHA256_DIGEST_PATTERN.search(image) is not None:
        return True
    if REQUIRED_COMMIT_TAG_PATTERN.search(image) is not None:
        return True

    tag = image.rsplit(":", maxsplit=1)[-1]
    return FULL_COMMIT_SHA_PATTERN.fullmatch(tag) is not None


def _violation(
    path: Path,
    service: str,
    check: str,
    message: str,
) -> DeploymentPolicyViolation:
    return DeploymentPolicyViolation(path=path, service=service, check=check, message=message)


def _write_violations(violations: list[DeploymentPolicyViolation]) -> None:
    sys.stderr.write("Deployment policy violations found. Tighten production Compose policy.\n")
    for violation in violations:
        sys.stderr.write(
            f"{violation.path}:{violation.service}:{violation.check}: {violation.message}\n"
        )


if __name__ == "__main__":
    raise SystemExit(main())
