"""The `archsage` CLI: a second domain is one command and no listener;
`ask` runs a sage in-process and prints its answer under its header."""

from __future__ import annotations

import io
from dataclasses import replace

from archsage import cli, roles, sages


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.run(argv, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_add_then_list_shows_the_new_domain_with_an_empty_tree(tmp_path, monkeypatch):
    root = tmp_path / "sages"
    monkeypatch.setattr(sages, "SAGES_ROOT", root)
    guide = tmp_path / "guide.md"
    guide.write_text("# Aquaculture\nRead sources/ first.\n", encoding="utf-8")
    code, out, _ = run(["sage", "add", "aquaculture", "--about", "aquaculture and closed-loop food systems", "--guide-file", str(guide)])
    assert code == 0 and "defined sage:aquaculture" in out and "no study yet" in out
    assert "definitions store: abc123" in out and "introduction re-posted" in out
    assert (root / "aquaculture" / "guide.md").read_text(encoding="utf-8").startswith("# Aquaculture")
    code, out, _ = run(["sage", "list"])
    assert code == 0 and out.strip() == ("sage:aquaculture: aquaculture and closed-loop food systems "
                                         "[empty tree; 0 queued] — no study attached")
    code, _, err = run(["sage", "add", "aquaculture", "--about", "again", "--guide", "x"])
    assert code == 1 and "already exists" in err


def test_ask_runs_the_named_sage_and_prints_its_header(tmp_path, monkeypatch):
    root = tmp_path / "sages"
    sages.add_sage("arxiv", "arXiv papers", "# arXiv guide", root=root)
    monkeypatch.setattr(sages, "SAGES_ROOT", root)
    monkeypatch.setattr(cli, "SPEC", replace(cli.SPEC, root=tmp_path))
    seen = {}

    def run_sage(sage, prompt, cwd, *, extra_meta=None, **kw):
        seen.update(sage=sage.name, prompt=prompt, meta=extra_meta)
        return "2608.1 is the one"

    monkeypatch.setattr(cli, "run_sage", run_sage)
    code, out, _ = run(["ask", "arxiv", "which paper covers harness optimization?"])
    assert code == 0 and out.strip() == "**[sage:arxiv]**\n2608.1 is the one"
    assert seen["sage"] == "arxiv" and "which paper covers harness optimization?" in seen["prompt"]
    assert "# arXiv guide" in seen["prompt"] and seen["meta"] == {"asked_by": "archsage"}
    code, _, err = run(["ask", "nobody", "hello"])
    assert code == 1 and "no sage named" in err
