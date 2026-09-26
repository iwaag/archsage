"""archsage's chat entrance: one account, the council and its sages.

Two routes, one account:

- **Its own channel** (`archsage-agstudio1`): every topic is a question.
  The newest post decides who answers — a post whose first token is a
  selector (`sage:arxiv what is trending?`) is answered by that sage, any
  other by archsage — and the reply carries the speaker's header. A
  request for a sage costs no archsage run.
- **An argue** (`agag.argue`): named there — `@**archsage** sage:arxiv …`
  for a sage, a bare `@**archsage**` for the council — each outstanding
  invitation is answered by the addressed role, in place, with its header.
- **A callback** (sage p2): archsage delegates — a study's workspace is
  asked of autolab in its project channel — and ends its run. The topic it
  posted in holds its root note naming the conversation of its own it
  spoke for; when the answer names archsage there, *that* conversation is
  served again, with the answering topic beside it as a thread, and the
  reply goes home. A mention with no root note of ours is logged and left.

The reply in the own channel names the requester (the turn is theirs), so
an agent that asked — Front, delegating a study — is called back with the
answer. A reply that only says the work is still pending declares
`intent=progress` and names nobody: waiting buys nobody a run.

Dispatch between roles never goes through Zulip: a listener ignores its own
posts, so a sage cannot be woken by archsage writing to it. archsage asks a
sage from inside its own run (`archsage ask`) instead.
"""

from __future__ import annotations

from agag.post import REPORT, PostMeta
from agag.agent import SWEEP_ACK as ACK_TEXT, exec_options_for, is_ack, listener_main
from agag.argue import (
    Invitation,
    is_argue_topic,
    mentions_of,
    parse_selector,
    participate,
    with_speaker,
)
from agag.entrance import EMPTY_REPLY
from agag.selfnote import is_speech
from agag.reply import REPLY_GUIDE, repair_with, resolve_reply
from agag.topics import (
    TopicResult,
    chatlog_path,
    chatlog_placement,
    conversation_context,
    format_chatlog,
    generation_dir,
    next_generation,
    prompt_with_guide,
    serve_topic,
    topic_workspace,
)
from agag import serving as serving_record
from agag.selfnote import Conversation
from agag.zulip import (
    ZulipClient,
    ZulipError,
    locate,
    log,
    note_served,
    remotes_for_home,
    rootchat_home,
    topic_history_across_resolve,
)

from .instance import ARCHSAGE_ROLE, SAGE_ROLE, SELECTOR_KIND, SPEC
from .roles import archsage_context, run_archsage, run_sage, sage_context
from .sages import load_sages, sage_named, selectors

NO_ANSWER = "I have nothing to add here."
THREAD_MESSAGES = 60
THREAD_CHARS = 12_000

__all__ = ["ACK_TEXT", "NO_ANSWER", "addressed", "handle_callback", "handle_mention", "handle_topic", "main", "serve",
           "write_threads"]


def addressed(history: list[dict], self_id: int) -> str | None:
    """Which logical speaker the newest post by somebody else addresses:
    a leading `sage:<name>` token (after an optional mention of us), or
    None for archsage itself."""
    for message in reversed(history):
        if message.get("sender_id") == self_id or not is_speech(message):
            continue
        text = str(message.get("content", "")).strip()
        for selector in mentions_of(text, "archsage"):
            if selector:
                return selector
        first = text.split(maxsplit=1)[0] if text else ""
        return parse_selector(first) if first.startswith(f"{SELECTOR_KIND}:") else None
    return None


def _unknown(selector: str) -> str:
    names = ", ".join(selectors()) or "none"
    return with_speaker(selector, f"There is no participant {selector!r} on this account. The ones I answer for are: {names}.")


def serve(context) -> TopicResult:
    """One question in the own channel: the sage it names, or archsage."""
    selector = addressed(context.history, context.self_id)
    role = SAGE_ROLE if selector else ARCHSAGE_ROLE
    context.step = "chatlog"
    number = next_generation(topic_workspace(SPEC.topics_root, context.channel, context.topic))
    workspace = generation_dir(SPEC.topics_root, context.channel, context.topic, number, role)
    chatlog = format_chatlog(context.history, context.self_id, drop=is_ack)
    chatlog_path(workspace).write_text(chatlog, encoding="utf-8")
    conversation = conversation_context(chatlog)
    asked = max((int(m.get("id", 0)) for m in context.history), default=0)
    if selector:
        sage = sage_named(selector.split(":", 1)[1])
        if sage is None:
            return TopicResult([_unknown(selector)], meta=PostMeta(intent=REPORT))
        context.step = sage.selector
        prompt = "\n".join([chatlog_placement(context.bot_name),
                            f"You are taking part as the logical participant {sage.selector!r}.",
                            "", conversation, "", sage_context(sage), "", REPLY_GUIDE])
        output = run_sage(sage, prompt, workspace, extra_meta={"requested": asked}, selection=context.selection)
        # The speaker header is the posting layer's, so the reply contract
        # (`agag.reply`) is resolved here and the header put in front of it.
        answer, split, _ = resolve_reply(
            output, repair_with(lambda again: run_sage(sage, again, workspace, extra_meta={"requested": asked},
                                                       selection=context.selection), output), log=log)
        journal = getattr(context, "journal", None)
        if journal is not None:
            journal.reply_outcome(marked=split.marked, blocks=split.blocks, failure=split.error or "")
        # What the sage's reply is for rides with it, as the listener's own
        # reply would (`agag.post`); a failed reply is a report.
        return TopicResult([with_speaker(sage.selector, answer)],
                           meta=split.meta if split.ok else PostMeta(intent=REPORT))
    context.step = "threads"
    threads = write_threads(context, workspace)
    context.step = ARCHSAGE_ROLE
    home = (context.channel, context.topic)
    placement = [chatlog_placement(context.bot_name), "", conversation]
    if threads:
        placement += ["", threads]
    prompt = prompt_with_guide(placement, archsage_context(), reply=True)
    output = run_archsage(prompt, workspace, home=home, extra_meta={"requested": asked}, selection=context.selection)
    return TopicResult(output=output, quiet_progress=True, repair=repair_with(
        lambda again: run_archsage(again, workspace, home=home, extra_meta={"requested": asked},
                                   selection=context.selection), output))


def write_threads(context, workspace) -> str:
    """The conversations this one is waiting on — each topic where our own
    root note names it, plus the one that just called back — written to
    `threads/` and summarised for the prompt. Empty when there are none."""
    remotes = list(dict.fromkeys([
        *(c.as_pair() for c in remotes_for_home(context.client, context.channel, context.topic,
                                                home_messages=context.history)),
        *(tuple(pair) for pair in context.extra_threads)]))
    if not remotes:
        return ""
    directory = workspace / "threads"
    directory.mkdir(exist_ok=True)
    lines = ["Conversations elsewhere that this one is waiting on (answers to what you asked there), newest posts last:"]
    for channel, topic in remotes:
        try:
            history = topic_history_across_resolve(context.client, channel, topic, THREAD_MESSAGES)
        except ZulipError as error:
            lines.append(f"- #{channel} › {topic}: could not be read ({error})")
            continue
        text = format_chatlog(history, context.self_id, drop=is_ack)
        path = directory / f"{channel}__{topic.replace('/', '_')}.md"
        path.write_text(text, encoding="utf-8")
        lines.append(f"- #{channel} › {topic} — {path}\n\n{conversation_context(text, budget=THREAD_CHARS, file_name=path.name)}")
    return "\n".join(lines)


def handle_topic(client: ZulipClient, channel: str, topic: str) -> None:
    log(f"question {channel!r}/{topic!r}")
    serve_topic(client, channel, topic, serve, ack_text=ACK_TEXT, empty_reply=EMPTY_REPLY,
                exec_options=exec_options_for(SPEC, client))


def _argue_context(invitation: Invitation) -> str:
    if invitation.selector:
        sage = sage_named(invitation.selector.split(":", 1)[1])
        return sage_context(sage) if sage else ""
    return archsage_context()


def _argue_run(prompt: str, cwd, invitation: Invitation) -> str:
    meta = {"invitation": invitation.message_id}
    if invitation.selector:
        sage = sage_named(invitation.selector.split(":", 1)[1])
        return run_sage(sage, prompt, cwd, extra_meta=meta)
    return run_archsage(prompt, cwd, extra_meta=meta)


def handle_mention(client: ZulipClient, channel: str, topic: str) -> None:
    if is_argue_topic(channel, topic):
        log(f"argue invitation in {channel!r}/{topic!r}")
        participate(client, channel, topic, spec=SPEC, role_context=_argue_context, run=_argue_run,
                    selectors=[None, *selectors()], drop=is_ack, log=log)
        return
    handle_callback(client, channel, topic)


def handle_callback(client: ZulipClient, channel: str, topic: str) -> None:
    """archsage was named where it had delegated: serve the conversation of
    its own the root note there names, and answer at home.

    Home is located by its anchor (a renamed or ✔'d home is still found; a
    reused name is not taken for it). A ✔'d home is served where it is,
    under its ✔ name — the work it was waiting for has come back and its
    requester is still owed the result; nothing is posted under the bare
    name, so no twin is opened."""
    self_id = int(client.whoami()["user_id"])
    home = rootchat_home(client, channel, topic, self_id)
    if home is None:
        log(f"mention in {channel!r}/{topic!r} carries no root note of ours; ignoring")
        return
    located = locate(client, home)
    if located is None:
        log(f"mention in {channel!r}/{topic!r} is for {home}, which no longer exists; ignoring")
        return
    if is_argue_topic(located.channel, located.topic):
        log(f"mention in {channel!r}/{topic!r} is for the argue {located}; archsage speaks there only when invited")
        return
    log(f"mention in {channel!r}/{topic!r} serves {located}")
    serve_topic(client, located.channel, located.topic, serve, ack_text=ACK_TEXT, empty_reply=EMPTY_REPLY,
                extra_threads=((channel, topic),), exec_options=exec_options_for(SPEC, client))
    if serving_record.current() is None:
        # Outside a listener the mark is written here; under `agag.listen`
        # the executor writes it after the reply's delivery is confirmed.
        served = note_served(client, Conversation(home.channel, located.topic, home.anchor), channel, topic)
        log(f"marked {channel!r}/{topic!r} served up to {served} in {located}" if served
            else f"nothing to mark served in {channel!r}/{topic!r}")


def main() -> None:
    log(f"sages: {', '.join(s.selector for s in load_sages()) or 'none'}")
    listener_main(SPEC, {}, entrance=handle_topic, on_mention=handle_mention)


if __name__ == "__main__":
    main()
