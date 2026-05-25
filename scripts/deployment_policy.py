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
APPLICATION_SERVICES = frozenset({"api", "frontend", "sophia-gui"})
DEPLOYABLE_IMAGE_SERVICES = APPLICATION_SERVICES | frozenset({"proxy"})
REQUIRED_DEPENDENCIES = {
    "proxy": frozenset({"api", "frontend", "sophia-gui"}),
    "api": frozenset({"redis"}),
    "litestream": frozenset({"api"}),
}
FULL_COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}", re.IGNORECASE)
SHA256_DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}\b", re.IGNORECASE)
REQUIRED_COMMIT_TAG_PATTERN = re.compile(r"\$\{(?:IMAGE_TAG|CI_COMMIT_SHA):\?[^}]+\}")
PROXY_CADDYFILE_VALIDATION_PATTERN = re.compile(
    r"RUN\s+/usr/bin/caddy\s+validate\s+--config\s+/etc/caddy/Caddyfile\s+--adapter\s+caddyfile"
)
CI_PROXY_COMMIT_SHA_TAG_PATTERN = re.compile(
    r"--tag\s+\$\{LOCAL_REGISTRY\}/proxy:\$\{CI_COMMIT_SHA\}(?:\s|$)"
)
UNSAFE_IMAGE_TOKENS = ("phase0-local", ":latest", "${image_tag:-latest}")
PATH_LIKE_PREFIXES = (".", "/", "~", "$", "..")


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

    custom_binary_index = dockerfile.find(custom_binary_copy)
    caddyfile_index = dockerfile.find(caddyfile_copy)
    validation_index = -1 if validation is None else validation.start()
    if not (0 <= custom_binary_index < caddyfile_index < validation_index):
        return [
            _violation(
                PROXY_DOCKERFILE,
                "proxy",
                "caddyfile-validation",
                "proxy Dockerfile must validate /etc/caddy/Caddyfile with the custom Caddy binary",
            )
        ]

    return []


def _scan_gitlab_ci(root: Path) -> list[DeploymentPolicyViolation]:
    """Ensure CI pushes the proxy image with the deployed commit SHA tag."""
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
