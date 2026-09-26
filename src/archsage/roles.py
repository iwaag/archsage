"""Running archsage and running a sage: the prompts, the bounds, the records.

Two runs, and what tells them apart:

- **A sage run** (`run_sage`) is the shared `sage` role over one sage: the
  sage's domain guide and the shared sage guide, `sagetree` pointed at its
  tree and its queue through the environment, no other file tool. Its
  record says which sage spoke (`speaker`), what its tree was at
  (`knowledge_revision`), and what post it was answering.
- **An archsage run** (`run_archsage`) is the frontier `archsage` role with
  the sages root in its prompt and its own tools: it reads every tree
  directly, asks a sage in-process with `archsage ask`, and defines a new
  sage with `archsage sage add`. Its record names every sage's revision.

A reply is posted **with the speaker's header** by the posting layer
(`agag.argue.with_speaker`), never by the model: the header is what says,
from one Zulip account, who is talking.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Mapping

from agag.agent import resolve_spec_role, run_role
from agag.execopt import Selection
from agag.topics import guide as read_guide, next_record_path, prompt_with_guide

from .instance import ARCHSAGE_ROLE, ROOT, SAGES_ROOT, SAGE_ROLE, SPEC
from .sagetree import QUEUE_VARIABLE, ROOT_VARIABLE
from .sages import Sage, load_sages

ARCHSAGE_TIMEOUT_SECONDS = 900
SAGE_TIMEOUT_SECONDS = 600
GUIDES = ROOT / "agent" / "guides"

__all__ = [
    "ARCHSAGE_TIMEOUT_SECONDS",
    "GUIDES",
    "RoleError",
    "SAGE_TIMEOUT_SECONDS",
    "archsage_context",
    "run_archsage",
    "run_sage",
    "sage_context",
    "sages_placement",
]


class RoleError(RuntimeError):
    """One run could not complete."""


def _tree_state(sage: Sage) -> str:
    if not sage.has_knowledge():
        return "with an EMPTY tree (no study attached, or nothing synced yet)"
    found = sage.findings()
    return (f"at revision {sage.revision()}, {found} knowledge file(s)" if found
            else f"at revision {sage.revision()} with NO FINDINGS yet (only the study's plan, READMEs and indexes)")


def sages_placement(sages: list[Sage] | None = None) -> str:
    """One paragraph naming every sage, its domain, its study, its tree and its queue."""
    sages = load_sages() if sages is None else sages
    if not sages:
        return f"There are no sages yet. New ones are defined under {SAGES_ROOT} (`archsage sage add`)."
    lines = [f"The sages live under {SAGES_ROOT}; each is a directory holding sage.toml, guide.md, mainstudy/ "
             "(its knowledge tree) and tostudy/ (its study queue):"]
    for sage in sages:
        lines.append(f"- {sage.selector}: {sage.about} — {sage.describe_source()}; tree {sage.tree} "
                     f"{_tree_state(sage)}; {len(sage.queued())} queued question(s)")
    return "\n".join(lines)


def sage_context(sage: Sage) -> str:
    """What one sage is told about itself: the shared sage guide, its domain
    guide, and the state of its tree."""
    shared = read_guide(GUIDES, SAGE_ROLE, "guide.md")
    if not sage.has_knowledge():
        state = ("Your knowledge tree is EMPTY: no study is attached to you yet, or nothing has been synced. Say "
                 "so, explain what a study would have to gather, and queue what was asked; do not invent findings.")
    elif not sage.findings():
        state = (f"Your knowledge tree is at revision {sage.revision()} but holds NO FINDINGS yet — only the study's "
                 "plan, READMEs and indexes. Say so, say what the plan intends to find, and queue what was asked; "
                 "do not present the plan as findings.")
    else:
        state = f"Your knowledge tree is at revision {sage.revision()} ({sage.describe_source()})."
    return f"{shared}\n\n# Your domain\n\n{sage.guide()}\n\n{state}"


def archsage_context() -> str:
    return prompt_with_guide([sages_placement()], read_guide(GUIDES, ARCHSAGE_ROLE, "guide.md"))


def _sage_environment(sage: Sage) -> dict[str, str]:
    return {ROOT_VARIABLE: str(sage.tree), QUEUE_VARIABLE: str(sage.queue)}


def run_sage(sage: Sage, prompt: str, cwd: Path, *, extra_meta: Mapping[str, object] | None = None,
             selection: Selection | None = None, timeout: float = SAGE_TIMEOUT_SECONDS) -> str:
    """One run of the shared `sage` role as `sage`, bounded to its tree."""
    agent = resolve_spec_role(SPEC, SAGE_ROLE, profile_override=SPEC.profile_for(selection, SAGE_ROLE))
    agent = replace(agent, environment={**agent.environment, **_sage_environment(sage)})
    meta = {"speaker": sage.selector, "sage": sage.name, "knowledge_revision": sage.revision(), **(extra_meta or {})}
    output, _, exit_code = run_role(
        SPEC, SAGE_ROLE, prompt, cwd=cwd, timeout=timeout, agent=agent, selection=selection,
        record=next_record_path(SPEC.records_root / SAGE_ROLE), transcript=cwd / "transcript.jsonl",
        stream=True, extra_meta=meta,
    )
    if exit_code != 0:
        raise RoleError(f"{sage.selector} run exited {exit_code}: {output.strip()[:500]}")
    return output.strip()


def run_archsage(prompt: str, cwd: Path, *, home: tuple[str, str] | None = None,
                 extra_meta: Mapping[str, object] | None = None, selection: Selection | None = None,
                 timeout: float = ARCHSAGE_TIMEOUT_SECONDS) -> str:
    """One run of the frontier `archsage` role."""
    meta = {"speaker": "archsage", "knowledge_revisions": {s.name: s.revision() for s in load_sages()},
            **(extra_meta or {})}
    output, _, exit_code = run_role(
        SPEC, ARCHSAGE_ROLE, prompt, cwd=cwd, timeout=timeout, home=home, selection=selection,
        record=next_record_path(SPEC.records_root / ARCHSAGE_ROLE), transcript=cwd / "transcript.jsonl",
        stream=True, extra_meta=meta,
    )
    if exit_code != 0:
        raise RoleError(f"archsage run exited {exit_code}: {output.strip()[:500]}")
    return output.strip()
