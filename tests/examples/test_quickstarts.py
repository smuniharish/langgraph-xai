"""The README and documentation quickstarts run as published and print the documented output."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[2]
CODE = re.compile(r"```python\n(.*?)```", re.DOTALL)

pytestmark = pytest.mark.examples


def readme_program(text: str) -> str:
    return next(block for block in CODE.findall(text) if "asyncio.run(main())" in block)


def guide_program(text: str) -> str:
    """The guide's numbered steps, which together form one program."""
    steps = text[text.index("## 1. ") : text.index("## Synchronous graphs")]
    return "\n\n".join(CODE.findall(steps))


@pytest.mark.parametrize(
    ("document", "program"),
    [
        ("README.md", readme_program),
        ("docs/getting-started/quickstart.md", guide_program),
    ],
    ids=["readme", "docs-quickstart"],
)
def test_quickstart_prints_the_documented_output(
    document: str, program: Callable[[str], str], tmp_path: Path
) -> None:
    text = (ROOT / document).read_text(encoding="utf-8")
    expected = re.search(r"Output:\n\n```text\n(.*?)```", text, re.DOTALL)
    assert expected is not None
    script = tmp_path / "quickstart.py"
    script.write_text(program(text), encoding="utf-8")

    completed = subprocess.run(  # noqa: S603 - the interpreter runs the documented code
        [
            sys.executable,
            "-W",
            "error",
            # langsmith, a LangChain dependency, still calls this Python 3.14 deprecation.
            "-W",
            "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning",
            str(script),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == expected.group(1)
