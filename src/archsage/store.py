"""The definitions store: `sages/` is a checkout of a private repository.

A sage's definition (`sage.toml`, `guide.md`) is written at runtime by
archsage. It does not belong in this public code repository: it carries
internal repository URLs, and it changes whenever a study is attached. So
`sages/` is a clone of its own repository on the host's internal Gitea,
ignored here, and every definition change is committed and pushed there by
`persist`. The trees (`mainstudy/`) and queues (`tostudy/`) stay local; the
store's own `.gitignore` says so.

Configuration is ignored and machine-specific, `.local/sages-store.toml`:

    url = "<the store's clone URL>"
    token_file = "<a file holding a Gitea token that may push to it>"
    username = "<that token's user>"
    author = "archsage <archsage@agstudio.invalid>"

Reconstruction on a fresh checkout: `archsage store restore` clones the
store into `sages/`, then `archsage sage sync` clones every tree.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

from . import sages as _sages
from .instance import ROOT

CONFIG = ROOT / ".local" / "sages-store.toml"
ASKPASS = ROOT / "service" / "askpass.sh"
STORE_IGNORE = "mainstudy/\ntostudy/\n"

__all__ = ["StoreError", "persist", "restore", "status"]


class StoreError(RuntimeError):
    """The definitions store cannot be read or written as asked."""


def _config(path: Path | None = None) -> dict:
    path = CONFIG if path is None else path
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise StoreError(f"cannot read {path}: {error}") from error


def _environment(config: dict) -> dict[str, str]:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    token_file = config.get("token_file")
    if token_file:
        env.update(GIT_ASKPASS=str(ASKPASS), ARCHSAGE_GIT_USERNAME=str(config.get("username") or "archsage"),
                   ARCHSAGE_GIT_TOKEN_FILE=str(token_file))
    return env


def _git(root: Path, *arguments: str, config: dict | None = None, check: bool = True) -> str:
    config = _config() if config is None else config
    author = str(config.get("author") or "archsage <archsage@agstudio.invalid>")
    name, _, email = author.partition(" <")
    done = subprocess.run(["git", "-C", str(root), "-c", f"user.name={name}", "-c", f"user.email={email.rstrip('>')}",
                           *arguments], capture_output=True, text=True, env=_environment(config), timeout=120,
                          check=False)
    if check and done.returncode != 0:
        raise StoreError(f"git {arguments[0]} in {root} failed: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout.strip()


def persist(message: str, *, root: Path | None = None) -> str:
    """Commit every definition change under `sages/` and push it. Returns
    the commit, `unchanged`, or raises when the store is not set up or the
    push fails (the commit then stays local and the next persist pushes it)."""
    root = _sages.SAGES_ROOT if root is None else root
    if not (root / ".git").is_dir():
        raise StoreError(f"{root} is not a checkout of the definitions store (see `archsage store --help`)")
    config = _config()
    if not (root / ".gitignore").exists():
        (root / ".gitignore").write_text(STORE_IGNORE, encoding="utf-8")
    _git(root, "add", "-A", config=config)
    if _git(root, "status", "--porcelain", config=config):
        _git(root, "commit", "-q", "-m", message, config=config)
    ahead = _git(root, "rev-list", "--count", "@{u}..HEAD", config=config, check=False)
    if ahead and ahead != "0":
        _git(root, "push", "-q", "origin", "HEAD", config=config)
        return _git(root, "rev-parse", "--short=12", "HEAD", config=config)
    return "unchanged"


def status(*, root: Path | None = None) -> dict:
    root = _sages.SAGES_ROOT if root is None else root
    if not (root / ".git").is_dir():
        return {"store": "absent", "path": str(root)}
    config = _config()
    return {"store": "present", "path": str(root),
            "remote": _git(root, "remote", "get-url", "origin", config=config, check=False),
            "head": _git(root, "rev-parse", "--short=12", "HEAD", config=config, check=False),
            "unpushed": _git(root, "rev-list", "--count", "@{u}..HEAD", config=config, check=False),
            "dirty": bool(_git(root, "status", "--porcelain", config=config, check=False))}


def restore(*, root: Path | None = None) -> str:
    """Clone the store into an absent or empty `sages/`."""
    root = _sages.SAGES_ROOT if root is None else root
    config = _config()
    url = str(config.get("url") or "")
    if not url:
        raise StoreError(f"no store configured: write `url = …` into {CONFIG}")
    if (root / ".git").is_dir():
        return f"{root} is already a checkout of {_git(root, 'remote', 'get-url', 'origin', config=config)}"
    if root.exists() and any(root.iterdir()):
        raise StoreError(f"{root} exists and is not a checkout; move it aside first")
    done = subprocess.run(["git", "clone", "-q", url, str(root)], capture_output=True, text=True,
                          env=_environment(config), timeout=300, check=False)
    if done.returncode != 0:
        raise StoreError(f"clone of {url} failed: {(done.stderr or done.stdout).strip()[:300]}")
    return f"restored {root} from {url}; `archsage sage sync` clones the trees"
