"""Engine version pinning: a target runs on the engine release it names, not on whatever is installed.

A target pins its engine in ``contracts/target.yaml`` (``engine: v0.1.0``, or a full commit
SHA). Before any command that works on a target, ``enforce_pin`` compares the pin with the
running engine:

- they match → the command runs here;
- they differ → the pinned engine is fetched from the engine repository, installed once into a
  cache, and the same command is handed to it with ``exec``. Its ``bin/`` goes first on
  ``PATH``, so tools the agents call mid-run (``archivist record-gap``) are the pinned ones too.

A run can override the pin for one invocation (``--engine``; ``current`` means "this engine,
whatever the pin says"), which is how an upgrade is tried before the pin is changed by PR.

Deterministic on purpose: which code runs a target must never be an agent's judgement.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import yaml

from archivist import __version__
from archivist.errors import ArchivistError

PIN_PATTERN = re.compile(r"^(v\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?|[0-9a-f]{40})$")
CURRENT = "current"
ENGINE_REPO_ENV = "ARCHIVIST_ENGINE_REPO"
ENGINE_CACHE_ENV = "ARCHIVIST_ENGINE_CACHE"
PINNED_ENV = "ARCHIVIST_ENGINE_PINNED"  # set on the handed-over process: guards against loops
DEFAULT_ENGINE_REPO = "https://github.com/dfirmin/archivist"


class EngineVersionError(ArchivistError):
    """The pinned engine cannot be resolved, installed or trusted."""


def version_from_describe(described: str) -> str | None:
    """The release identity for ``git describe --tags --long --dirty`` output.

    ``v0.4.0-0-gabc1234`` (on the tag, clean) is the release ``v0.4.0``. Anything else, commits
    after a tag or uncommitted changes, is a development version that can never equal a pin:
    ``v0.4.0-3-gabc1234`` → ``v0.4.1.dev3+gabc1234``.
    """
    match = re.fullmatch(r"(v\d+\.\d+\.\d+(?:-rc\.\d+)?)-(\d+)-g([0-9a-f]+)(-dirty)?", described.strip())
    if not match:
        return None
    tag, distance, sha, dirty = match.groups()
    if distance == "0" and not dirty:
        return tag
    major, minor, patch = re.match(r"v(\d+)\.(\d+)\.(\d+)", tag).groups()
    local = f"g{sha}" + (".dirty" if dirty else "")
    return f"v{major}.{minor}.{int(patch) + 1}.dev{distance}+{local}"


def running_version() -> str:
    """This engine's identity: ``v`` + its version, read live from git when it runs from a checkout.

    Live, because the version an editable install recorded goes stale as soon as the checkout
    moves; git always knows whether this exact code is a tagged release. Without a checkout (a
    wheel or a Docker image) the version recorded at build time is the answer.
    """
    root = Path(__file__).resolve().parents[2]
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(root), "describe", "--tags", "--long", "--dirty", "--match", "v[0-9]*"],
            capture_output=True, text=True,
        )
        version = version_from_describe(result.stdout) if result.returncode == 0 else None
        if version:
            return version
    return f"v{__version__}"


def is_release(version: str) -> bool:
    """A tag a target can pin: vX.Y.Z (optionally -rc.N), never a .dev build."""
    return bool(re.fullmatch(r"v\d+\.\d+\.\d+(?:-rc\.\d+)?", version))


def scaffold_pin(requested: str | None) -> str:
    """The pin prepare-target writes: the requested release, else this engine if it is a release."""
    pin = (requested or running_version()).strip()
    if requested and not PIN_PATTERN.fullmatch(pin):
        raise EngineVersionError(f"engine pin {pin!r} must be a release tag (v1.2.3) or a full commit SHA")
    if not PIN_PATTERN.fullmatch(pin) or (pin.startswith("v") and not is_release(pin)):
        raise EngineVersionError(
            f"{pin} is a development build, not a release; pin a release tag (vX.Y.Z) or, to test "
            "unreleased code, a full commit SHA (docs/testing.md)"
        )
    return pin


def running_commit() -> str | None:
    """The commit this engine runs from, when it runs from a git checkout."""
    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        return None
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def read_pin(workspace: Path) -> str | None:
    """The ``engine`` value of ``contracts/target.yaml``, or None when the file or key is absent.

    Read with plain YAML so a pin can be honoured before this engine validates contracts that
    may have been written for a different engine.
    """
    path = workspace / "contracts" / "target.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None  # validation reports it
    value = data.get("engine") if isinstance(data, dict) else None
    return str(value).strip() if value is not None else None


@dataclass(frozen=True, slots=True)
class Decision:
    action: str  # "run" or "delegate"
    pin: str | None
    reason: str


def decide(pin: str | None, *, override: str | None = None, environ: dict[str, str] | None = None) -> Decision:
    """Which engine runs: this one, or the pinned one. Pure: no I/O beyond the git HEAD check."""
    env = environ if environ is not None else os.environ
    handed = env.get(PINNED_ENV, "").strip()
    # A handed-over process runs exactly the version its parent chose (pin or override).
    wanted = (handed or override or pin or "").strip()
    if wanted == CURRENT:
        return Decision("run", pin, f"--engine current: running {running_version()} regardless of the pin")
    if not wanted:
        raise EngineVersionError(
            "contracts/target.yaml has no `engine:` pin; add the engine release this target runs on "
            f"(this engine is {running_version()})"
        )
    if not PIN_PATTERN.fullmatch(wanted):
        raise EngineVersionError(f"engine pin {wanted!r} must be a release tag (v1.2.3) or a full commit SHA")
    if wanted in (running_version(), running_commit()):
        return Decision("run", wanted, f"engine {wanted} is running")
    if handed:
        raise EngineVersionError(
            f"handed over to engine {handed}, but it reports {running_version()}; "
            "the pinned release is inconsistent (its package version does not match its tag)"
        )
    return Decision("delegate", wanted, f"target pins engine {wanted}; this engine is {running_version()}")


def cache_root(environ: dict[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    raw = env.get(ENGINE_CACHE_ENV, "").strip()
    return Path(raw) if raw else Path.home() / ".cache" / "archivist" / "engines"


def install_commands(pin: str, src: Path, venv: Path, repo: str) -> list[list[str]]:
    """The commands that materialize one engine release; split out so tests can check them."""
    if pin.startswith("v"):
        clone = [["git", "clone", "--depth", "1", "--branch", pin, repo, str(src)]]
    else:
        clone = [
            ["git", "clone", "--filter=blob:none", "--no-checkout", repo, str(src)],
            ["git", "-C", str(src), "checkout", pin],
        ]
    return [
        *clone,
        [sys.executable, "-m", "venv", str(venv)],
        # Editable: the engine reads agents/, skills/ and schemas/ from its source tree at
        # runtime, which a regular wheel install would leave behind.
        [str(venv / "bin" / "python"), "-m", "pip", "install", "--quiet", "-e", str(src)],
    ]


def ensure_engine(pin: str, *, environ: dict[str, str] | None = None) -> Path:
    """Install the pinned engine once (under a lock) and return its ``bin/`` directory."""
    env = environ if environ is not None else os.environ
    repo = env.get(ENGINE_REPO_ENV, "").strip() or DEFAULT_ENGINE_REPO
    root = cache_root(env) / pin
    bin_dir = root / "venv" / "bin"
    if (bin_dir / "archivist").is_file() and (root / ".ready").is_file():
        return bin_dir
    root.parent.mkdir(parents=True, exist_ok=True)
    with open(root.parent / f"{pin}.lock", "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if (root / ".ready").is_file():
            return bin_dir
        if root.exists():
            shutil.rmtree(root)  # a half-finished install from an interrupted run
        root.mkdir(parents=True)
        print(f"engine    installing {pin} from {repo} into {root}", file=sys.stderr)
        for command in install_commands(pin, root / "src", root / "venv", repo):
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["failed"]
                shutil.rmtree(root, ignore_errors=True)
                raise EngineVersionError(f"could not install engine {pin}: {' '.join(command[:3])}: {detail[0]}")
        (root / ".ready").write_text(pin + "\n", encoding="utf-8")
    return bin_dir


def enforce_pin(
    workspace: Path,
    argv: Sequence[str],
    *,
    override: str | None = None,
    environ: dict[str, str] | None = None,
) -> Decision:
    """Run here, or hand ``argv`` to the pinned engine (this call then does not return)."""
    env = dict(environ if environ is not None else os.environ)
    decision = decide(read_pin(workspace), override=override, environ=env)
    if decision.action == "run":
        return decision
    assert decision.pin is not None
    bin_dir = ensure_engine(decision.pin, environ=env)
    print(f"engine    {decision.reason}; handing over", file=sys.stderr)
    env[PINNED_ENV] = decision.pin
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    os.execve(str(bin_dir / "archivist"), ["archivist", *strip_engine_flag(argv)], env)
    raise AssertionError("unreachable")  # pragma: no cover


def strip_engine_flag(argv: Sequence[str]) -> list[str]:
    """argv without ``--engine X`` / ``--engine=X``: the pinned engine runs as itself."""
    out: list[str] = []
    skip = False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg == "--engine":
            skip = True
            continue
        if arg.startswith("--engine="):
            continue
        out.append(arg)
    return out
