"""The sages: what one is, how they are found, defined, attached and refreshed.

A sage is a directory `sages/<name>/`:

    sage.toml      name, one line about the domain, and its study:
                   `project` (the study's slug), `source` (`main` — the
                   study's internal knowledge repository, current as soon as
                   research is integrated — or `publish` — its public,
                   reviewed copy, which lags behind a human push) and
                   `study` (the repository URL the tree is cloned from; "" =
                   no study yet)
    guide.md       the domain guide, read per run
    mainstudy/     the clone of that repository (ignored; `sync_sage`)
    tostudy/       the sage's study queue: notes about what it could not answer (ignored)

The execution profile is shared (`[roles.sage]`), the selector is
`sage:<name>`, and the knowledge revision is `mainstudy`'s git revision —
`empty` for a sage whose study has nothing yet, which is a valid state for a
newly planned study: such a sage explains the gap rather than inventing
findings.

`sages/` itself is a checkout of the definitions store (`archsage.store`),
so what `add`, `update` and `attach` change is committed and pushed there,
not into this public code repository.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .instance import ROOT, SAGES_ROOT, SELECTOR_KIND

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
EMPTY_REVISION = "empty"
UNAVAILABLE_REVISION = "unavailable"
SOURCES = ("main", "publish")
#: Files a study carries before it has found anything: its plan, its
#: READMEs, its indexes. A tree holding only these has no findings yet.
SCAFFOLD_NAMES = {"README.md", "RESEARCHPLAN.md", "INDEX.md", "LICENSE", ".gitignore", ".gitkeep"}
REPLACED_TREES = ROOT / ".local" / "replaced-trees"

__all__ = [
    "EMPTY_REVISION", "NAME_RE", "SOURCES", "Sage", "SageError", "SyncResult", "add_sage", "attach_study",
    "findings", "knowledge_revision", "load_sages", "sage_named", "selector_of", "selectors", "sync_sage",
    "update_sage", "write_definition",
]


class SageError(RuntimeError):
    """A sage cannot be read, made or refreshed as asked."""


@dataclass(frozen=True)
class Sage:
    name: str
    about: str
    study: str
    root: Path
    project: str = ""
    source: str = ""

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

    def findings(self) -> int:
        return findings(self.tree)

    def queued(self) -> list[Path]:
        return sorted(self.queue.glob("*.md")) if self.queue.is_dir() else []

    def describe_source(self) -> str:
        if not self.study:
            return "no study attached"
        where = f"study `{self.project}`" if self.project else "a study"
        kind = {"main": "its internal knowledge repository (main)", "publish": "its public repository (publish)"}
        return f"{where}, {kind.get(self.source, 'repository')} <{self.study}>"


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
    return Sage(name, str(data.get("about") or "").strip(), str(data.get("study") or "").strip(), path,
                str(data.get("project") or "").strip(), str(data.get("source") or "").strip())


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
    done = _git(tree, "rev-parse", "--short=12", "HEAD")
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else UNAVAILABLE_REVISION


def findings(tree: Path) -> int:
    """How many files in the tree are knowledge rather than scaffolding (a
    plan, a README, an index): 0 means the study has found nothing yet."""
    if not tree.is_dir():
        return 0
    return sum(1 for p in tree.rglob("*")
               if p.is_file() and ".git" not in p.parts and p.name not in SCAFFOLD_NAMES)


def _git(cwd: Path | None, *arguments: str, timeout: float = 300):
    command = ["git", *(["-C", str(cwd)] if cwd is not None else []), *arguments]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return subprocess.CompletedProcess(command, 1, "", str(error))


def write_definition(directory: Path, name: str, about: str, *, study: str = "", project: str = "",
                     source: str = "") -> None:
    lines = [f"name = {json.dumps(name)}", f"about = {json.dumps(about.strip())}",
             f"project = {json.dumps(project.strip())}", f"source = {json.dumps(source.strip())}",
             f"study = {json.dumps(study.strip())}"]
    (directory / "sage.toml").write_text(
        "# One sage: its domain and the study whose knowledge is its tree (archsage.sages).\n"
        + "\n".join(lines) + "\n", encoding="utf-8")


def add_sage(name: str, about: str, guide: str, *, study: str = "", project: str = "", source: str = "",
             root: Path | None = None) -> Sage:
    """Define a new sage: its config and its domain guide, nothing more.

    An empty study is allowed and means the knowledge tree is empty until a
    study is attached — the sage will say so when asked. Refuses a name in
    use, because a sage is its tree and a second definition would not be a
    second tree (`update_sage` and `attach_study` change an existing one).
    """
    root = SAGES_ROOT if root is None else root
    if not NAME_RE.match(name):
        raise SageError(f"{name!r} is not a sage name ({NAME_RE.pattern})")
    if not about.strip():
        raise SageError("a sage needs one line about its domain")
    if not guide.strip():
        raise SageError("a sage needs a domain guide")
    if source and source not in SOURCES:
        raise SageError(f"source must be one of {', '.join(SOURCES)}")
    directory = root / name
    if directory.exists():
        raise SageError(f"sage {name!r} already exists at {directory}; `archsage sage update` or `attach` changes it")
    directory.mkdir(parents=True)
    write_definition(directory, name, about, study=study, project=project, source=source)
    (directory / "guide.md").write_text(guide.strip() + "\n", encoding="utf-8")
    (directory / "tostudy").mkdir(exist_ok=True)
    return _read(directory)  # type: ignore[return-value]


def update_sage(name: str, *, about: str | None = None, guide: str | None = None, root: Path | None = None) -> Sage:
    """Change an existing sage's one-line domain and/or its guide."""
    sage = sage_named(name, root)
    if sage is None:
        raise SageError(f"no sage named {name!r}")
    if about is not None:
        if not about.strip():
            raise SageError("the one line about the domain cannot be empty")
        write_definition(sage.root, sage.name, about, study=sage.study, project=sage.project, source=sage.source)
    if guide is not None:
        if not guide.strip():
            raise SageError("the domain guide cannot be empty")
        sage.guide_path.write_text(guide.strip() + "\n", encoding="utf-8")
    return _read(sage.root)  # type: ignore[return-value]


def attach_study(name: str, *, project: str, source: str = "main", repository: str = "",
                 root: Path | None = None) -> Sage:
    """Point an existing sage at a study's knowledge. For `main` the
    repository defaults to the study's internal one on the host's Gitea;
    for `publish` it must be given (a public repository the developer made)."""
    sage = sage_named(name, root)
    if sage is None:
        raise SageError(f"no sage named {name!r}")
    if source not in SOURCES:
        raise SageError(f"source must be one of {', '.join(SOURCES)}")
    if not repository:
        if source == "publish":
            raise SageError("a publish source needs --repository: the public repository the developer supplied")
        from agag.project import gitea_head

        head = gitea_head(project)
        if not head.get("exists"):
            raise SageError(f"the internal repository of study {project!r} is not there "
                            f"({head.get('error') or head.get('repository') or 'unknown'}): is its setup finished? "
                            f"(`agproject status {project}`)")
        repository = str(head["repository"])
    write_definition(sage.root, sage.name, sage.about, study=repository, project=project, source=source)
    return _read(sage.root)  # type: ignore[return-value]


@dataclass(frozen=True)
class SyncResult:
    sage: str
    revision: str
    before: str
    findings: int
    replaced: str = ""
    note: str = ""

    def line(self) -> str:
        if self.revision == EMPTY_REVISION:
            state = "the tree is empty"
        elif self.findings == 0:
            state = "the study has no findings yet (only its plan, READMEs and indexes)"
        else:
            state = f"{self.findings} knowledge file(s)"
        moved = "unchanged" if self.before == self.revision else f"{self.before} → {self.revision}"
        extra = f"; {self.replaced}" if self.replaced else ""
        return f"{self.sage}: {moved}; {state}{extra}{f'; {self.note}' if self.note else ''}"


def _origin(tree: Path) -> str:
    done = _git(tree, "remote", "get-url", "origin")
    return done.stdout.strip() if done.returncode == 0 else ""


def sync_sage(sage: Sage, *, timeout: float = 300) -> SyncResult:
    """Clone or fast-forward the sage's tree from its study.

    A tree cloned from another repository than the definition names — a
    reattached sage — is moved aside (`.local/replaced-trees/`) and the new
    one cloned. A failed refresh leaves the tree where it was and says so."""
    before = sage.revision()
    if not sage.study:
        return SyncResult(sage.name, before, before, sage.findings(), note="no study attached: the tree stays as it is")
    replaced = ""
    if sage.tree.exists():
        origin = _origin(sage.tree) if (sage.tree / ".git").is_dir() else ""
        if origin != sage.study:
            REPLACED_TREES.mkdir(parents=True, exist_ok=True)
            aside = REPLACED_TREES / f"{sage.name}-{time.strftime('%Y%m%d-%H%M%S')}"
            shutil.move(str(sage.tree), aside)
            replaced = f"replaced the tree from {origin or 'no repository'} (kept at {aside.name})"
    if (sage.tree / ".git").is_dir():
        fetched = _git(sage.tree, "fetch", "--quiet", "origin", timeout=timeout)
        done = fetched if fetched.returncode != 0 else _git(sage.tree, "merge", "--ff-only", "--quiet", "@{u}",
                                                            timeout=timeout)
    else:
        done = _git(None, "clone", "--quiet", sage.study, str(sage.tree), timeout=timeout)
    if done.returncode != 0:
        raise SageError(f"refresh of {sage.name} from {sage.study} failed: {(done.stderr or done.stdout).strip()[:400]}"
                        f"; the tree stays at {sage.revision()}")
    return SyncResult(sage.name, sage.revision(), before, sage.findings(), replaced=replaced)
