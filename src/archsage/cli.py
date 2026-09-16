"""`archsage`: the council's own tools — list, add and sync sages; ask one.

    archsage sage list                      every sage, its domain, tree and revision
    archsage sage add <name> --about "…" --guide-file <path> [--study <git url>]
    archsage sage sync [<name>]             clone or fast-forward the study trees
    archsage ask <name> "<question>"        run that sage now and print its answer

`ask` is how archsage consults a sage from inside its own run: the sage's
Zulip posts cannot wake another role of the same account (a listener
ignores its own messages), so the dispatch between roles is a direct call.
The sage's answer is a run of its own, recorded under `.local/agent/sage/`,
and it is printed here for archsage to weigh — with the header that would
have named it in a post.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agag.argue import with_speaker
from agag.topics import chatlog_placement, conversation_context, generation_dir, next_generation, topic_workspace

from .instance import SPEC
from .roles import RoleError, run_sage, sage_context
from .sages import SageError, add_sage, load_sages, sage_named, sync_sage

ASK_CHANNEL = "archsage-internal"

__all__ = ["main", "run"]


def cmd_sage_list(args, out) -> int:
    sages = load_sages()
    if not sages:
        print("no sages defined yet", file=out)
        return 0
    for sage in sages:
        state = sage.revision() if sage.has_knowledge() else "empty tree"
        print(f"{sage.selector}: {sage.about} [{state}]" + (f" <{sage.study}>" if sage.study else ""), file=out)
    return 0


def cmd_sage_add(args, out) -> int:
    guide = Path(args.guide_file).read_text(encoding="utf-8") if args.guide_file else " ".join(args.guide or [])
    sage = add_sage(args.name, args.about, guide, study=args.study or "")
    print(f"defined {sage.selector} at {sage.root}", file=out)
    if sage.study:
        print(f"its study is {sage.study}; `archsage sage sync {sage.name}` clones it", file=out)
    else:
        print("it has no study repository yet: its tree is empty and it will say so when asked", file=out)
    print("re-post the introduction (`python -m archsage.intro`) so the new name is published", file=out)
    return 0


def cmd_sage_sync(args, out) -> int:
    sages = [sage_named(args.name)] if args.name else load_sages()
    if args.name and sages[0] is None:
        raise SageError(f"no sage named {args.name!r}")
    for sage in sages:
        print(sync_sage(sage), file=out)
    return 0


def cmd_ask(args, out) -> int:
    sage = sage_named(args.name)
    if sage is None:
        raise SageError(f"no sage named {args.name!r}; `archsage sage list` names them")
    question = " ".join(args.question).strip()
    if not question:
        raise SageError("ask something")
    rendered = f"[archsage] {question}\n"
    number = next_generation(topic_workspace(SPEC.topics_root, ASK_CHANNEL, sage.name))
    workspace = generation_dir(SPEC.topics_root, ASK_CHANNEL, sage.name, number, "sage")
    (workspace / "chatlog.md").write_text(rendered, encoding="utf-8")
    prompt = "\n".join([
        chatlog_placement("archsage"),
        f"You are taking part as the logical participant {sage.selector!r}, asked directly by archsage.",
        "", conversation_context(rendered), "", sage_context(sage),
    ])
    answer = run_sage(sage, prompt, workspace, extra_meta={"asked_by": "archsage"})
    print(with_speaker(sage.selector, answer), file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archsage", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sage = sub.add_parser("sage", help="list, add or sync sages")
    sage_sub = sage.add_subparsers(dest="sage_command", required=True)
    sage_sub.add_parser("list", help="every sage").set_defaults(run=cmd_sage_list)
    add = sage_sub.add_parser("add", help="define a new sage")
    add.add_argument("name")
    add.add_argument("--about", required=True, help="one line about the domain")
    add.add_argument("--study", default="", help="git URL of the study whose published knowledge is its tree")
    add.add_argument("--guide-file", default=None, help="the domain guide, as a file")
    add.add_argument("--guide", nargs="*", help="the domain guide, inline")
    add.set_defaults(run=cmd_sage_add)
    sync = sage_sub.add_parser("sync", help="clone or fast-forward the study trees")
    sync.add_argument("name", nargs="?", default=None)
    sync.set_defaults(run=cmd_sage_sync)
    ask = sub.add_parser("ask", help="run one sage now and print its answer")
    ask.add_argument("name")
    ask.add_argument("question", nargs="+")
    ask.set_defaults(run=cmd_ask)
    return parser


def run(argv: list[str], out=None, err=None) -> int:
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    args = build_parser().parse_args(argv)
    try:
        return args.run(args, out)
    except (SageError, RoleError, OSError) as error:
        print(f"archsage: {error}", file=err)
        return 1


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
