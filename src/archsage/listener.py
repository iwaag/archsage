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
  Any other mention is logged and left.

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
from agag.zulip import ZulipClient, log

from .instance import ARCHSAGE_ROLE, SAGE_ROLE, SELECTOR_KIND, SPEC
from .roles import archsage_context, run_archsage, run_sage, sage_context
from .sages import load_sages, sage_named, selectors

NO_ANSWER = "I have nothing to add here."

__all__ = ["ACK_TEXT", "NO_ANSWER", "addressed", "handle_mention", "handle_topic", "main", "serve"]


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
    context.step = ARCHSAGE_ROLE
    home = (context.channel, context.topic)
    prompt = prompt_with_guide([chatlog_placement(context.bot_name), "", conversation], archsage_context(), reply=True)
    output = run_archsage(prompt, workspace, home=home, extra_meta={"requested": asked}, selection=context.selection)
    return TopicResult(output=output, repair=repair_with(
        lambda again: run_archsage(again, workspace, home=home, extra_meta={"requested": asked},
                                   selection=context.selection), output))


def handle_topic(client: ZulipClient, channel: str, topic: str) -> None:
    log(f"question {channel!r}/{topic!r}")
    serve_topic(client, channel, topic, serve, ack_text=ACK_TEXT, empty_reply=EMPTY_REPLY, handoff=False,
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
    if not is_argue_topic(channel, topic):
        log(f"mention in {channel!r}/{topic!r} is not an argue; ignoring")
        return
    log(f"argue invitation in {channel!r}/{topic!r}")
    participate(client, channel, topic, spec=SPEC, role_context=_argue_context, run=_argue_run,
                selectors=[None, *selectors()], drop=is_ack, log=log)


def main() -> None:
    log(f"sages: {', '.join(s.selector for s in load_sages()) or 'none'}")
    listener_main(SPEC, {}, entrance=handle_topic, on_mention=handle_mention)


if __name__ == "__main__":
    main()
