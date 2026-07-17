"""Seam linter: generic (Tier A) plugins must contain no domain (Tier B/C) content.

The #1 failure mode of a consolidated marketplace (ADR-001) is domain judgment leaking
into a generic craft plugin. This test enforces the plugin-boundary seam: anything in a
generic plugin must be reusable by anyone, with zero ecosystem/domain specifics.
"""
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


def test_seam_finds_the_generic_plugins():
    # Sanity: the crucible craft plugin is in scope (guards against an empty/mis-globbed run).
    names = {p.name for p in _generic_plugin_dirs()}
    assert "crucible" in names
