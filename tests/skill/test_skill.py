"""The Agent Skill is valid, its links resolve, and its setup check and test template pass."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from skills_ref import read_properties, validate

import langgraph_xai

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "langgraph-xai-skills" / "skills" / "langgraph-xai"
LINK = re.compile(r"\]\(([^)#<>\s]+)(?:#[^)]*)?\)")
# langsmith, a LangChain dependency, still calls this Python 3.14 deprecation.
STRICT_WARNINGS = [
    "-W",
    "error",
    "-W",
    "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning",
]


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - runs this repository's own files
        [sys.executable, *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
        cwd=ROOT,
    )


def test_the_skill_follows_the_agent_skills_specification() -> None:
    properties = read_properties(SKILL)

    assert validate(SKILL) == []
    assert properties.name == SKILL.name
    assert properties.license == "Apache-2.0"
    assert properties.metadata["version"] == langgraph_xai.__version__
    assert len((SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()) < 500


def test_references_are_one_level_deep_and_every_relative_link_resolves() -> None:
    assert all(path.is_file() for path in (SKILL / "references").iterdir())
    for page in SKILL.rglob("*.md"):
        for target in LINK.findall(page.read_text(encoding="utf-8")):
            if "://" not in target:
                assert (page.parent / target).is_file(), f"{page.name} links to {target}"


def test_the_setup_check_passes() -> None:
    completed = run(*STRICT_WARNINGS, str(SKILL / "scripts" / "verify_setup.py"))

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "FAIL" not in completed.stdout
    assert completed.stdout.rstrip().endswith("All checks passed.")


def test_the_disclosure_policy_template_passes(tmp_path: Path) -> None:
    template = SKILL / "assets" / "test_disclosure_policy.py"
    # A private basetemp keeps the nested run away from the user-wide pytest temp directory.
    completed = run(
        "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={tmp_path}", str(template)
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "5 passed" in completed.stdout
