"""Verify FRONTEND_CI_TAG names the image this commit's inputs actually build.

`.frontend-job` pulls `frontend-ci:$FRONTEND_CI_TAG`, a tag written into
`.gitlab-ci.yml` by hand rather than published by the job that builds it. Not
because a computed value could not reach `image:` -- a dotenv variable from an
earlier job does reach it -- but because the publisher would have to run in
every pipeline, would need its own `needs:` to be seen from its own stage, and
expands to `invalid reference format` when unset. `.gitlab-ci.yml` carries that
reasoning in full.

What a hand-written tag risks instead is going stale, and this is the answer to
it: recompute the hash from the same two files the rebuild job builds from, and
fail with the value to paste when they differ.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

GITLAB_CI_FILE = Path(".gitlab-ci.yml")
# The order is the contract: the hash is over these files concatenated, and
# reordering them silently invalidates every tag already in the registry.
IMAGE_INPUTS = (Path("ci/Dockerfile.frontend"), Path("frontend/pnpm-lock.yaml"))
TAG_LENGTH = 16
TAG_PATTERN = re.compile(r"^\s*FRONTEND_CI_TAG:\s*\"([^\"]*)\"\s*$", re.MULTILINE)


def content_tag(root: Path) -> str:
    """The tag `ci/Dockerfile.frontend` and the lockfile add up to."""
    digest = hashlib.sha256()
    for relative_path in IMAGE_INPUTS:
        digest.update((root / relative_path).read_bytes())
    return digest.hexdigest()[:TAG_LENGTH]


def declared_tag(gitlab_ci: str) -> str | None:
    """The tag `.gitlab-ci.yml` declares, or None when it declares none."""
    match = TAG_PATTERN.search(gitlab_ci)
    return match.group(1) if match else None


def check_root(root: Path) -> str | None:
    """The failure to report, or None when the declared tag is current."""
    ci_path = root / GITLAB_CI_FILE
    if not ci_path.is_file():
        return f"{GITLAB_CI_FILE} is required"

    missing = [str(p) for p in IMAGE_INPUTS if not (root / p).is_file()]
    if missing:
        return f"the image inputs are missing: {', '.join(missing)}"

    expected = content_tag(root)
    declared = declared_tag(ci_path.read_text(encoding="utf-8"))
    if declared is None:
        return (
            f"{GITLAB_CI_FILE} declares no FRONTEND_CI_TAG. "
            f'Add FRONTEND_CI_TAG: "{expected}" under `variables:`.'
        )
    if declared != expected:
        inputs = " and ".join(str(p) for p in IMAGE_INPUTS)
        return (
            f"FRONTEND_CI_TAG is {declared} but {inputs} hash to {expected}.\n"
            f'Set FRONTEND_CI_TAG: "{expected}" in {GITLAB_CI_FILE}. '
            "rebuild-frontend-ci-image builds that tag on the same change, so "
            "the image will exist by the time the frontend jobs pull it."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to check. Defaults to the current directory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return a non-zero exit status when the tag is stale.",
    )
    args = parser.parse_args(argv)

    failure = check_root(args.root)
    if failure is not None:
        sys.stderr.write(f"{failure}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
