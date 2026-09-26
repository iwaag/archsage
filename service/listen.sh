#!/bin/sh
# Run the archsage Zulip listener (credentials: .local/zulip.env).
set -eu
cd "$(dirname "$0")/.."
mkdir -p .local/out
# Machine-specific environment, ignored: AGAG_PROVISIONER_ENV names the
# realm-admin credential archsage opens study and routine channels with
# (`agproject`, `agroutine`); runs inherit it.
if [ -f .local/listener.env ]; then set -a; . ./.local/listener.env; set +a; fi
exec uv run python -m archsage.listener
