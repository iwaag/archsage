# archsage

The knowledge council of the `agdev` realm: **one deployed agent, one Zulip
account, many logical sages**. archsage (the frontier model) designs the
knowledge and research a desire needs and can inspect every sage's tree;
each sage (the ordinary model) answers from the published knowledge tree of
one study, cites what it read, and says when the tree does not answer.

## Layout

```
agents.toml                 profiles: frontier (archsage), sonnet (every sage); roles: archsage, sage
agent/guides/archsage/      archsage's guide
agent/guides/sage/          the shared execution guide every sage runs with
sages/<name>/sage.toml      name, one line about the domain, the study repository ("" = none yet)
sages/<name>/guide.md       the sage's domain guide
sages/<name>/mainstudy/     ignored: the clone of the study's published knowledge (service/sync_knowledge.sh)
sages/<name>/tostudy/       ignored: the sage's study queue
src/archsage/               listener, roles, sages, the `archsage` and `sagetree` CLIs
```

A sage is nothing but the two files and the tree. Adding a domain is
`archsage sage add <name> --about "…" --guide-file guide.md [--study <url>]`
plus a re-post of the introduction; no listener and no account is added.

## Addressing

`@**archsage** sage:<name> …` in an argue, or `sage:<name> …` as the first
word of a post in the own channel, asks that sage; a bare mention or post
asks archsage. Every reply from a sage begins with `**[sage:<name>]**`. The
selector is parsed by code, never by a model, and a request for a sage
costs no archsage run.

## The boundary a sage runs in

A sage's run has one tool: `sagetree` (`Bash(sagetree:*)`), which lists,
reads, greps and finds inside the tree named by `SAGETREE_ROOT` and refuses
every path outside it; its one write is a note into the study queue
(`SAGETREE_QUEUE`). There is no Read/Glob/Grep tool in the grant, and the
working directory is the run's own workspace, not the tree.

**This is a bounded reader, not a sandbox.** Under claude_code a
`Bash(<name>:*)` grant admits a compound shell command, so a sage that
wants to read outside its tree can (`sagetree ls && cat …`); the
transcript shows it as a command that is not `sagetree`. What the boundary
does is make everything a sage is meant to read one command away and
nothing else easy, and keep the supplied context (the prompt names only
its own tree) honest. archsage's access is broader on purpose and is
listed in `agents.toml`: it reads every tree directly, asks sages, and
writes sage definitions under `sages/`.

## Running

```
uv sync
service/sync_knowledge.sh          # clone/refresh every sage's tree
uv run python -m archsage.intro    # publish the sages and the addressing syntax
service/listen.sh                  # or the launchd template in service/
uv run pytest -q
```
