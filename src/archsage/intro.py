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
    """One line per sage: its selector, what it knows about, and the study it
    reads. Only what changes with a definition is rendered — the introduction
    is re-posted on define/update/attach/remove, not on `sage sync`, so a
    findings state printed here went stale the moment research landed
    (`agent_guide` p1: "no findings yet" after two accepted rounds, and a
    Front run that read it had nothing to look for). How far a study got is
    read where it lives: the study's channel and `agproject status`."""
    sages = load_sages()
    if not sages:
        return "- (no sages defined yet)"
    def state(sage) -> str:
        if not sage.study:
            return " *(no study attached yet)*"
        return f" *(study `{sage.project}`)*" if sage.project else ""

    return "\n".join(f"- `{sage.selector}` — {sage.about}{state(sage)}" for sage in sages)


def main() -> str:
    log_pool_diagnostics(SPEC)
    client = ZulipClient.from_env(SPEC.zulip_env)
    roster = roster_for(SPEC, client)
    return post_intro(client, instance=SPEC.instance_name(), intro_path=SPEC.intro_path, root=SPEC.root,
                      roster=roster, options=SPEC.published_options(roster.bot), extra={"sages": sages_lines()})


if __name__ == "__main__":
    main()
