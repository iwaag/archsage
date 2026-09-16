"""Sages as directories: found by their config, added with a config and a
guide and nothing more, an empty tree a valid state; and the roles' prompts
give each sage its own context while archsage sees all of them."""

from __future__ import annotations

import pytest

from archsage import roles, sages


def two_sages(tmp_path, monkeypatch):
    root = tmp_path / "sages"
    a = sages.add_sage("arxiv", "arXiv papers", "# arXiv\nRead the README table first.", study="https://example/a.git", root=root)
    (a.tree / "papers").mkdir(parents=True)
    (a.tree / "README.md").write_text("papers index", encoding="utf-8")
    b = sages.add_sage("realworld", "public institutional sources", "# realworld\nSources and reports.", root=root)
    monkeypatch.setattr(sages, "SAGES_ROOT", root)
    return root, a, b


def test_sages_are_found_by_name_with_their_selectors(tmp_path, monkeypatch):
    root, a, b = two_sages(tmp_path, monkeypatch)
    assert [s.name for s in sages.load_sages()] == ["arxiv", "realworld"]
    assert sages.selectors() == ["sage:arxiv", "sage:realworld"]
    assert sages.sage_named("realworld").about == "public institutional sources"
    assert sages.sage_named("nobody") is None
    assert a.has_knowledge() and not b.has_knowledge()
    assert b.revision() == "empty" and a.revision() == "unavailable"  # a tree without git
    assert (a.root / "sage.toml").read_text(encoding="utf-8") == (
        'name = "arxiv"\nabout = "arXiv papers"\nstudy = "https://example/a.git"\n')


@pytest.mark.parametrize("name", ["Arxiv", "a b", "", "1x"])
def test_a_sage_name_is_a_selector_name(tmp_path, name):
    with pytest.raises(sages.SageError):
        sages.add_sage(name, "about", "guide", root=tmp_path / "s")


def test_a_second_definition_of_a_sage_is_refused(tmp_path):
    sages.add_sage("arxiv", "about", "guide", root=tmp_path / "s")
    with pytest.raises(sages.SageError):
        sages.add_sage("arxiv", "about again", "guide", root=tmp_path / "s")
    with pytest.raises(sages.SageError):
        sages.add_sage("empty", "", "guide", root=tmp_path / "s")


def test_each_sage_is_told_its_own_domain_and_an_empty_tree_is_named(tmp_path, monkeypatch):
    root, a, b = two_sages(tmp_path, monkeypatch)
    context_a = roles.sage_context(a)
    context_b = roles.sage_context(b)
    assert "Read the README table first." in context_a and "Sources and reports." not in context_a
    assert "Sources and reports." in context_b and "README table" not in context_b
    assert "EMPTY" in context_b and "EMPTY" not in context_a
    assert "sagetree" in context_a  # the shared execution guide


def test_archsage_sees_every_tree(tmp_path, monkeypatch):
    root, a, b = two_sages(tmp_path, monkeypatch)
    placement = roles.sages_placement()
    assert str(a.tree) in placement and str(b.tree) in placement
    assert "sage:arxiv" in placement and "sage:realworld" in placement and "EMPTY tree" in placement


def test_a_sage_run_is_bounded_to_its_tree_and_records_who_spoke(tmp_path, monkeypatch):
    root, a, b = two_sages(tmp_path, monkeypatch)
    seen = {}

    def run_role(spec, role, prompt, *, cwd, timeout, agent=None, extra_meta=None, **kw):
        seen.update(role=role, env=dict(agent.environment), meta=dict(extra_meta or {}))
        return "from the tree", {}, 0

    monkeypatch.setattr(roles, "run_role", run_role)
    assert roles.run_sage(b, "PROMPT", tmp_path / "ws", extra_meta={"invitation": 5}) == "from the tree"
    assert seen["role"] == "sage"
    assert seen["env"]["SAGETREE_ROOT"] == str(b.tree) and seen["env"]["SAGETREE_QUEUE"] == str(b.queue)
    assert seen["meta"] == {"speaker": "sage:realworld", "sage": "realworld", "knowledge_revision": "empty", "invitation": 5}


def test_an_archsage_run_records_every_tree_s_revision(tmp_path, monkeypatch):
    root, a, b = two_sages(tmp_path, monkeypatch)
    seen = {}

    def run_role(spec, role, prompt, *, cwd, timeout, extra_meta=None, **kw):
        seen.update(role=role, meta=dict(extra_meta or {}))
        return "council says", {}, 0

    monkeypatch.setattr(roles, "run_role", run_role)
    assert roles.run_archsage("PROMPT", tmp_path / "ws") == "council says"
    assert seen["role"] == "archsage"
    assert seen["meta"]["speaker"] == "archsage"
    assert seen["meta"]["knowledge_revisions"] == {"arxiv": "unavailable", "realworld": "empty"}
