"""One error family. Every guardrail raises a subclass; the CLI prints it and exits 1."""

from __future__ import annotations


class ArchivistError(RuntimeError):
    """Base for every error the engine reports to an operator."""


class WorkspaceError(ArchivistError):
    """A target checkout or workspace cannot be safely prepared."""


class DefinitionError(ArchivistError):
    """An engine agent, skill or profile is missing, malformed, or unsafe."""


class ContractError(ArchivistError):
    """A target contract is missing, malformed, or inconsistent."""
