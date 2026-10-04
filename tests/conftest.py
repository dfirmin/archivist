from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    """A writable copy of the full business-view example target."""
    dest = tmp_path / "warehouse"
    shutil.copytree(EXAMPLES / "warehouse", dest)
    return dest


@pytest.fixture
def minimal(tmp_path: Path) -> Path:
    """A writable copy of the smallest example target (author + verifier only)."""
    dest = tmp_path / "minimal"
    shutil.copytree(EXAMPLES / "minimal", dest)
    return dest


def edit_yaml(path: Path, change) -> None:  # type: ignore[no-untyped-def]
    """Load a YAML file, let ``change`` mutate it, write it back."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
