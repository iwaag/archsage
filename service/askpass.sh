#!/bin/sh
# GIT_ASKPASS for the definitions store (archsage.store): the username and
# the token come from the environment the store sets, never from argv.
case "$1" in
  *Username*) printf '%s\n' "$ARCHSAGE_GIT_USERNAME" ;;
  *Password*) cat "$ARCHSAGE_GIT_TOKEN_FILE" ;;
esac
