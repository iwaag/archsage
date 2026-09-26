"""`archsage`: the council's own tools — sages, their studies, their queues.

    archsage sage list | show <name>
    archsage sage add <name> --about "…" --guide-file <path> [--project <slug> [--source main|publish] [--repository <url>]]
    archsage sage update <name> [--about "…"] [--guide-file <path>]
    archsage sage attach <name> --project <slug> [--source main|publish] [--repository <url>]
    archsage sage sync [<name>]
    archsage sage remove <name>
    archsage ask <name> "<question>"
    archsage queue list [<name>] | show <name> <note> | resolve <name> <note> --answered-by <path>…
    archsage intro
    archsage store status | restore

What each is for:

- **A sage** is one domain and the knowledge tree of one study. `add`
  defines one; `update` changes its one line or its guide; `attach` points
  an existing sage at a study — `main` (the study's internal knowledge
  repository: current as soon as research is integrated, the default) or
  `publish` (a public repository the developer supplied, which lags behind
  their review and push). Attaching syncs the tree at once and says the
  revision and whether the study has findings yet.
- **`sync`** refreshes a tree after research was integrated. A tree cloned
  from another repository than the definition names is replaced (the old
  one is kept under `.local/replaced-trees/`). A failed refresh leaves the
  tree where it was and says so.
- Every definition change is **committed and pushed** to the definitions
  store (`archsage store --help`) and the introduction is **re-posted** so
  the sage list others read is current (`--no-intro` skips that).
- **`ask`** consults a sage from inside your run: the sage's Zulip posts
  cannot wake another role of this account, so the dispatch is a direct
  call, recorded under `.local/agent/sage/`.
- **`queue`** reads the sages' study queues — the questions they could not
  answer. `resolve` removes a note only when files in the refreshed tree
  answer it; asking for research is not an answer.

Exit status 1 with one line on failure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agag.argue import with_speaker
from agag.topics import chatlog_placement, conversation_context, generation_dir, next_generation, topic_workspace

from . import store
from .instance import SPEC
from .queue import note_path, resolve_note
from .roles import RoleError, run_sage, sage_context
from .sages import SOURCES, SageError, add_sage, attach_study, load_sages, remove_sage, sage_named, sync_sage, update_sage

ASK_CHANNEL = "archsage-internal"

__all__ = ["main", "run"]


def _sage(name: str):
    sage = sage_named(name)
    if sage is None:
        raise SageError(f"no sage named {name!r}; `archsage sage list` names them")
    return sage


def _state(sage) -> str:
    if not sage.has_knowledge():
        return "empty tree"
    found = sage.findings()
    return f"{sage.revision()}, " + (f"{found} knowledge file(s)" if found else "no findings yet")


def cmd_sage_list(args, out) -> int:
    sages = load_sages()
    if not sages:
        print("no sages defined yet", file=out)
        return 0
    for sage in sages:
        queued = len(sage.queued())
        print(f"{sage.selector}: {sage.about} [{_state(sage)}; {queued} queued] — {sage.describe_source()}", file=out)
    return 0


def cmd_sage_show(args, out) -> int:
    sage = _sage(args.name)
    print(f"{sage.selector}\n  about: {sage.about}\n  study: {sage.describe_source()}\n  tree: {sage.tree} "
          f"({_state(sage)})\n  queue: {len(sage.queued())} note(s) in {sage.queue}\n  guide: {sage.guide_path}", file=out)
    return 0


def _persist(message: str) -> str:
    return store.persist(message)


def _post_intro() -> None:
    from .intro import main as post_intro

    post_intro()


def _after_change(sage, what: str, args, out) -> int:
    code = 0
    try:
        print(f"definitions store: {_persist(f'{what} {sage.selector}')}", file=out)
    except store.StoreError as error:
        print(f"warning: the change is local only — {error}", file=out)
        code = 1
    if not getattr(args, "no_intro", False):
        try:
            _post_intro()
            print("introduction re-posted: the sage list on the board is current", file=out)
        except Exception as error:  # noqa: BLE001 - the definition stands; the board is one command away
            print(f"warning: the introduction was not re-posted ({error}); run `archsage intro`", file=out)
            code = 1
    return code


def _sync_and_say(sage, out) -> None:
    try:
        print(f"tree: {sync_sage(sage).line()}", file=out)
    except SageError as error:
        print(f"tree: {error}", file=out)


def cmd_sage_add(args, out) -> int:
    guide = Path(args.guide_file).read_text(encoding="utf-8") if args.guide_file else " ".join(args.guide or [])
    study = args.repository or ""
    sage = add_sage(args.name, args.about, guide, study=study, project=args.project or "",
                    source=args.source if (args.project or study) else "")
    if args.project and not study:
        sage = attach_study(sage.name, project=args.project, source=args.source)
    print(f"defined {sage.selector} at {sage.root} — {sage.describe_source()}", file=out)
    if sage.study:
        _sync_and_say(sage, out)
    else:
        print("it has no study yet: its tree is empty and it will say so when asked", file=out)
    return _after_change(sage, "Define", args, out)


def cmd_sage_update(args, out) -> int:
    if args.about is None and not args.guide_file:
        raise SageError("nothing to update: give --about and/or --guide-file")
    guide = Path(args.guide_file).read_text(encoding="utf-8") if args.guide_file else None
    sage = update_sage(args.name, about=args.about, guide=guide)
    print(f"updated {sage.selector}", file=out)
    return _after_change(sage, "Update", args, out)


def cmd_sage_attach(args, out) -> int:
    before = _sage(args.name)
    sage = attach_study(args.name, project=args.project, source=args.source, repository=args.repository or "")
    was = before.describe_source()
    print(f"attached {sage.selector} to {sage.describe_source()}" + (f" (was: {was})" if was != sage.describe_source() else ""),
          file=out)
    _sync_and_say(sage, out)
    return _after_change(sage, "Attach", args, out)


def cmd_sage_remove(args, out) -> int:
    sage = _sage(args.name)
    aside = remove_sage(args.name)
    print(f"removed {sage.selector}; its directory is kept at {aside}", file=out)
    return _after_change(sage, "Remove", args, out)


def cmd_sage_sync(args, out) -> int:
    sages = [_sage(args.name)] if args.name else load_sages()
    failed = 0
    for sage in sages:
        try:
            print(sync_sage(sage).line(), file=out)
        except SageError as error:
            failed += 1
            print(str(error), file=out)
    return 1 if failed else 0


def cmd_ask(args, out) -> int:
    sage = _sage(args.name)
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


def cmd_queue(args, out) -> int:
    if args.queue_command == "list":
        sages = [_sage(args.name)] if args.name else load_sages()
        for sage in sages:
            notes = sage.queued()
            print(f"{sage.selector}: {len(notes)} note(s)", file=out)
            for note in notes:
                first = note.read_text(encoding="utf-8").strip().splitlines()[0:1]
                print(f"  {note.stem}: {(first[0] if first else '')[:160]}", file=out)
    elif args.queue_command == "show":
        print(note_path(_sage(args.name), args.note).read_text(encoding="utf-8"), file=out)
    else:
        record = resolve_note(_sage(args.name), args.note, args.answered_by)
        print(f"resolved {record['note']} of {args.name}: answered at {record['revision']} by "
              f"{', '.join(record['answered_by'])} (logged in .local/queue-resolved.jsonl)", file=out)
    return 0


def cmd_intro(args, out) -> int:
    _post_intro()
    print("introduction posted", file=out)
    return 0


def cmd_store(args, out) -> int:
    if args.store_command == "status":
        for key, value in store.status().items():
            print(f"{key}: {value}", file=out)
    else:
        print(store.restore(), file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archsage", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sage = sub.add_parser("sage", help="list, show, add, update, attach or sync sages")
    sage_sub = sage.add_subparsers(dest="sage_command", required=True)
    sage_sub.add_parser("list", help="every sage, its tree and its study").set_defaults(run=cmd_sage_list)
    show = sage_sub.add_parser("show", help="one sage in full")
    show.add_argument("name")
    show.set_defaults(run=cmd_sage_show)
    add = sage_sub.add_parser("add", help="define a new sage (optionally already attached to a study)")
    add.add_argument("name")
    add.add_argument("--about", required=True, help="one line about the domain")
    add.add_argument("--guide-file", default=None, help="the domain guide, as a file")
    add.add_argument("--guide", nargs="*", help="the domain guide, inline")
    add.add_argument("--project", default="", help="the study's slug (its channel is pj-<slug>)")
    add.add_argument("--source", choices=SOURCES, default="main")
    add.add_argument("--repository", default="", help="the repository to clone (default for main: the study's internal one)")
    add.add_argument("--no-intro", action="store_true")
    add.set_defaults(run=cmd_sage_add)
    update = sage_sub.add_parser("update", help="change a sage's one line and/or its guide")
    update.add_argument("name")
    update.add_argument("--about", default=None)
    update.add_argument("--guide-file", default=None)
    update.add_argument("--no-intro", action="store_true")
    update.set_defaults(run=cmd_sage_update)
    attach = sage_sub.add_parser("attach", help="point an existing sage at a study's knowledge and sync it")
    attach.add_argument("name")
    attach.add_argument("--project", required=True, help="the study's slug")
    attach.add_argument("--source", choices=SOURCES, default="main",
                        help="main: the internal knowledge repository (default); publish: a public repository")
    attach.add_argument("--repository", default="", help="required for publish; default for main is the study's own")
    attach.add_argument("--no-intro", action="store_true")
    attach.set_defaults(run=cmd_sage_attach)
    remove = sage_sub.add_parser("remove", help="retire a sage (its directory is moved aside, not deleted)")
    remove.add_argument("name")
    remove.add_argument("--no-intro", action="store_true")
    remove.set_defaults(run=cmd_sage_remove)
    sync = sage_sub.add_parser("sync", help="clone or fast-forward the trees (replaces a tree from another repository)")
    sync.add_argument("name", nargs="?", default=None)
    sync.set_defaults(run=cmd_sage_sync)
    ask = sub.add_parser("ask", help="run one sage now and print its answer")
    ask.add_argument("name")
    ask.add_argument("question", nargs="+")
    ask.set_defaults(run=cmd_ask)
    queue = sub.add_parser("queue", help="the sages' study queues")
    queue_sub = queue.add_subparsers(dest="queue_command", required=True)
    listing = queue_sub.add_parser("list", help="the queued notes, per sage")
    listing.add_argument("name", nargs="?", default=None)
    note = queue_sub.add_parser("show", help="one note in full")
    note.add_argument("name")
    note.add_argument("note")
    resolve = queue_sub.add_parser("resolve", help="remove a note the refreshed tree now answers")
    resolve.add_argument("name")
    resolve.add_argument("note")
    resolve.add_argument("--answered-by", nargs="+", required=True, help="paths in the sage's tree that answer it")
    queue.set_defaults(run=cmd_queue)
    sub.add_parser("intro", help="(re-)post the introduction with the current sage list").set_defaults(run=cmd_intro)
    store_parser = sub.add_parser("store", help="the sage definitions store (status, restore)",
                                  description=store.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    store_sub = store_parser.add_subparsers(dest="store_command", required=True)
    store_sub.add_parser("status")
    store_sub.add_parser("restore")
    store_parser.set_defaults(run=cmd_store)
    return parser


def run(argv: list[str], out=None, err=None) -> int:
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    args = build_parser().parse_args(argv)
    try:
        return args.run(args, out)
    except (SageError, RoleError, store.StoreError, OSError) as error:
        print(f"archsage: {error}", file=err)
        return 1


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
