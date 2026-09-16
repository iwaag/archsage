"""archsage's instance name and the spec the skeleton runs it by.

`archsage` is the agent; `archsage-agstudio1` is *this running instance of
it*. The name lives in `.local/instance.toml` (`instance.example.toml`
shows the shape) and `ARCHSAGE_INSTANCE_NAME` overrides it. The Zulip
account's display name — the name it is mentioned by — is `archsage`,
chosen at provisioning time; the roster block in the introduction says so.

One deployed agent, one Zulip account, many logical **sages**: each is a
directory under `sages/` with a `sage.toml`, a domain `guide.md` and the
clone of its study's published knowledge (`mainstudy/`). archsage owns all
of them and is the only thing that reads across them.
"""

from __future__ import annotations

from pathlib import Path

from agag.agent import AgentSpec
from agag.execopt import Option

ROOT = Path(__file__).resolve().parents[2]
SAGES_ROOT = ROOT / "sages"
#: The role that is archsage itself, and the shared role every sage runs.
ARCHSAGE_ROLE = "archsage"
SAGE_ROLE = "sage"
#: How a logical sage is addressed: `sage:<name>` right after the mention in
#: an argue, or as the first token of a post in this instance's own channel.
SELECTOR_KIND = "sage"
#: What can be asked of this instance: the council itself runs on the
#: frontier profile, a sage on the ordinary one. `frontier` is published so
#: a requester can ask for the council's judgement on a difficult question
#: in its own channel, and knows what it spends.
COVERS = "answers in my own channel and in argues"
DEFAULT_OPTION_DETAIL = (
    "anthropic",
    "my configured defaults — archsage on Claude Fable 5.1, each sage on Claude Sonnet 5, through claude_code",
)

SPEC = AgentSpec(
    "archsage", ROOT,
    exec_options=(Option("default", *DEFAULT_OPTION_DETAIL[:1], COVERS, DEFAULT_OPTION_DETAIL[1]),),
    exec_roles=(ARCHSAGE_ROLE, SAGE_ROLE),
)

__all__ = [
    "ARCHSAGE_ROLE", "COVERS", "DEFAULT_OPTION_DETAIL", "ROOT", "SAGES_ROOT", "SAGE_ROLE", "SELECTOR_KIND", "SPEC",
]
