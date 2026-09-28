"""`python -m archsage.trial <probe> --out <dir>` — one serving of archsage's own
channel for a fixture probe (`agent_guide` p2 ex1; p2 step 7's driver).

The serving is the listener's own `serve`, with the fixture board as the
client and every run's `agentchat` reading it; nothing is posted anywhere.
The sages' trees are this host's (`sages/`), read as they are. `--guides
<tree>` or `--guides-rev <commit>` serves with another `agent/guides` tree,
`--no-shared` without pyagag's shared sections; `--dry-run` writes the prompt
and runs no model. The outcome goes to `<out>/outcome.json` and `reply.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agag.fixture.board import ARCHSAGE
from agag.fixture.run import Trial, client, newest, probe_history, session_log, tool_calls, trial_parser
from agag.topics import TopicContext

#: This checkout, where `--guides-rev` is looked up.
ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    args = trial_parser("python -m archsage.trial", __doc__, "archsage").parse_args(argv)
    trial = Trial.start(args, ROOT)
    from . import listener, roles
    from .instance import ARCHSAGE_ROLE, SPEC

    if trial.guides is not None:
        roles.GUIDES = trial.guides
    probe = trial.probe
    context = TopicContext(client(trial.store), probe.channel, probe.topic, ARCHSAGE, "archsage",
                           history=probe_history(probe))
    with trial.session():
        result = listener.serve(context)
    workspace = newest(SPEC.topics_root / probe.channel / probe.topic, "*")
    cwd = workspace / ARCHSAGE_ROLE if workspace is not None else None
    calls = tool_calls(cwd / "transcript.jsonl") or tool_calls(session_log(cwd)) if cwd is not None else []
    return trial.finish(result.output or "", records=SPEC.records_root / ARCHSAGE_ROLE, role=ARCHSAGE_ROLE,
                        calls=calls)


if __name__ == "__main__":
    sys.exit(main())
