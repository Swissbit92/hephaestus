"""Tests for the second-brain vault graph.

`review` used to answer orphans / broken links / stale / tag drift by reading the whole
vault, which costs tokens proportional to its size, cannot be tested, and answers
slightly differently each run — so a vault could not be trended, which is the only reason
to run a health report twice.

These pin the cases that make the counting non-trivial, each drawn from how Obsidian
actually behaves rather than from how wikilinks look at first glance:

- a link may carry an alias, a heading or a block ref, and may be an embed;
- a `[[link]]` inside a code fence is an example in documentation, not a link;
- a link resolves by note *name*, not only by path, so a note in a folder still resolves;
- the controlled-vocabulary file is a declaration and must not be counted as a note;
- "no notes here" and "a clean vault" must never share an exit code.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import vault_graph as vg

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (REPO_ROOT / "plugins" / "second-brain" / "skills" / "second-brain"
          / "scripts" / "vault_graph.py")


def _w(root: Path, rel: str, content: str = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


# --------------------------------------------------------------------------- link forms
def test_alias_heading_block_and_embed_links_all_resolve(tmp_path):
    """Obsidian link syntax carries four decorations; keying on the raw text inside the
    brackets would report every decorated link as broken."""
    _w(tmp_path, "target.md", "# Target\n")
    _w(tmp_path, "source.md",
       "[[target]] [[target|an alias]] [[target#Heading]] [[target#^block42]] ![[target]]\n")
    data = vg.scan(tmp_path)
    assert data["broken_links"] == []
    assert data["notes"]["target.md"]["inbound"] == ["source.md"] * 5


def test_links_inside_code_are_not_links(tmp_path):
    """A skill documenting `[[wikilink]]` syntax would otherwise generate broken links
    for every example it shows."""
    _w(tmp_path, "a.md", "prose\n\n```md\n[[not-a-real-note]]\n```\n\nand `[[also-not]]`\n")
    data = vg.scan(tmp_path)
    assert data["broken_links"] == []


def test_broken_link_is_reported_with_its_source(tmp_path):
    _w(tmp_path, "a.md", "see [[nowhere]]\n")
    data = vg.scan(tmp_path)
    assert data["broken_links"] == [{"from": "a.md", "target": "nowhere"}]


def test_link_resolves_by_note_name_across_folders(tmp_path):
    """Obsidian resolves by name, not by path — a note in Notes/ is reachable as
    [[existing]] from anywhere."""
    _w(tmp_path, "Notes/existing.md", "# Existing\n")
    _w(tmp_path, "Inbox/new.md", "refers to [[existing]]\n")
    data = vg.scan(tmp_path)
    assert data["broken_links"] == []
    assert data["notes"]["Notes/existing.md"]["inbound"] == ["Inbox/new.md"]


def test_a_note_linking_only_to_itself_is_not_its_own_backlink(tmp_path):
    _w(tmp_path, "a.md", "see [[a]]\n")
    data = vg.scan(tmp_path)
    assert data["notes"]["a.md"]["inbound"] == []


# --------------------------------------------------------------------------- orphans
def test_orphan_needs_neither_inbound_nor_outbound(tmp_path):
    _w(tmp_path, "island.md", "alone\n")
    _w(tmp_path, "hub.md", "points at [[leaf]]\n")
    _w(tmp_path, "leaf.md", "pointed at\n")
    data = vg.scan(tmp_path)
    assert data["orphans"] == ["island.md"], "hub has outbound, leaf has inbound"


# --------------------------------------------------------------------------- staleness
def test_stale_uses_the_threshold_and_sorts_worst_first(tmp_path):
    old, older = _w(tmp_path, "old.md", "x"), _w(tmp_path, "older.md", "x")
    now = time.time()
    import os
    os.utime(old, (now - 200 * 86400, now - 200 * 86400))
    os.utime(older, (now - 400 * 86400, now - 400 * 86400))
    _w(tmp_path, "fresh.md", "x")
    data = vg.scan(tmp_path, stale_days=180, now=now)
    assert [s["path"] for s in data["stale"]] == ["older.md", "old.md"]


# --------------------------------------------------------------------------- tags
def test_case_separator_and_plural_variants_are_paired(tmp_path):
    _w(tmp_path, "a.md", "#machine-learning\n")
    _w(tmp_path, "b.md", "#machine_learning\n")
    _w(tmp_path, "c.md", "#Books\n")
    _w(tmp_path, "d.md", "#book\n")
    pairs = {(v["a"], v["b"]) for v in vg.scan(tmp_path)["tag_variants"]}
    assert ("machine-learning", "machine_learning") in pairs
    assert ("book", "books") in pairs


def test_semantically_related_tags_are_deliberately_not_paired(tmp_path):
    """#ml and #machine-learning share no substring. Claiming to detect that would be a
    promise the string metric cannot keep, so the report says so instead."""
    _w(tmp_path, "a.md", "#ml\n")
    _w(tmp_path, "b.md", "#machine-learning\n")
    assert vg.scan(tmp_path)["tag_variants"] == []


def test_headings_and_numbers_are_not_tags(tmp_path):
    _w(tmp_path, "a.md", "# Heading\n\nissue #42 and #real\n")
    assert set(vg.scan(tmp_path)["tags"]) == {"real"}


def test_frontmatter_tags_count_in_both_list_forms(tmp_path):
    _w(tmp_path, "a.md", "---\ntags: [alpha, beta]\n---\n\nbody\n")
    _w(tmp_path, "b.md", "---\ntags:\n  - gamma\n  - delta\n---\n\nbody\n")
    tags = set(vg.scan(tmp_path)["tags"])
    assert {"alpha", "beta", "gamma", "delta"} <= tags


def test_vocabulary_file_is_not_a_note_and_its_tags_are_not_uses(tmp_path):
    """_meta/tags.md declares the approved tags. Counted as a note it is a permanent
    orphan, and its declarations turn every approved tag into a phantom 'used once'."""
    _w(tmp_path, "_meta/tags.md", "#idea\n#reference\n#meeting\n")
    _w(tmp_path, "a.md", "#idea\n")
    data = vg.scan(tmp_path)
    assert "_meta/tags.md" not in data["orphans"]
    assert data["note_count"] == 1
    assert data["tag_singletons"] == ["idea"], "only real uses count"


def test_uncontrolled_tags_are_only_reported_when_a_vocabulary_exists(tmp_path):
    _w(tmp_path, "a.md", "#whatever\n")
    assert vg.scan(tmp_path)["uncontrolled_tags"] == []
    _w(tmp_path, "_meta/tags.md", "#idea\n")
    assert vg.scan(tmp_path)["uncontrolled_tags"] == ["whatever"]


# --------------------------------------------------------------------------- determinism
def test_two_scans_of_one_vault_agree_exactly(tmp_path):
    """The property the whole script exists for: a report you can trend."""
    _w(tmp_path, "a.md", "#t links [[b]]\n")
    _w(tmp_path, "b.md", "#t\n")
    _w(tmp_path, "c.md", "orphan\n")
    now = time.time()
    first = vg.scan(tmp_path, now=now)
    second = vg.scan(tmp_path, now=now)
    assert first == second


# --------------------------------------------------------------------------- CLI
def test_empty_vault_is_exit_2_not_a_clean_bill_of_health(tmp_path):
    p = _run(str(tmp_path))
    assert p.returncode == 2
    assert "cannot determine" in p.stderr


def test_missing_vault_is_exit_2():
    p = _run("definitely/not/a/vault")
    assert p.returncode == 2


def test_cli_json_omits_the_per_note_detail(tmp_path):
    _w(tmp_path, "a.md", "[[b]]\n")
    _w(tmp_path, "b.md", "x\n")
    p = _run(str(tmp_path), "--json")
    assert p.returncode == 0
    data = json.loads(p.stdout)
    assert "notes" not in data, "per-note link lists are far too verbose for a report"
    assert data["note_count"] == 2


def test_cli_report_names_the_limit_of_the_tag_check(tmp_path):
    _w(tmp_path, "a.md", "#x\n")
    p = _run(str(tmp_path))
    assert p.returncode == 0
    assert "not detectable from spelling" in p.stdout
