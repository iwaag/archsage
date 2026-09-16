"""`sagetree`, the bounded reader: everything inside the tree is one command
away, every path outside it is refused, an empty tree says so, and the
study queue is the one thing it writes."""

from __future__ import annotations

import io
import subprocess

import pytest

from archsage import sagetree


def tree(tmp_path):
    root = tmp_path / "mainstudy"
    (root / "papers" / "2608.1").mkdir(parents=True)
    (root / "README.md").write_text("# index\n| 2608.1 | A paper |\n", encoding="utf-8")
    (root / "papers" / "2608.1" / "summary.md").write_text("Summary of a paper.\nIt is about agents.\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    return root


def run(monkeypatch, tmp_path, *argv, root=None, queue=None):
    monkeypatch.setenv(sagetree.ROOT_VARIABLE, str(root if root is not None else tmp_path / "mainstudy"))
    monkeypatch.setenv(sagetree.QUEUE_VARIABLE, str(queue if queue is not None else tmp_path / "tostudy"))
    out, err = io.StringIO(), io.StringIO()
    code = sagetree.run(list(argv), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_ls_cat_grep_and_find_stay_inside_the_tree(monkeypatch, tmp_path):
    tree(tmp_path)
    code, out, _ = run(monkeypatch, tmp_path, "ls")
    assert code == 0 and out.splitlines() == ["papers/", "README.md"]
    code, out, _ = run(monkeypatch, tmp_path, "cat", "papers/2608.1/summary.md")
    assert code == 0 and "     1\tSummary of a paper." in out
    code, out, _ = run(monkeypatch, tmp_path, "grep", "agents")
    assert code == 0 and out.strip() == "papers/2608.1/summary.md:2:It is about agents."
    code, out, _ = run(monkeypatch, tmp_path, "find", "papers/*/summary.md")
    assert code == 0 and out.strip() == "papers/2608.1/summary.md"


@pytest.mark.parametrize("argv", [("cat", "../outside.txt"), ("ls", ".."), ("grep", "secret", "../"), ("cat", "/etc/hosts")])
def test_a_path_outside_the_tree_is_refused(monkeypatch, tmp_path, argv):
    tree(tmp_path)
    code, out, err = run(monkeypatch, tmp_path, *argv)
    assert code == 1 and "outside this sage's tree" in err and "secret" not in out


def test_an_empty_tree_says_so_instead_of_failing(monkeypatch, tmp_path):
    (tmp_path / "mainstudy").mkdir()
    code, out, _ = run(monkeypatch, tmp_path, "ls")
    assert code == 0 and "empty" in out
    code, out, _ = run(monkeypatch, tmp_path, "revision")
    assert code == 0 and out.strip() == "empty"
    code, _, err = run(monkeypatch, tmp_path, "ls", root=tmp_path / "missing")
    assert code == 0  # a missing tree is an empty one


def test_no_root_variable_is_an_error_not_a_read_of_the_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv(sagetree.ROOT_VARIABLE, raising=False)
    out, err = io.StringIO(), io.StringIO()
    assert sagetree.run(["ls"], out=out, err=err) == 1 and "not set" in err.getvalue()


def test_the_queue_creates_then_appends_and_lists(monkeypatch, tmp_path):
    tree(tmp_path)
    code, out, _ = run(monkeypatch, tmp_path, "queue", "list")
    assert code == 0 and "empty" in out
    code, out, _ = run(monkeypatch, tmp_path, "queue", "add", "autodesign-2608.13560", "# AutoDesign\n\nasked once")
    assert code == 0 and out.strip() == "created autodesign-2608.13560.md"
    code, out, _ = run(monkeypatch, tmp_path, "queue", "add", "autodesign-2608.13560", "- asked again")
    assert code == 0 and out.strip() == "appended to autodesign-2608.13560.md"
    note = (tmp_path / "tostudy" / "autodesign-2608.13560.md").read_text(encoding="utf-8")
    assert note == "# AutoDesign\n\nasked once\n\n- asked again\n"
    code, out, _ = run(monkeypatch, tmp_path, "queue", "list")
    assert out.strip() == "autodesign-2608.13560: # AutoDesign"
    code, _, err = run(monkeypatch, tmp_path, "queue", "add", "../escape", "x")
    assert code == 1 and "not a note slug" in err


def test_revision_reads_git(monkeypatch, tmp_path):
    root = tree(tmp_path)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], check=True)
    code, out, _ = run(monkeypatch, tmp_path, "revision")
    assert code == 0 and len(out.strip()) >= 7 and out.strip() != "empty"
