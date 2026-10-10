"""The run-contract stack reads one secret out of the env file, quotes and all (#128)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "stack" / "env_value.sh"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("SOPHIA_GEMINI_API_KEY=plain-key", "plain-key"),
        ("SOPHIA_GEMINI_API_KEY='single-quoted-key'", "single-quoted-key"),
        ('SOPHIA_GEMINI_API_KEY="double-quoted-key"', "double-quoted-key"),
        ("export SOPHIA_GEMINI_API_KEY='exported-key'  ", "exported-key"),
    ],
)
def test_the_value_comes_out_without_its_quotes(tmp_path: Path, line: str, expected: str) -> None:
    """The first version kept the quotes, and the worker sent them to Gemini as the key."""
    env_file = tmp_path / "env"
    env_file.write_text(
        f"export SOPHIA_KEYRING_PASSWORD='never-printed'\nGITHUB_TOKEN=unrelated\n{line}\n"
    )

    result = subprocess.run(
        ["bash", str(SCRIPT), "SOPHIA_GEMINI_API_KEY", str(env_file)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == expected
    assert "never-printed" not in result.stdout


def test_a_missing_file_or_variable_prints_nothing(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text("GITHUB_TOKEN=unrelated\n")
    for path in (env_file, tmp_path / "absent"):
        result = subprocess.run(
            ["bash", str(SCRIPT), "SOPHIA_GEMINI_API_KEY", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout == ""
