"""Seam linter: generic (Tier A) plugins must contain no domain (Tier B/C) content.

The #1 failure mode of a consolidated marketplace (ADR-001) is domain judgment leaking
into a generic craft plugin. This test enforces the plugin-boundary seam: anything in a
generic plugin must be reusable by anyone, with zero ecosystem/domain specifics.
"""
import re
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS = REPO_ROOT / "plugins"

# Tier B domain plugins are exempt — they are SUPPOSED to carry domain content.
DOMAIN_PLUGINS = {"quant-factory", "kucoin-safety-gate"}

# Unambiguous ecosystem/domain tokens that must never appear in a generic plugin.
DOMAIN_TOKENS = (
    "kucoin", "eeva", "nephilim", "crypto_research", "btc_price_tracker",
    "strategy_signals", "portfolio_deployed", "cmii",
)

TEXT_EXTS = {".md", ".py", ".json", ".yaml", ".yml", ".sh", ".txt"}
PRUNE = {".venv", "venv", "__pycache__", ".git", "node_modules"}

# --- Document-name leakage -------------------------------------------------------
# DOMAIN_TOKENS above catches project *nouns* (kucoin, nephilim). It cannot catch a
# specific *document* name — LORE_DEEPDIVE_PLAN, OAUTH_IMPLEMENTATION_PLAN — which
# names no project yet is just as repo-specific. That gap was real: add_frontmatter.py
# hardcoded five such filenames from one repo, so the rule silently did nothing for
# every other repo and went stale the moment those files were archived.
#
# Rule: a generic plugin may match documents by KIND (a suffix: _REVIEW, _PLAN) or by
# a name the CMS standard itself defines. It may not hardcode a particular repo's
# document titles. Suffix patterns are exempt by construction — the token regex needs a
# word boundary before the first segment, which a leading "_" denies.
DOC_NAME_TOKEN = r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"

# Names the standard defines, or that are universal across repos rather than owned by one.
STANDARD_DOC_NAMES = {
    # CMS skeleton
    "LESSONS_LEARNED", "THREAT_LEVEL", "ARCHITECTURE", "ROADMAP", "CHANGELOG",
    "SECURITY", "CONTRIBUTING", "README", "CLAUDE", "INVARIANTS", "LICENSE",
    # Generic document kinds used as illustrative examples in prose/allowlists
    "BUSINESS_PLAN", "MIGRATION_PLAN", "PHASE2_PLAN",
}


def _generic_plugin_dirs():
    if not PLUGINS.is_dir():
        return []
    return [p for p in sorted(PLUGINS.iterdir())
            if p.is_dir() and p.name not in DOMAIN_PLUGINS]


def _text_files(root):
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXTS:
            continue
        if any(part in PRUNE for part in p.parts):
            continue
        yield p


@pytest.mark.parametrize("plugin", _generic_plugin_dirs(), ids=lambda p: p.name)
def test_generic_plugin_has_no_domain_content(plugin):
    hits = []
    for f in _text_files(plugin):
        try:
            text = f.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        for tok in DOMAIN_TOKENS:
            if tok in text:
                hits.append(f"{f.relative_to(REPO_ROOT)}: '{tok}'")
    assert not hits, (
        f"Domain content leaked into generic plugin '{plugin.name}' "
        f"(seam violation, ADR-001):\n  " + "\n  ".join(hits)
        + "\nMove domain-specific logic to a Tier-B domain plugin or a per-repo .claude/."
    )


def _doc_name_hits(text):
    """Doc names a file hardcodes: `NAME.md`, plus alternatives inside a `(...)\\.md` regex.

    Deliberately narrow. Only tokens that ARE a document name are considered — a
    constant that merely sits near a `.md` line (REPO_ROOT, FRONTMATTER_REQUIRED) is
    not a doc name and must not trip this.
    """
    found = set(re.findall(rf"\b({DOC_NAME_TOKEN})(?=\.md\b)", text))
    # Regex alternation groups terminated by `\.md` — the add_frontmatter.py shape.
    # Adjacent string literals are concatenated by the parser, so scan the whole text.
    for group in re.findall(r"\(([^()]*?)\)\\\.md", text, re.DOTALL):
        found.update(re.findall(rf"\b({DOC_NAME_TOKEN})\b", group))
    return found


@pytest.mark.parametrize("plugin", _generic_plugin_dirs(), ids=lambda p: p.name)
def test_generic_plugin_hardcodes_no_specific_doc_names(plugin):
    hits = []
    for f in _text_files(plugin):
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name in sorted(_doc_name_hits(text)):
            if name not in STANDARD_DOC_NAMES:
                hits.append(f"{f.relative_to(REPO_ROOT)}: '{name}'")
    assert not hits, (
        f"Generic plugin '{plugin.name}' hardcodes a specific repo's document name "
        f"(seam violation, ADR-001):\n  " + "\n  ".join(hits)
        + "\nMatch documents by KIND — a suffix such as _REVIEW or _PLAN — or add the "
          "name to STANDARD_DOC_NAMES if it is genuinely universal."
    )


def test_doc_name_detector_actually_detects():
    """Guard the guard: a detector that silently matches nothing would pass forever."""
    leaky = 'COMPLETED = re.compile(r"(_REVIEW|LORE_DEEPDIVE_PLAN|QA_WAVE1)\\.md$")'
    assert _doc_name_hits(leaky) == {"LORE_DEEPDIVE_PLAN", "QA_WAVE1"}, "must flag doc names"
    assert _doc_name_hits('r"(_REVIEW|_TEST_RUN)\\.md$"') == set(), "suffixes are not doc names"
    assert "LESSONS_LEARNED" in _doc_name_hits("see LESSONS_LEARNED.md for details")


def test_seam_finds_the_generic_plugins():
    # Sanity: the crucible craft plugin is in scope (guards against an empty/mis-globbed run).
    names = {p.name for p in _generic_plugin_dirs()}
    assert "crucible" in names
