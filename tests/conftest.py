"""No test reaches the real definitions store or posts a real introduction."""

import pytest

from archsage import cli


@pytest.fixture(autouse=True)
def _no_store_no_intro(monkeypatch):
    done = {"persist": [], "intro": 0}
    monkeypatch.setattr(cli, "_persist", lambda message: done["persist"].append(message) or "abc123")

    def intro():
        done["intro"] += 1

    monkeypatch.setattr(cli, "_post_intro", intro)
    monkeypatch.setenv("AGAG_GITEA_URL", "")
    return done
