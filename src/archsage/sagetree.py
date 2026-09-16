"""`sagetree`: the bounded reader a sage's run is given instead of file tools.

A sage's grant is `Bash(sagetree:*)` and nothing else — no Read, no Glob,
no Grep — and `sagetree` refuses every path that does not resolve inside
the tree named by `SAGETREE_ROOT`. The study queue (`SAGETREE_QUEUE`) is
the one place it writes. That is the whole of the boundary this experiment
offers, and its limit is stated rather than hidden: under claude_code a
`Bash(<name>:*)` grant admits a compound command (`sagetree ls && cat
/etc/hosts`), so a sage that *wants* out can get out. What the boundary
does is make the honest path the easy one — everything a sage is meant to
read is one command away, and nothing else is — and make an escape
visible in the transcript as a command that is not `sagetree`.

    sagetree ls [path]            entries of a directory (the root by default)
    sagetree cat <path> [...]     a file, with line numbers
    sagetree grep <pattern> [path]  matching lines under a path (the root by default)
    sagetree find <glob>          files matching a glob, e.g. 'papers/*/summary.md'
    sagetree revision             the tree's git revision (or `empty`)
    sagetree queue list           the study queue's notes
    sagetree queue add <slug> <text...>   create a note, or append to one that exists
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT_VARIABLE = "SAGETREE_ROOT"
QUEUE_VARIABLE = "SAGETREE_QUEUE"
MAX_CAT_BYTES = 200_000
MAX_GREP_LINES = 400
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

__all__ = ["QUEUE_VARIABLE", "ROOT_VARIABLE", "TreeError", "inside", "main", "run"]


class TreeError(RuntimeError):
    pass


def inside(root: Path, relative: str) -> Path:
    """`root/relative`, or a refusal when it resolves outside the root."""
    root = root.resolve()
    target = (root / relative).resolve() if relative not in ("", ".") else root
    if target != root and root not in target.parents:
        raise TreeError(f"{relative!r} is outside this sage's tree")
    return target


def _root() -> Path:
    value = os.environ.get(ROOT_VARIABLE, "")
    if not value:
        raise TreeError(f"{ROOT_VARIABLE} is not set: this run has no tree")
    return Path(value)


def _queue() -> Path:
    value = os.environ.get(QUEUE_VARIABLE, "")
    if not value:
        raise TreeError(f"{QUEUE_VARIABLE} is not set: this run has no study queue")
    return Path(value)


def _empty(root: Path) -> bool:
    return not root.is_dir() or not any(p.name != ".git" for p in root.iterdir())


def cmd_ls(args, out) -> int:
    root = _root()
    if _empty(root):
        print("(the tree is empty: this sage's study has published nothing yet)", file=out)
        return 0
    target = inside(root, args.path)
    if not target.is_dir():
        raise TreeError(f"{args.path!r} is not a directory")
    for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
        if entry.name == ".git":
            continue
        print(f"{entry.name}/" if entry.is_dir() else entry.name, file=out)
    return 0


def cmd_cat(args, out) -> int:
    root = _root()
    for relative in args.paths:
        target = inside(root, relative)
        if not target.is_file():
            raise TreeError(f"{relative!r} is not a file in this tree")
        data = target.read_bytes()
        text = data[:MAX_CAT_BYTES].decode("utf-8", errors="replace")
        if len(args.paths) > 1:
            print(f"==> {relative} <==", file=out)
        for number, line in enumerate(text.splitlines(), 1):
            print(f"{number:>6}\t{line}", file=out)
        if len(data) > MAX_CAT_BYTES:
            print(f"[... {len(data) - MAX_CAT_BYTES} more bytes not shown ...]", file=out)
    return 0


def cmd_grep(args, out) -> int:
    root = _root()
    target = inside(root, args.path)
    try:
        pattern = re.compile(args.pattern, re.IGNORECASE if args.ignore_case else 0)
    except re.error as error:
        raise TreeError(f"bad pattern: {error}") from error
    files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file() and ".git" not in p.parts)
    shown = 0
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            if pattern.search(line):
                print(f"{path.relative_to(root.resolve()).as_posix()}:{number}:{line}", file=out)
                shown += 1
                if shown >= MAX_GREP_LINES:
                    print(f"[... more than {MAX_GREP_LINES} matches; narrow the pattern or the path ...]", file=out)
                    return 0
    if shown == 0:
        print("(no match)", file=out)
    return 0


def cmd_find(args, out) -> int:
    root = _root().resolve()
    if _empty(root):
        print("(the tree is empty)", file=out)
        return 0
    found = sorted(p for p in root.glob(args.glob) if p.is_file() and ".git" not in p.parts)
    for path in found:
        print(path.relative_to(root).as_posix(), file=out)
    if not found:
        print("(no match)", file=out)
    return 0


def cmd_revision(args, out) -> int:
    from .sages import knowledge_revision

    print(knowledge_revision(_root()), file=out)
    return 0


def cmd_queue(args, out) -> int:
    queue = _queue()
    if args.queue_command == "list":
        notes = sorted(queue.glob("*.md")) if queue.is_dir() else []
        if not notes:
            print("(the study queue is empty)", file=out)
            return 0
        for path in notes:
            first = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            print(f"{path.stem}: {first[0] if first else ''}", file=out)
        return 0
    if not SLUG_RE.match(args.slug):
        raise TreeError(f"{args.slug!r} is not a note slug ({SLUG_RE.pattern})")
    text = " ".join(args.text).strip()
    if not text:
        raise TreeError("a note needs text")
    queue.mkdir(parents=True, exist_ok=True)
    path = queue / f"{args.slug}.md"
    if path.exists():
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n" + text + "\n")
        print(f"appended to {path.name}", file=out)
    else:
        path.write_text(text + "\n", encoding="utf-8")
        print(f"created {path.name}", file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sagetree", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("ls", help="entries of a directory in the tree")
    ls.add_argument("path", nargs="?", default=".")
    ls.set_defaults(run=cmd_ls)
    cat = sub.add_parser("cat", help="print files with line numbers")
    cat.add_argument("paths", nargs="+")
    cat.set_defaults(run=cmd_cat)
    grep = sub.add_parser("grep", help="lines matching a regular expression")
    grep.add_argument("pattern")
    grep.add_argument("path", nargs="?", default=".")
    grep.add_argument("-i", "--ignore-case", action="store_true")
    grep.set_defaults(run=cmd_grep)
    find = sub.add_parser("find", help="files matching a glob under the tree")
    find.add_argument("glob")
    find.set_defaults(run=cmd_find)
    revision = sub.add_parser("revision", help="the tree's git revision")
    revision.set_defaults(run=cmd_revision)
    queue = sub.add_parser("queue", help="the study queue: what this sage could not answer")
    queue_sub = queue.add_subparsers(dest="queue_command", required=True)
    queue_sub.add_parser("list", help="the notes in the queue")
    add = queue_sub.add_parser("add", help="create a note, or append to one with this slug")
    add.add_argument("slug")
    add.add_argument("text", nargs="+")
    queue.set_defaults(run=cmd_queue)
    return parser


def run(argv: list[str], out=None, err=None) -> int:
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    args = build_parser().parse_args(argv)
    try:
        return args.run(args, out)
    except TreeError as error:
        print(f"sagetree: {error}", file=err)
        return 1


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
