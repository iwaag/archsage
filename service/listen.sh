#!/bin/sh
# Run the archsage Zulip listener (credentials: .local/zulip.env).
set -eu
cd "$(dirname "$0")/.."
mkdir -p .local/out
exec uv run python -m archsage.listener
