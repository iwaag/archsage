"""`archsage`: the council's own tools — sages, their studies, their queues.

    archsage sage list | show <name>
    archsage sage add <name> --about "…" --guide-file <path> [--project <slug> [--source main|publish] [--repository <url>]]
    archsage sage update <name> [--about "…"] [--guide-file <path>]
    archsage sage attach <name> --project <slug> [--source main|publish] [--repository <url>]
    archsage sage sync [<name> [--require <commit>]]
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
  tree where it was and says so. Inside a serving, a refresh (by `sync` or
  `attach`) is recorded in the conversation served as
  `[selfnote][sagesync] <sage> <revision> …`: that note, not the reply's
  words, is what says a study's knowledge was refreshed.
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
from .sages import (SOURCES, SageError, add_sage, attach_study, includes, load_sages, remove_sage, sage_named,
                    sync_sage, update_sage)

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


SYNC_TAG = "sagesync"


def sync_note(sage, result, *, asked_for: str = "", required: str = "", included: bool | None = None) -> str:
    """`[selfnote][sagesync] <sage> <revision> project=<slug> findings=<n>
    [for=<channel>/<topic>#<anchor>] [includes=<commit>|missing=<commit>]`
    — the record that a sage's tree was refreshed (progress_panel p1), and
    since failsafe p5 **for whom** (the conversation whose request this
    serving answers) and **whether it holds the result** that request needed
    (the integrated commit it named, checked by ancestry in the tree)."""
    from agag.selfnote import note

    project = f" project={sage.project}" if getattr(sage, "project", "") else ""
    value = f"{sage.name} {result.revision}{project} findings={result.findings}"
    if asked_for:
        value += f" for={asked_for}"
    if required:
        value += f" {'includes' if included else 'missing'}={required}"
    return note(SYNC_TAG, value)


def asked_for(client, home) -> str:
    """The conversation this serving's request came from: the asker's root
    note in the home topic (`<channel>/<topic>#<anchor>`), or "" when the
    topic was opened by hand. Read, never inferred from names."""
    from agag.selfnote import parse_rootchat

    try:
        history = client.topic_history(home.channel, home.topic, num_before=400)
        self_id = int(client.whoami()["user_id"])
    except Exception:  # noqa: BLE001 - the relation is said to be unknown
        return ""
    for message in history:
        found = parse_rootchat(message.get("content")) if message.get("sender_id") != self_id else None
        if found is not None:
            return f"{found.channel}/{found.topic}" + (f"#{found.anchor}" if found.anchor else "")
    return ""


def _record_sync(sage, result, out, *, required: str = "", included: bool | None = None) -> None:
    """Leave the refresh on record in the conversation this run serves.

    A selfnote buys nobody a run. Outside a serving (no `AGENTCHAT_HOME`)
    there is no conversation to record it in, and nothing is written; a
    note that cannot be written is said and is not fatal — the tree is
    refreshed either way."""
    from agag.chat import client_from_environment
    from agag.selfnote import home_from_environment
    from agag.zulip import locate

    home = home_from_environment()
    if home is None:
        return
    try:
        client = client_from_environment()
        where = locate(client, home) or home
        text = sync_note(sage, result, asked_for=asked_for(client, where), required=required, included=included)
        client.send_to_channel(where.channel, where.topic, text)
        print(f"recorded in {where.channel}/{where.topic}: {text.split('] ', 1)[-1]}", file=out)
    except Exception as error:  # noqa: BLE001 - the refresh stands; its record is said to be missing
        print(f"warning: the refresh was not recorded in {home.channel}/{home.topic} ({error})", file=out)


def _sync(sage, out, required: str = ""):
    result = sync_sage(sage)
    included = includes(sage.tree, required) if required else None
    if required:
        print(f"{sage.name} at {result.revision} " + ("includes" if included else "does NOT include")
              + f" {required}", file=out)
    _record_sync(sage, result, out, required=required, included=included)
    return result


def _sync_and_say(sage, out) -> None:
    try:
        print(f"tree: {_sync(sage, out).line()}", file=out)
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
    if args.require and len(sages) != 1:
        print("--require names the result one sage's refresh must include: give the sage", file=out)
        return 1
    failed = 0
    for sage in sages:
        try:
            print(_sync(sage, out, args.require or "").line(), file=out)
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
    sage_sub.add_parser(
        "list", help="every sage, its tree and its study",
        description=("One line per sage: `sage:<name>`, its one line, then [its tree's revision and how many "
                     "knowledge files it holds — `no findings yet` when only the plan, READMEs and indexes are "
                     "there, `empty tree` when nothing is synced; how many questions its queue holds] and its "
                     "study (`pj-<slug>`, main or publish), or `no study attached`. A read.")
    ).set_defaults(run=cmd_sage_list)
    show = sage_sub.add_parser(
        "show", help="one sage in full",
        description="One sage: its one line, study and source, tree path and state, queue size and guide file. A read.")
    show.add_argument("name")
    show.set_defaults(run=cmd_sage_show)
    add = sage_sub.add_parser(
        "add", help="define a new sage (optionally already attached to a study)",
        description=("Define a sage for a domain nobody covers: its one line (--about) and its domain guide — what "
                     "it knows, how it answers, what it queues. With --project it is attached to that study at once "
                     "and its tree synced (the same as `attach`); without, its tree is empty and it says so when "
                     "asked. Prints where it was defined, the tree's revision and findings, then the definitions "
                     "store commit and whether the introduction was re-posted. A name already defined is refused: "
                     "`update` or `attach` it instead."))
    add.add_argument("name")
    add.add_argument("--about", required=True, help="one line about the domain")
    add.add_argument("--guide-file", default=None, help="the domain guide, as a file")
    add.add_argument("--guide", nargs="*", help="the domain guide, inline")
    add.add_argument("--project", default="", help="the study's slug (its channel is pj-<slug>)")
    add.add_argument("--source", choices=SOURCES, default="main")
    add.add_argument("--repository", default="", help="the repository to clone (default for main: the study's internal one)")
    add.add_argument("--no-intro", action="store_true")
    add.set_defaults(run=cmd_sage_add)
    update = sage_sub.add_parser(
        "update", help="change a sage's one line and/or its guide",
        description=("Replace the sage's one line and/or its domain guide (the whole file). Its tree and study are "
                     "untouched (that is `attach`). Committed to the definitions store; the introduction is "
                     "re-posted."))
    update.add_argument("name")
    update.add_argument("--about", default=None, help="the new one line about the domain")
    update.add_argument("--guide-file", default=None, help="the new domain guide, whole")
    update.add_argument("--no-intro", action="store_true", help="do not re-post the introduction")
    update.set_defaults(run=cmd_sage_update)
    attach = sage_sub.add_parser(
        "attach", help="point an existing sage at a study's knowledge and sync it",
        description=("Point a sage at a study (`pj-<slug>`) and sync its tree at once: `main` is the study's "
                     "internal knowledge repository, current as soon as research is integrated; `publish` is a "
                     "public repository the developer supplied, which lags behind their review. A tree cloned from "
                     "another repository is replaced (the old one is kept aside). Prints the old and new source, "
                     "the tree's revision and findings, the store commit and the introduction re-post. Inside a "
                     "serving the sync is recorded as `[selfnote][sagesync]`, as with `sync`."))
    attach.add_argument("name")
    attach.add_argument("--project", required=True, help="the study's slug")
    attach.add_argument("--source", choices=SOURCES, default="main",
                        help="main: the internal knowledge repository (default); publish: a public repository")
    attach.add_argument("--repository", default="", help="required for publish; default for main is the study's own")
    attach.add_argument("--no-intro", action="store_true", help="do not re-post the introduction")
    attach.set_defaults(run=cmd_sage_attach)
    remove = sage_sub.add_parser(
        "remove", help="retire a sage (its directory is moved aside, not deleted)",
        description=("Retire a sage: its directory moves to `.local/removed-sages/` (nothing is deleted), the "
                     "removal is committed to the definitions store, and the introduction is re-posted without it."))
    remove.add_argument("name")
    remove.add_argument("--no-intro", action="store_true", help="do not re-post the introduction")
    remove.set_defaults(run=cmd_sage_remove)
    sync = sage_sub.add_parser(
        "sync", help="clone or fast-forward the trees (replaces a tree from another repository)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Refresh a sage's tree from its study (all sages without a name), after research was integrated. It\n"
            "prints `<sage> at <revision> includes|does NOT include <commit>` when --require names one, then the\n"
            "tree's revision and findings. A failed refresh leaves the tree where it was and says so (exit 1).\n"
            "\n"
            "Inside a serving the refresh is recorded in the conversation served:\n"
            "\n"
            "  [selfnote][sagesync] <sage> <revision> project=<slug> findings=<n>\n"
            "      for=<channel>/<topic>#<anchor>  includes=<commit> | missing=<commit>\n"
            "\n"
            "`for=` is the conversation whose request this refresh answers (the asker's root note in the topic\n"
            "you serve). `includes=` says the refreshed tree holds the commit the request named; `missing=` says\n"
            "it does not — that request's knowledge was NOT refreshed, whatever the revision moved to: say so\n"
            "and why (not pushed yet, another repository). The note is the record; saying in your reply that\n"
            "the sage is refreshed records nothing (the progress panel and the requester read the note).\n"
            "Outside a serving nothing is recorded.\n"
            "\n"
            "  archsage sage sync growbox --require 9d34067f5c0a"))
    sync.add_argument("name", nargs="?", default=None)
    sync.add_argument("--require", default=None, metavar="COMMIT",
                      help="the integrated commit the request needs the refreshed tree to include (recorded as "
                           "includes= or missing=); needs a sage name")
    sync.set_defaults(run=cmd_sage_sync)
    ask = sub.add_parser(
        "ask", help="run one sage now and print its answer",
        description=("Consult a sage from inside your own run: it answers from its tree only, on the ordinary "
                     "model (not yours), and says when the tree does not answer. The answer is printed under its "
                     "header; the run is recorded under `.local/agent/sage/`. Nothing is posted: quote what you "
                     "use. Posting `sage:<name>` in a topic would not reach it from your run (a post of this "
                     "account wakes no other role of it)."))
    ask.add_argument("name")
    ask.add_argument("question", nargs="+")
    ask.set_defaults(run=cmd_ask)
    queue = sub.add_parser("queue", help="the sages' study queues")
    queue_sub = queue.add_subparsers(dest="queue_command", required=True)
    listing = queue_sub.add_parser(
        "list", help="the queued notes, per sage",
        description=("Per sage, the questions it was asked and its tree could not answer: `<note>: <first line>`. "
                     "They are research questions somebody already has; carry the ones that fit into a research "
                     "plan or a routine request. A read."))
    listing.add_argument("name", nargs="?", default=None)
    note = queue_sub.add_parser("show", help="one note in full",
                                description="One queued note, whole: the question as asked, why it is the sage's, "
                                            "what a study run should look for. A read.")
    note.add_argument("name")
    note.add_argument("note")
    resolve = queue_sub.add_parser(
        "resolve", help="remove a note the refreshed tree now answers",
        description=("Settle a queued note because files in the sage's refreshed tree now answer it. Every path in "
                     "--answered-by must exist in the tree at its current revision, or nothing changes (refresh it "
                     "first). The note leaves the queue and the settlement is logged with the revision in "
                     "`.local/queue-resolved.jsonl`. Asking for research is not an answer: a note still unanswered "
                     "stays."))
    resolve.add_argument("name")
    resolve.add_argument("note")
    resolve.add_argument("--answered-by", nargs="+", required=True, help="paths in the sage's tree that answer it")
    queue.set_defaults(run=cmd_queue)
    sub.add_parser(
        "intro", help="(re-)post the introduction with the current sage list",
        description=("Post archsage's introduction to `#agents` with the current sage list. Definition changes "
                     "(add, update, attach, remove) do it by themselves; `sync` and a listener restart do not.")
    ).set_defaults(run=cmd_intro)
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
