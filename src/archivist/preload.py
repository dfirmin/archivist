"""Target contracts loaded into each agent's prompt for the run (ADR 0009).

Every agent used to open its run by reading `contracts/target.yaml` and then the contracts and
reference data it needs: the same files, two or three model turns, for every spawn. Python
already knows which contracts an agent uses (`requires` and `optional` in `agents/profile.yaml`)
and has them loaded and validated, so it puts them in the agent's prompt at install time,
verbatim, with the instruction that they are already read.

This prepares input; it decides nothing. The agent applies the contracts as before, and what it
reads beyond them (sources, concepts, other files) it still reads itself. Prompt caching makes
the repeated text cheap, and the section is identical for every spawn of an agent in a run.

Large reference data stays on disk: a file over the per-file cap, or past the agent's total,
is listed as not loaded, and the agent reads it as **target-contracts** says.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable

from archivist.agents import Agent
from archivist.contracts import TargetContracts
from archivist.profile import Profile

REFERENCE = "reference"
STRUCTURES = "structures"
TARGET_INDEX = Path("contracts") / "target.yaml"
FILE_CAP = 48 * 1024
TOTAL_CAP = 160 * 1024

HEADER = """# Target contracts for this run (already read)

These are this target's contract files for this run, verbatim. Treat them as already read: use
them from here and do not open these paths again. Read anything not listed here (other
contracts, reference data marked not loaded, the source documents, concepts) as usual.
Contracts stay read-only.

Having the reference data in view changes nothing about how it is used: look a value up where
a contract or your instructions call for a lookup, and use only that hit. Reference wording
never becomes a title, a name or body text; those come from the sources."""


def _kinds_for(agent: str, profile: Profile) -> tuple[str, ...]:
    """The contract kinds an agent uses; the coordinator's come from the stages it dispatches."""
    spec = profile.agents.get(agent)
    if spec is not None:
        return (*spec.requires, *spec.optional)
    if agent == profile.coordinator:
        # The gap fleet's `before` rule has the conductor read these two to size the fleet.
        return ("gap-kinds", "concept-types")
    return ()


def _files(kinds: Iterable[str], contracts: TargetContracts) -> list[Path]:
    root = contracts.workspace
    files: list[Path] = [root / TARGET_INDEX]
    for kind in dict.fromkeys(kinds):
        if kind == REFERENCE:
            files.extend(ref.path for ref in contracts.references.values())
        elif kind in contracts.paths:
            path = contracts.paths[kind]
            if path.is_dir():
                files.extend(sorted(p for p in path.rglob("*") if p.is_file()))
            else:
                files.append(path)
    unique: list[Path] = []
    for path in files:
        if path.is_file() and path not in unique:
            unique.append(path)
    return unique


def contract_section(agent: str, profile: Profile, contracts: TargetContracts) -> str | None:
    """The preloaded-contracts section for one agent, or None when it uses no contracts."""
    kinds = _kinds_for(agent, profile)
    if not kinds:
        return None
    parts = [HEADER]
    skipped: list[str] = []
    total = 0
    for path in _files(kinds, contracts):
        rel = path.relative_to(contracts.workspace).as_posix()
        size = path.stat().st_size
        if size > FILE_CAP or total + size > TOTAL_CAP:
            skipped.append(rel)
            continue
        total += size
        text = path.read_text(encoding="utf-8").rstrip("\n")
        fence = "````" if "```" in text else "```"
        parts.append(f"## `{rel}`\n\n{fence}\n{text}\n{fence}")
    if skipped:
        listed = "\n".join(f"- `{rel}`" for rel in skipped)
        parts.append(f"## Not loaded (too large): read these as **target-contracts** says\n\n{listed}")
    return "\n\n".join(parts)


def with_contracts(
    agents: dict[str, Agent], profile: Profile, contracts: TargetContracts
) -> dict[str, Agent]:
    """Agents whose prompt ends with the contracts they use for this run."""
    out: dict[str, Agent] = {}
    for name, agent in agents.items():
        section = contract_section(name, profile, contracts)
        out[name] = replace(agent, body=f"{agent.body.rstrip()}\n\n{section}") if section else agent
    return out
