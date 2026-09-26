#!/bin/sh
# Refresh every sage's knowledge tree from its study repository (or one
# sage's, by name). archsage does the same with `archsage sage sync` after
# research is integrated; a sage never does: it only reads its tree.
set -eu
cd "$(dirname "$0")/.."
exec uv run archsage sage sync "$@"
