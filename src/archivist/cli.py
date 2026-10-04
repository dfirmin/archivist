"""Command line interface: ``archivist <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from archivist.claude_runner import (
    DEFAULT_PROMPT,
    prepare_agent_workspace,
    run_conductor_agent,
    run_smoke_agent,
)
from archivist.config import resolve_auth
from archivist.engine import resolve_run
from archivist.errors import ArchivistError
from archivist.load_target import load_target
from archivist.record_gap import record_gap
from archivist.workspace import prepare_target


def _fail(err: Exception) -> int:
    print(f"FAIL  {err}", file=sys.stderr)
    return 1


def _config_check(_args: argparse.Namespace) -> int:
    try:
        auth = resolve_auth()
    except ArchivistError as err:
        return _fail(err)
    print(auth.describe())
    print(f"model     {auth.model or 'Claude Code default (agents set their own)'}")
    print("PASS  configuration resolved")
    return 0


def _print_run(run) -> None:  # type: ignore[no-untyped-def]
    print(f"target    {run.contracts.slug}")
    print(f"contracts {', '.join(sorted(run.contracts.declared)) or 'none'}")
    print(f"pipeline  {run.roster.pipeline}: {', '.join(run.roster.stages)}")
    for kind, agents in sorted(run.required.items()):
        print(f"requires  {kind} ← {', '.join(agents)}")


def _validate(args: argparse.Namespace) -> int:
    pipelines = args.pipeline or [None]
    try:
        for pipeline in pipelines:
            run = resolve_run(Path(args.workspace), pipeline=pipeline)
            _print_run(run)
    except ArchivistError as err:
        return _fail(err)
    print("PASS  contracts valid")
    return 0


def _load_target(args: argparse.Namespace) -> int:
    try:
        result = load_target(
            target_slug=args.target,
            workspace=Path(args.workspace),
            registry_path=Path(args.registry) if args.registry else None,
        )
    except ArchivistError as err:
        return _fail(err)
    print(f"workspace {result.workspace}")
    _print_run(result.run)
    print("PASS  target loaded")
    return 0


def _prepare_workspace(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    try:
        prepared = prepare_agent_workspace(workspace, pipeline=args.pipeline)
    except ArchivistError as err:
        return _fail(err)
    _print_run(prepared.run)
    print(f"skills    {len(prepared.skills)}  ({workspace / '.claude' / 'skills'})")
    print(f"agents    {', '.join(prepared.agents)}")
    print(f"plan      {prepared.plan}")
    print("PASS  workspace ready; `claude --agent conductor` here runs the pipeline")
    return 0


def _record_gap(args: argparse.Namespace) -> int:
    description = args.description
    if args.description_file:
        description = (
            sys.stdin.read()
            if args.description_file == "-"
            else Path(args.description_file).read_text(encoding="utf-8")
        )
    try:
        result = record_gap(
            Path(args.concept),
            kind=args.kind,
            origin=args.origin,
            description=description,
            absent=args.absent,
        )
    except ArchivistError as err:
        return _fail(err)
    print(f"gap       {result.kind} {result.action}")
    print(f"PASS  okfx_gaps holds {result.gaps} entries")
    return 0


def _run_conductor(args: argparse.Namespace) -> int:
    return run_conductor_agent(
        workspace=Path(args.workspace),
        inbox_file=args.inbox_file,
        inbox_limit=args.inbox_limit,
        group_limit=args.group_limit,
        concept_file=args.concept,
        skip_publish=args.skip_publish,
        pipeline=args.pipeline,
    )


def _prepare_target(args: argparse.Namespace) -> int:
    try:
        result = prepare_target(
            target_slug=args.target,
            workspace=Path(args.workspace),
            registry_path=Path(args.registry) if args.registry else None,
            local=args.local,
            publish=not args.no_publish,
        )
    except ArchivistError as err:
        return _fail(err)
    print(f"target    {result.target.slug}")
    print(f"workspace {result.workspace}")
    print(f"action    {result.action}")
    for path in result.scaffold.written:
        print(f"WRITE     {path}")
    if result.commit_sha:
        print(f"commit    {result.commit_sha}")
    if result.pull_request_url:
        print(f"PR        {result.pull_request_url}")
    print("PASS  target workspace ready")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archivist", description="Contract-driven document engine")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("config-check", help="Verify Claude Code auth configuration (any CLAUDE_AUTH_MODE)").set_defaults(func=_config_check)

    smoke = commands.add_parser("smoke-agent", help="Prove claude -p answers and can spawn a sub-agent (live)")
    smoke.add_argument("-p", "--prompt", default=DEFAULT_PROMPT)
    smoke.set_defaults(func=_smoke_agent)

    validate = commands.add_parser("validate", help="Validate a target's contracts for one or more pipelines")
    validate.add_argument("workspace", help="Target repository root")
    validate.add_argument(
        "--pipeline",
        action="append",
        help="Pipeline to check requirements for (repeatable; default: the target's default)",
    )
    validate.set_defaults(func=_validate)

    prepare = commands.add_parser("prepare-target", help="Resolve and scaffold a registered target repository")
    prepare.add_argument("workspace", help="Checkout or local scaffold path")
    prepare.add_argument("--target", required=True, help="Slug from targets.yaml")
    prepare.add_argument("--registry", help="Override targets.yaml path")
    prepare.add_argument("--local", action="store_true", help="Scaffold a local directory without GitHub")
    prepare.add_argument("--no-publish", action="store_true", help="Clone and scaffold without a commit or PR")
    prepare.set_defaults(func=_prepare_target)

    load = commands.add_parser("load-target", help="Clone a registered target fresh and validate its contracts")
    load.add_argument("workspace", help="Clone destination inside the workspace volume")
    load.add_argument("--target", required=True, help="Slug from targets.yaml")
    load.add_argument("--registry", help="Override targets.yaml path")
    load.set_defaults(func=_load_target)

    ws = commands.add_parser("prepare-workspace", help="Install agents, skills and the run plan into .claude/")
    ws.add_argument("workspace", help="Target repository root")
    ws.add_argument("--pipeline", help="Pipeline whose agents the conductor may spawn")
    ws.set_defaults(func=_prepare_workspace)

    conductor = commands.add_parser("run-conductor", help="Run the conductor over a loaded target (live)")
    conductor.add_argument("workspace", help="Target repository root")
    conductor.add_argument("--inbox-file", help="Bundle-relative inbox document to author")
    conductor.add_argument("--inbox-limit", type=int, default=0, help="Inbox scan: at most N documents")
    conductor.add_argument("--group-limit", type=int, default=0, help="Inbox scan: at most N groups")
    conductor.add_argument("--concept", help="Bundle-relative existing concept: skip authoring")
    conductor.add_argument("--pipeline", help="Pipeline to run (default: the target's, else the engine's)")
    conductor.add_argument("--skip-publish", action="store_true", help="No branch, commit, push, PR or issues")
    conductor.set_defaults(func=_run_conductor)

    gap = commands.add_parser("record-gap", help="Write one kind's okfx_gaps entry on a concept")
    gap.add_argument("concept", help="Path to the concept .md")
    gap.add_argument("--kind", required=True, help="Kind id from the gap-kinds contract")
    gap.add_argument("--origin", help="An origin the kind allows")
    gap.add_argument("--description", help="What failed and the evidence inspected")
    gap.add_argument("--description-file", help="Read the description from a file, or - for stdin")
    gap.add_argument("--absent", action="store_true", help="Remove this kind's entry: the gap is not present")
    gap.set_defaults(func=_record_gap)
    return parser


def _smoke_agent(args: argparse.Namespace) -> int:
    return run_smoke_agent(prompt=args.prompt)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
