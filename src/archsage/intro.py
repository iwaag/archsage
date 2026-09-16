"""`python -m archsage.intro`: post params/intro.md to #agents as this instance.

The list of sages is what only the running instance knows, so it is
rendered here into the `{sages}` placeholder — the published names and the
addressing syntax are how Front discovers and uses them.
"""

from __future__ import annotations

from agag.agent import log_pool_diagnostics, roster_for
from agag.intro import post_intro
from agag.zulip import ZulipClient

from .instance import SPEC
from .sages import load_sages


def sages_lines() -> str:
    sages = load_sages()
    if not sages:
        return "- (no sages defined yet)"
    return "\n".join(
        f"- `{sage.selector}` — {sage.about}" + ("" if sage.has_knowledge() else " *(empty tree: its study has published nothing yet)*")
        for sage in sages
    )


def main() -> str:
    log_pool_diagnostics(SPEC)
    client = ZulipClient.from_env(SPEC.zulip_env)
    roster = roster_for(SPEC, client)
    return post_intro(client, instance=SPEC.instance_name(), intro_path=SPEC.intro_path, root=SPEC.root,
                      roster=roster, options=SPEC.published_options(roster.bot), extra={"sages": sages_lines()})


if __name__ == "__main__":
    main()
