"""A sage and its study (sage p2 step 3).

Pinned: an existing sage is attached to a study and its tree synced at
once; a study with only its plan and indexes reads as "no findings yet",
and a finding pushed later is picked up by a refresh with the revision
named; reattaching to another repository replaces the tree instead of
pulling the old one; a failed refresh leaves the tree where it was; `main`
is resolved from the study's internal repository; a queued question is
removed only when files in the refreshed tree answer it; definitions are
committed and pushed to the store and restorable from it.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess

import pytest

from archsage import cli, queue, sages, store


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def study_repo(tmp_path, name, files):
    work = tmp_path / f"{name}-work"
    bare = tmp_path / f"{name}.git"
    git("init", "--bare", "-b", "main", str(bare))
    git("clone", "-q", str(bare), str(work))
    for path, text in files.items():
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_text(text, encoding="utf-8")
    commit(work, "layout")
    return bare, work


def commit(work, message):
    git("add", "-A", cwd=work)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message, cwd=work)
    git("push", "-q", "origin", "HEAD:main", cwd=work)


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / "sages"
    monkeypatch.setattr(sages, "SAGES_ROOT", root)
    monkeypatch.setattr(sages, "REPLACED_TREES", tmp_path / "replaced")
    return root


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.run(argv, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


SCAFFOLD = {"README.md": "# aqua", "RESEARCHPLAN.md": "# plan", "methods/README.md": "# methods",
            "reports/INDEX.md": "| date | subject |"}


def test_an_existing_sage_is_attached_synced_and_refreshed(tmp_path, root, _no_store_no_intro):
    sages.add_sage("aqua", "aquaculture", "# guide", root=root)
    bare, work = study_repo(tmp_path, "aqua", SCAFFOLD)
    code, out, err = run(["sage", "attach", "aqua", "--project", "aqua", "--repository", str(bare)])
    assert code == 0, err
    assert "attached sage:aqua to study `aqua`, its internal knowledge repository (main)" in out
    assert "empty →" in out and "no findings yet" in out
    assert _no_store_no_intro["persist"] == ["Attach sage:aqua"] and _no_store_no_intro["intro"] == 1
    sage = sages.sage_named("aqua")
    assert (sage.project, sage.source, sage.study) == ("aqua", "main", str(bare))
    (work / "reports" / "2026-09-26-feeds.md").write_text("# findings", encoding="utf-8")
    commit(work, "first finding")
    before = sage.revision()
    result = sages.sync_sage(sage)
    assert result.before == before and result.revision == git("rev-parse", "--short=12", "HEAD", cwd=work)
    assert result.findings == 1 and "1 knowledge file(s)" in result.line()


def test_reattaching_replaces_the_tree_and_a_failed_refresh_keeps_it(tmp_path, root):
    old, _ = study_repo(tmp_path, "old", {"old.md": "old knowledge"})
    new, _ = study_repo(tmp_path, "new", {"new.md": "new knowledge"})
    sage = sages.add_sage("aqua", "aquaculture", "# guide", study=str(old), root=root)
    sages.sync_sage(sage)
    sage = sages.attach_study("aqua", project="aqua2", source="publish", repository=str(new))
    result = sages.sync_sage(sage)
    assert "replaced the tree from" in result.line() and (sage.tree / "new.md").exists()
    assert not (sage.tree / "old.md").exists() and any((tmp_path / "replaced").iterdir())
    kept = sage.revision()
    shutil.rmtree(new)
    with pytest.raises(sages.SageError, match=f"the tree stays at {kept}"):
        sages.sync_sage(sage)
    assert sage.revision() == kept


def test_main_is_resolved_from_the_study_and_publish_needs_a_repository(tmp_path, root, monkeypatch):
    sages.add_sage("aqua", "aquaculture", "# guide", root=root)
    import agag.project

    monkeypatch.setattr(agag.project, "gitea_head", lambda slug, **_: {"exists": False, "repository": "r"})
    with pytest.raises(sages.SageError, match="agproject status aqua"):
        sages.attach_study("aqua", project="aqua")
    monkeypatch.setattr(agag.project, "gitea_head",
                        lambda slug, **_: {"exists": True, "repository": f"http://g/autodev/{slug}.git"})
    assert sages.attach_study("aqua", project="aqua").study == "http://g/autodev/aqua.git"
    with pytest.raises(sages.SageError, match="--repository"):
        sages.attach_study("aqua", project="aqua", source="publish")


def test_a_queued_question_goes_only_when_the_refreshed_tree_answers_it(tmp_path, root):
    bare, work = study_repo(tmp_path, "aqua", SCAFFOLD)
    sage = sages.add_sage("aqua", "aquaculture", "# guide", study=str(bare), root=root)
    sages.sync_sage(sage)
    (sage.queue / "feeds.md").write_text("Which feeds are cheapest?", encoding="utf-8")
    log = tmp_path / "resolved.jsonl"
    with pytest.raises(sages.SageError, match="keep the note"):
        queue.resolve_note(sage, "feeds", ["reports/feeds.md"], log=log)
    with pytest.raises(sages.SageError):
        queue.resolve_note(sage, "feeds", ["../../etc/passwd"], log=log)
    (work / "reports" / "feeds.md").write_text("# feeds", encoding="utf-8")
    commit(work, "feeds")
    sages.sync_sage(sage)
    record = queue.resolve_note(sage, "feeds", ["reports/feeds.md"], log=log)
    assert not (sage.queue / "feeds.md").exists() and record["revision"] == sage.revision()
    assert json.loads(log.read_text().splitlines()[0])["text"] == "Which feeds are cheapest?"


def test_definitions_are_pushed_to_the_store_and_restored_from_it(tmp_path, root, monkeypatch):
    bare = tmp_path / "store.git"
    git("init", "--bare", "-b", "main", str(bare))
    git("clone", "-q", str(bare), str(root))
    monkeypatch.setattr(store, "CONFIG", tmp_path / "store.toml")
    (tmp_path / "store.toml").write_text(f'url = "{bare}"\nauthor = "archsage <a@b>"\n', encoding="utf-8")
    sages.add_sage("aqua", "aquaculture", "# guide", root=root)
    (root / "aqua" / "mainstudy").mkdir()
    (root / "aqua" / "mainstudy" / "x.md").write_text("tree", encoding="utf-8")
    git("-c", "user.name=a", "-c", "user.email=a@b", "commit", "-q", "--allow-empty", "-m", "init", cwd=root)
    git("push", "-q", "-u", "origin", "HEAD:main", cwd=root)
    first = store.persist("Define sage:aqua", root=root)
    assert first != "unchanged" and store.persist("again", root=root) == "unchanged"
    files = git("ls-tree", "-r", "--name-only", "main", cwd=bare)
    assert "aqua/sage.toml" in files and "aqua/guide.md" in files and "mainstudy" not in files
    restored = tmp_path / "restored"
    monkeypatch.setattr(sages, "SAGES_ROOT", restored)
    assert "restored" in store.restore()
    assert sages.sage_named("aqua").about == "aquaculture"
