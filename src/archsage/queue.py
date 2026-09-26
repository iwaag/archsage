"""The sages' study queues, as archsage reads and settles them.

A sage writes a note into its `tostudy/` when its tree does not answer a
reasonable question in its domain (`sagetree queue add`). archsage reads
the queues when it plans research — which questions go into a study's
research plan or a routine run is its judgement — and settles a note only
when the **refreshed** tree actually answers it: `resolve` checks that the
files it names exist in the tree at its current revision and records that
revision before the note is removed. Sending a research request is not an
answer; the note stays until the knowledge is there.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .instance import ROOT
from .sages import Sage, SageError

LOG = ROOT / ".local" / "queue-resolved.jsonl"

__all__ = ["note_path", "notes", "resolve_note"]


def notes(sage: Sage) -> list[Path]:
    return sage.queued()


def note_path(sage: Sage, note: str) -> Path:
    name = note if note.endswith(".md") else f"{note}.md"
    path = sage.queue / name
    if "/" in note or not path.is_file():
        raise SageError(f"{sage.name} has no queued note {note!r}; `archsage queue list {sage.name}` names them")
    return path


def resolve_note(sage: Sage, note: str, answered_by: list[str], *, log: Path | None = None) -> dict:
    """Remove a queued note because these files in the tree answer it."""
    path = note_path(sage, note)
    if not answered_by:
        raise SageError("name the files in the tree that answer it (--answered-by)")
    tree = sage.tree.resolve()
    missing = []
    for relative in answered_by:
        target = (tree / relative).resolve()
        if tree not in target.parents or not target.is_file():
            missing.append(relative)
    if missing:
        raise SageError(f"not in {sage.name}'s tree at {sage.revision()}: {', '.join(missing)} — refresh it "
                        f"(`archsage sage sync {sage.name}`) or keep the note")
    record = {"sage": sage.name, "note": path.name, "text": path.read_text(encoding="utf-8"),
              "revision": sage.revision(), "answered_by": answered_by,
              "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    log = LOG if log is None else log
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    path.unlink()
    return record
