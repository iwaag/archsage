"""One account, the council and its sages (`argue` p1 step 2).

Pinned: a leading `sage:<name>` in the own channel, or a selector after the
mention in an argue, is answered by that sage with its header and costs no
archsage run; a bare post or mention is archsage; two sages invited in one
post each get their own context and keep their own identity; a name nobody
publishes is refused without a run; a mention outside an argue is left.
"""

from __future__ import annotations

from dataclasses import replace

from agag import topics

from archsage import listener, roles, sages

BOT = 24
FRONT = 15
DEV = 8


def message(*, sender=DEV, name="Developer", content="hello", id=100, topic="ask-me"):
    return {"id": id, "sender_id": sender, "sender_full_name": name, "content": content,
            "sender_realm_str": "", "subject": topic, "display_recipient": "archsage-agstudio1"}


class Client:
    email = "archsage-agstudio1-bot@example"

    def __init__(self, history):
        self.history = list(history)
        self.calls = []

    def whoami(self, refresh=False):
        return {"user_id": BOT, "full_name": "archsage"}

    def topic_history(self, channel, topic, num_before=50):
        return list(self.history)

    def send_to_channel(self, channel, topic, content):
        self.calls.append(("post", channel, topic, content))
        return 900 + len(self.calls)

    def add_reaction(self, message_id, emoji_name="eyes"):
        self.calls.append(("react", message_id))


def two_sages(tmp_path, monkeypatch):
    root = tmp_path / "sages"
    a = sages.add_sage("arxiv", "arXiv papers", "# arXiv guide", root=root)
    b = sages.add_sage("realworld", "public sources", "# realworld guide", root=root)
    monkeypatch.setattr(sages, "SAGES_ROOT", root)
    return a, b


def wire(monkeypatch, tmp_path):
    two_sages(tmp_path, monkeypatch)
    monkeypatch.setattr(listener, "SPEC", replace(listener.SPEC, root=tmp_path))
    runs = []

    def run_sage(sage, prompt, cwd, *, extra_meta=None, selection=None, timeout=None):
        runs.append(("sage", sage.name, prompt, dict(extra_meta or {})))
        return f"{sage.name} answers"

    def run_archsage(prompt, cwd, *, home=None, extra_meta=None, selection=None, timeout=None):
        runs.append(("archsage", None, prompt, dict(extra_meta or {})))
        return "the council answers"

    monkeypatch.setattr(listener, "run_sage", run_sage)
    monkeypatch.setattr(listener, "run_archsage", run_archsage)
    monkeypatch.setattr(topics, "topic_write", lambda topic, text, **kw: runs.append(("reply", text)) or "success")
    return runs


# --- who is addressed --------------------------------------------------------------


def test_the_newest_post_decides_who_answers():
    assert listener.addressed([message(content="sage:arxiv what is trending?")], BOT) == "sage:arxiv"
    assert listener.addressed([message(content="@**archsage** sage:realworld problems?")], BOT) == "sage:realworld"
    assert listener.addressed([message(content="what should we study?")], BOT) is None
    assert listener.addressed([message(content="sage:arxiv x", id=1), message(content="and you?", id=2)], BOT) is None
    assert listener.addressed([message(content="sage:arxiv x", id=1), message(sender=BOT, name="archsage", content="…", id=2)], BOT) == "sage:arxiv"
    assert listener.addressed([message(content="Sage:arxiv nope")], BOT) is None


# --- the own channel -----------------------------------------------------------------


def test_a_direct_sage_request_costs_no_archsage_run(monkeypatch, tmp_path):
    runs = wire(monkeypatch, tmp_path)
    monkeypatch.setattr(listener, "exec_options_for", lambda spec, client: None)
    listener.handle_topic(Client([message(content="sage:arxiv what is trending?")]), "archsage-agstudio1", "ask-me")
    kinds = [r[0] for r in runs]
    assert "archsage" not in kinds and kinds.count("sage") == 1
    _, name, prompt, meta = next(r for r in runs if r[0] == "sage")
    assert name == "arxiv" and "# arXiv guide" in prompt and "# realworld guide" not in prompt
    assert meta == {"requested": 100}
    replies = [r[1] for r in runs if r[0] == "reply"]
    assert replies[-1] == "**[sage:arxiv]**\narxiv answers"
    assert not any(reply.startswith("@**") for reply in replies)


def test_a_plain_question_is_the_council_s(monkeypatch, tmp_path):
    runs = wire(monkeypatch, tmp_path)
    monkeypatch.setattr(listener, "exec_options_for", lambda spec, client: None)
    listener.handle_topic(Client([message(content="what should we study first?")]), "archsage-agstudio1", "ask-me")
    kinds = [r[0] for r in runs]
    assert kinds.count("archsage") == 1 and "sage" not in kinds
    _, _, prompt, _ = next(r for r in runs if r[0] == "archsage")
    assert "sage:arxiv" in prompt and "sage:realworld" in prompt  # it sees every tree
    assert [r[1] for r in runs if r[0] == "reply"][-1] == "the council answers"


def test_an_unknown_sage_is_refused_without_a_run(monkeypatch, tmp_path):
    runs = wire(monkeypatch, tmp_path)
    monkeypatch.setattr(listener, "exec_options_for", lambda spec, client: None)
    listener.handle_topic(Client([message(content="sage:oceans tell me")]), "archsage-agstudio1", "ask-me")
    assert [r[0] for r in runs if r[0] != "reply"] == []
    reply = [r[1] for r in runs if r[0] == "reply"][-1]
    assert reply.startswith("**[sage:oceans]**") and "sage:arxiv, sage:realworld" in reply


# --- an argue --------------------------------------------------------------------------


def test_two_sages_invited_in_one_post_keep_their_own_identities(monkeypatch, tmp_path):
    runs = wire(monkeypatch, tmp_path)
    client = Client([
        message(sender=FRONT, name="Front", content="[selfnote][argue] from front/front-a", id=1, topic="argue-x"),
        message(content="I want a self-running aquarium factory.", id=2, topic="argue-x"),
        message(sender=FRONT, name="Front", id=3, topic="argue-x",
                content="@**archsage** sage:arxiv trends? @**archsage** sage:realworld problems? @**archsage** and your view?"),
    ])
    listener.handle_mention(client, "argue", "argue-x")
    served = [(r[0], r[1]) for r in runs if r[0] in ("sage", "archsage")]
    assert served == [("sage", "arxiv"), ("sage", "realworld"), ("archsage", None)]
    prompts = {r[1]: r[2] for r in runs if r[0] == "sage"}
    assert "# arXiv guide" in prompts["arxiv"] and "# realworld guide" not in prompts["arxiv"]
    assert "# realworld guide" in prompts["realworld"] and "# arXiv guide" not in prompts["realworld"]
    assert "logical participant 'sage:arxiv'" in prompts["arxiv"]
    council = next(r[2] for r in runs if r[0] == "archsage")
    assert "sage:arxiv" in council and "sage:realworld" in council
    posts = [c[3] for c in client.calls if c[0] == "post"]
    assert posts[0] == "**[sage:arxiv]**\narxiv answers"
    assert posts[1] == "**[sage:realworld]**\nrealworld answers"
    assert posts[2] == "the council answers"
    assert posts[3] == "[selfnote][served] argue/argue-x 3"
    assert all(r[3] == {"invitation": 3} for r in runs if r[0] in ("sage", "archsage"))


def test_a_mention_outside_an_argue_is_left_alone(monkeypatch, tmp_path):
    runs = wire(monkeypatch, tmp_path)
    client = Client([message(sender=FRONT, name="Front", content="@**archsage** hi", topic="front-x")])
    listener.handle_mention(client, "front", "front-x")
    assert runs == [] and client.calls == []


def test_the_listener_is_the_skeleton_with_the_entrance_and_the_mention_route(monkeypatch):
    handed = {}
    monkeypatch.setattr(listener, "listener_main", lambda spec, routes, **kw: handed.update(spec=spec, routes=routes, **kw))
    listener.main()
    assert handed["spec"] is listener.SPEC and handed["routes"] == {}
    assert handed["entrance"] is listener.handle_topic and handed["on_mention"] is listener.handle_mention
    assert listener.SPEC.sweep_prefixes == ()  # only the own channel is owned
