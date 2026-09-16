#!/bin/sh
# Refresh every sage's knowledge tree from its study repository (or one
# sage's, by name). Run by an operator, never by a sage: a tree is a study's
# publication, and the sages only read it.
set -eu
cd "$(dirname "$0")/.."
exec uv run archsage sage sync "$@"
