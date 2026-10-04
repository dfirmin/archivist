"""Engine pinning: a target runs on the engine release it names."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from archivist import __version__
from archivist.contracts import load_contracts
from archivist.engines import (
    PINNED_ENV,
    EngineVersionError,
    decide,
    install_commands,
    read_pin,
    running_version,
    strip_engine_flag,
)
from archivist.errors import ContractError
from archivist.targets import Target
from archivist.workspace import scaffold_workspace
from conftest import REPO, edit_yaml

OTHER = "v9.9.9"
SHA = "a" * 40


def test_matching_pin_runs_here() -> None:
    assert decide(running_version(), environ={}).action == "run"


def test_different_pin_hands_over() -> None:
    decision = decide(OTHER, environ={})
    assert (decision.action, decision.pin) == ("delegate", OTHER)


def test_override_wins_and_current_means_this_engine() -> None:
    assert decide(running_version(), override=OTHER, environ={}).action == "delegate"
    assert decide(OTHER, override="current", environ={}).action == "run"


def test_missing_or_malformed_pin_is_refused() -> None:
    with pytest.raises(EngineVersionError, match="no `engine:` pin"):
        decide(None, environ={})
    with pytest.raises(EngineVersionError, match="release tag"):
        decide("latest", environ={})


def test_handed_over_process_runs_the_version_it_was_given() -> None:
    # The parent chose this engine (pin or override); the child must not re-decide from the pin.
    assert decide(OTHER, environ={PINNED_ENV: running_version()}).action == "run"
    with pytest.raises(EngineVersionError, match="handed over to engine v9.9.9"):
        decide(running_version(), environ={PINNED_ENV: OTHER})


def test_install_commands_for_tag_and_commit(tmp_path: Path) -> None:
    tag = install_commands("v0.1.0", tmp_path / "src", tmp_path / "venv", "https://x/e")
    assert tag[0] == ["git", "clone", "--depth", "1", "--branch", "v0.1.0", "https://x/e", str(tmp_path / "src")]
    sha = install_commands(SHA, tmp_path / "src", tmp_path / "venv", "https://x/e")
    assert sha[1] == ["git", "-C", str(tmp_path / "src"), "checkout", SHA]
    assert sha[-1][-1] == str(tmp_path / "src")  # pip installs the checkout


def test_engine_flag_is_not_passed_to_the_pinned_engine() -> None:
    argv = ["run-conductor", "/w", "--engine", OTHER, "--skip-publish", "--engine=x"]
    assert strip_engine_flag(argv) == ["run-conductor", "/w", "--skip-publish"]


def test_scaffold_pins_the_creating_engine(tmp_path: Path) -> None:
    target = Target("kb", "KB", "d", "https://github.com/o/kb", "docs", "active", False)
    scaffold_workspace(tmp_path / "kb", target)
    assert read_pin(tmp_path / "kb") == running_version()


def test_scaffold_refuses_a_development_pin(tmp_path: Path) -> None:
    from archivist.engines import scaffold_pin

    assert scaffold_pin("v1.2.3") == "v1.2.3"
    assert scaffold_pin(SHA) == SHA
    with pytest.raises(EngineVersionError, match="development build"):
        scaffold_pin("v0.2.0.dev0")


def test_contract_index_requires_a_pin(minimal: Path) -> None:
    edit_yaml(minimal / "contracts/target.yaml", lambda d: d.pop("engine"))
    with pytest.raises(ContractError, match="'engine' is a required property"):
        load_contracts(minimal)


def test_package_version_matches_pyproject() -> None:
    """The release identity (v + __version__) must equal the version that gets tagged."""
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1) == __version__
