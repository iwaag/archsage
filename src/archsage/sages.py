"""The sages: what one is, how they are found, added and refreshed.

A sage is a directory `sages/<name>/`:

    sage.toml      name, one line about the domain, the study repository (or "")
    guide.md       the domain guide, read per run
    mainstudy/     the clone of the study's published knowledge (ignored)
    tostudy/       the sage's study queue: notes about what it could not answer (ignored)

That is the whole of a sage. The execution profile is shared (`[roles.sage]`),
the selector is `sage:<name>`, and the knowledge revision is `mainstudy`'s
git revision — `empty` for a sage whose study has not published anything
yet, which is a valid state for a newly planned study: such a sage explains
the gap rather than inventing findings.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .instance import SAGES_ROOT, SELECTOR_KIND

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
EMPTY_REVISION = "empty"
UNAVAILABLE_REVISION = "unavailable"

__all__ = [
    "EMPTY_REVISION",
    "NAME_RE",
    "Sage",
    "SageError",
    "add_sage",
    "knowledge_revision",
    "load_sages",
    "sage_named",
    "selector_of",
    "selectors",
    "sync_sage",
]


class SageError(RuntimeError):
    """A sage cannot be read, made or refreshed as asked."""


@dataclass(frozen=True)
class Sage:
    name: str
    about: str
    study: str
    root: Path

    @property
    def selector(self) -> str:
        return f"{SELECTOR_KIND}:{self.name}"

    @property
    def tree(self) -> Path:
        return self.root / "mainstudy"

    @property
    def queue(self) -> Path:
        return self.root / "tostudy"

    @property
    def guide_path(self) -> Path:
        return self.root / "guide.md"

    def guide(self) -> str:
        try:
            return self.guide_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def revision(self) -> str:
        return knowledge_revision(self.tree)

    def has_knowledge(self) -> bool:
        return self.tree.is_dir() and any(p.name != ".git" for p in self.tree.iterdir())


def selector_of(name: str) -> str:
    return f"{SELECTOR_KIND}:{name}"


def _read(path: Path) -> Sage | None:
    config = path / "sage.toml"
    if not config.is_file():
        return None
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SageError(f"cannot read {config}: {error}") from error
    name = str(data.get("name") or path.name).strip()
    if not NAME_RE.match(name):
        raise SageError(f"{config}: {name!r} is not a sage name ({NAME_RE.pattern})")
    return Sage(name, str(data.get("about") or "").strip(), str(data.get("study") or "").strip(), path)


def load_sages(root: Path | None = None) -> list[Sage]:
    """Every sage under `sages/`, by name."""
    root = SAGES_ROOT if root is None else root
    if not root.is_dir():
        return []
    found = [sage for sage in (_read(p) for p in sorted(root.iterdir()) if p.is_dir()) if sage is not None]
    return sorted(found, key=lambda s: s.name)


def sage_named(name: str, root: Path | None = None) -> Sage | None:
    return next((s for s in load_sages(root) if s.name == name), None)


def selectors(root: Path | None = None) -> list[str]:
    return [sage.selector for sage in load_sages(root)]


def knowledge_revision(tree: Path) -> str:
    """The tree's git revision; `empty` without a tree or with an empty one;
    `unavailable` when there is a tree git cannot describe."""
    if not tree.is_dir() or not any(p.name != ".git" for p in tree.iterdir()):
        return EMPTY_REVISION
    try:
        done = subprocess.run(["git", "-C", str(tree), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return UNAVAILABLE_REVISION
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else UNAVAILABLE_REVISION


def add_sage(name: str, about: str, guide: str, *, study: str = "", root: Path | None = None) -> Sage:
    """Define a new sage: its config and its domain guide, nothing more.

    An empty study is allowed and means the knowledge tree is empty until a
    study publishes something — the sage will say so when asked. Refuses a
    name in use, because a sage is its tree and a second definition would
    not be a second tree.
    """
    root = SAGES_ROOT if root is None else root
    if not NAME_RE.match(name):
        raise SageError(f"{name!r} is not a sage name ({NAME_RE.pattern})")
    if not about.strip():
        raise SageError("a sage needs one line about its domain")
    if not guide.strip():
        raise SageError("a sage needs a domain guide")
    directory = root / name
    if directory.exists():
        raise SageError(f"sage {name!r} already exists at {directory}")
    directory.mkdir(parents=True)
    (directory / "sage.toml").write_text(
        'name = "{}"\nabout = "{}"\nstudy = "{}"\n'.format(name, about.strip().replace('"', "'"), study.strip()),
        encoding="utf-8",
    )
    (directory / "guide.md").write_text(guide.strip() + "\n", encoding="utf-8")
    (directory / "tostudy").mkdir(exist_ok=True)
    return _read(directory)  # type: ignore[return-value]


def sync_sage(sage: Sage, *, timeout: float = 300) -> str:
    """Clone or fast-forward the sage's tree from its study. Returns what
    happened; a sage without a study is left as it is."""
    if not sage.study:
        return "no study repository: the tree stays as it is"
    if (sage.tree / ".git").is_dir():
        done = subprocess.run(["git", "-C", str(sage.tree), "pull", "--ff-only"],
                              capture_output=True, text=True, timeout=timeout, check=False)
    elif sage.tree.exists():
        raise SageError(f"{sage.tree} exists but is not a git checkout")
    else:
        done = subprocess.run(["git", "clone", sage.study, str(sage.tree)],
                              capture_output=True, text=True, timeout=timeout, check=False)
    if done.returncode != 0:
        raise SageError(f"sync of {sage.name} failed: {(done.stderr or done.stdout).strip()[:500]}")
    return f"{sage.name} at {sage.revision()}"
