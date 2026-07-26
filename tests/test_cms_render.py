"""The architecture renderer and its structural checker.

Two things are being defended here, and they are different.

`render_arch` turns ARCHITECTURE.md into ARCHITECTURE.html. Its failure mode is
*silence*: a markdown form it does not implement gets absorbed into a paragraph
and the page still looks fine. That is not hypothetical — an out-of-sample run
against five existing docs found ordered lists being swallowed whole, which
turned a repo's five-step pipeline description into a run-on sentence.

`check_arch` inspects the emitted SVG. Its failure mode is being *toothless*: a
checker that passes everything is worse than no checker, because it grants
confidence it has not earned. So it is mutation-tested — defects are planted and
it must find them.
"""

import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = (Path(__file__).resolve().parents[1]
         / "plugins" / "crucible" / "skills" / "cms" / "scripts")

import check_arch  # noqa: E402
import render as render_arch  # noqa: E402


def _fm(body: str) -> str:
    return f"---\ntitle: T\napplies_to: demo\n---\n\n{body}\n"


# ════════════════════════════════════════════════════════════════════════════
# markdown subset
# ════════════════════════════════════════════════════════════════════════════

class TestMarkdownBlocks:
    def test_h1_is_consumed_without_hanging(self):
        """The bug that hung the very first render: '# Title' failed the h2-h4
        match, then the paragraph branch rejected lines starting with '#', so it
        emitted an empty <p> and never advanced. An infinite loop that presents
        as a silent hang."""
        out = render_arch.render_markdown("# Title\n\nBody text.\n")

        assert "<h1" not in out          # the page header already names the repo
        assert "<p>Body text.</p>" in out
        assert "<p></p>" not in out

    def test_headings_become_anchored(self):
        out = render_arch.render_markdown("## Data Layer\n")

        assert '<h2 id="data-layer">Data Layer</h2>' in out

    @pytest.mark.parametrize("rule", ["---", "***", "___", "-----"])
    def test_horizontal_rules(self, rule):
        """Every repo's doc has these. They used to render as <p>---</p>."""
        assert "<hr>" in render_arch.render_markdown(f"text\n\n{rule}\n\nmore\n")

    def test_blockquote_keeps_its_text_and_drops_its_marker(self):
        """CRA's opening paragraph is a blockquote — the '>' used to leak into
        the rendered text as &gt;."""
        out = render_arch.render_markdown("> quoted line\n> continues\n")

        assert "<blockquote>" in out
        assert "&gt;" not in out
        assert "quoted line continues" in out

    def test_ordered_list_survives(self):
        """The destructive one. Numbered items were neither recognised nor
        treated as paragraph terminators, so a numbered pipeline was absorbed
        into the sentence above it."""
        out = render_arch.render_markdown("Steps:\n\n1. Load\n2. Detect\n3. Fetch\n")

        assert out.count("<li>") == 3
        assert "<ol>" in out
        assert "<p>Steps:</p>" in out          # the lead-in stays its own paragraph

    def test_a_paragraph_does_not_swallow_the_block_after_it(self):
        """The root cause, asserted directly: the paragraph accumulator and the
        block-form list must agree. They had drifted."""
        out = render_arch.render_markdown("Lead in\n1. one\n")

        assert "<ol>" in out
        assert "1. one" not in out

    def test_unordered_list(self):
        out = render_arch.render_markdown("- alpha\n- beta\n")

        assert out.count("<li>") == 2
        assert "<ul>" in out

    def test_table(self):
        out = render_arch.render_markdown("| a | b |\n|---|---|\n| 1 | 2 |\n")

        assert "<table>" in out and out.count("<td>") == 2

    def test_code_fence_is_escaped_not_executed(self):
        out = render_arch.render_markdown("```python\n<script>x</script>\n```\n")

        assert "&lt;script&gt;" in out
        assert "<script>x</script>" not in out

    def test_html_fence_passes_through_untouched(self):
        """The mechanism socket — repo-specific visuals need no schema."""
        out = render_arch.render_markdown('```html\n<div id="custom-figure"></div>\n```\n')

        assert '<div id="custom-figure"></div>' in out

    @pytest.mark.parametrize("md,want", [
        ("**bold**", "<strong>bold</strong>"),
        ("`code`", "<code>code</code>"),
        ("[t](u)", '<a href="u">t</a>'),
    ])
    def test_inline_forms(self, md, want):
        assert want in render_arch.render_markdown(md + "\n")

    def test_every_block_form_also_terminates_a_paragraph(self):
        """Guards the bug class rather than one instance: any form _starts_block
        recognises must also stop a paragraph, or it gets absorbed."""
        for line in ["## h", "| a |", "```x", "---", "> q", "1. one", "- one"]:
            assert render_arch._starts_block(line), line


# ════════════════════════════════════════════════════════════════════════════
# diagram engine
# ════════════════════════════════════════════════════════════════════════════

def _spec(n, edges, groups=None):
    return {"nodes": [{"id": f"n{i}", "label": f"node {i}"} for i in range(n)],
            "edges": edges, "groups": groups or []}


class TestLayout:
    def test_layers_by_longest_path(self):
        layer, fwd, back = render_arch._layer(
            _spec(3, [])["nodes"],
            [{"from": "n0", "to": "n1"}, {"from": "n1", "to": "n2"}])

        assert (layer["n0"], layer["n1"], layer["n2"]) == (0, 1, 2)
        assert len(fwd) == 2 and back == []

    def test_a_cycle_is_split_into_forward_and_back(self):
        """A back edge must not participate in layering, or a cycle would not
        terminate."""
        _, fwd, back = render_arch._layer(
            _spec(2, [])["nodes"],
            [{"from": "n0", "to": "n1"}, {"from": "n1", "to": "n0"}])

        assert len(fwd) == 1 and len(back) == 1

    def test_node_width_accounts_for_the_tech_line(self):
        narrow = render_arch._node_w({"label": "x"})
        wide = render_arch._node_w({"label": "x", "tech": "a-very-long-technology-string"})

        assert wide > narrow

    def test_row_height_grows_with_line_count(self):
        assert (render_arch.NODE_H[1] < render_arch.NODE_H[2]
                < render_arch.NODE_H[3])

    def test_renders_without_edges(self):
        svg = render_arch.render_diagram(_spec(2, []))

        # 'class="nd ' with the trailing space — 'class="nd' alone also matches
        # the ndl/nds/ndt label classes and silently counts double.
        assert "<svg" in svg and svg.count('class="nd nd-') == 2


class TestRoutingIsCollisionFree:
    """These are the regressions that the structural checker found in a page
    that had already been committed, pushed and called finished."""

    def _violations(self, spec):
        html = render_arch.render_diagram(spec)
        import re
        m = re.search(r'viewBox="([^"]+)"', html)
        body = html[html.index("<svg"):html.index("</svg>")]
        return check_arch.check_svg(body, m.group(1))

    def test_an_edge_skipping_a_row_does_not_cross_it(self):
        """A multi-layer edge used to drop straight down its own column, through
        whatever node happened to sit in between."""
        spec = _spec(3, [{"from": "n0", "to": "n1"},
                         {"from": "n1", "to": "n2"},
                         {"from": "n0", "to": "n2"}])

        assert self._violations(spec) == []

    def test_a_back_edge_does_not_cross_the_rows_it_returns_over(self):
        """The return leg used to run horizontally at the target's mid-height,
        straight through anything between the lane and the target."""
        spec = _spec(4, [{"from": "n0", "to": "n1"},
                         {"from": "n1", "to": "n2"},
                         {"from": "n2", "to": "n3"},
                         {"from": "n3", "to": "n0"}])

        assert self._violations(spec) == []

    def test_a_wide_row_with_a_skip_edge_stays_clean(self):
        """Leaving a node sideways at its own mid-height clips its row-mates —
        so horizontal travel only ever happens in inter-row gaps."""
        spec = _spec(8, [{"from": "n0", "to": f"n{i}"} for i in range(1, 6)]
                     + [{"from": "n1", "to": "n6"}, {"from": "n0", "to": "n7"},
                        {"from": "n6", "to": "n7"}])

        assert self._violations(spec) == []

    def test_a_nineteen_node_graph_stays_clean(self):
        """The size CRA actually is. Layout engines fail quietly as graphs grow."""
        edges = ([{"from": "n0", "to": "n1"}]
                 + [{"from": "n1", "to": f"n{i}"} for i in range(2, 7)]
                 + [{"from": f"n{i}", "to": f"n{i + 5}"} for i in range(2, 7)]
                 + [{"from": "n7", "to": "n12"}, {"from": "n8", "to": "n12"},
                    {"from": "n11", "to": "n13"}, {"from": "n13", "to": "n14"},
                    {"from": "n14", "to": "n15"}, {"from": "n1", "to": "n11"},
                    {"from": "n15", "to": "n16"}, {"from": "n16", "to": "n17"},
                    {"from": "n17", "to": "n18"}, {"from": "n12", "to": "n8"}])

        assert self._violations(_spec(19, edges)) == []


# ════════════════════════════════════════════════════════════════════════════
# structural checker — mutation tested
# ════════════════════════════════════════════════════════════════════════════

class TestCheckerHasTeeth:
    """A checker that passes everything is worse than none: it grants confidence
    it has not earned. Each planted defect must be caught, by the right code."""

    BASE = ('<svg viewBox="0 0 400 300">'
            '<rect class="nd nd-module" x="20" y="20" width="100" height="40"/>'
            '<rect class="nd nd-module" x="200" y="20" width="100" height="40"/>'
            '<path class="wire" d="M70 60 L70 120 L250 120 L250 160"/>'
            '<rect class="nd nd-module" x="200" y="160" width="100" height="40"/>'
            '</svg>')

    def _check(self, svg):
        body = svg[svg.index(">") + 1:svg.index("</svg>")]
        return {v.code for v in check_arch.check_svg(body, "0 0 400 300")}

    def test_the_clean_baseline_passes(self):
        assert self._check(self.BASE) == set()

    def test_C1_overlapping_nodes(self):
        bad = self.BASE.replace('x="200" y="20"', 'x="60" y="30"')

        assert "C1" in self._check(bad)

    def test_C2_connector_through_a_node(self):
        bad = self.BASE.replace('d="M70 60 L70 120 L250 120 L250 160"',
                                'd="M70 60 L70 300 L250 300"').replace(
            '<rect class="nd nd-module" x="200" y="160"',
            '<rect class="nd nd-module" x="40" y="150"')

        assert "C2" in self._check(bad)

    def test_C3_geometry_outside_the_viewbox(self):
        assert "C3" in self._check(self.BASE.replace('y="160"', 'y="900"'))

    def test_C5_degenerate_rect(self):
        assert "C5" in self._check(self.BASE.replace('height="40"/>', 'height="0"/>', 1))

    def test_a_page_with_no_diagrams_is_not_a_failure(self, tmp_path):
        """Four of six repos have prose and no archview blocks yet. Flagging them
        would make the checker cry wolf on two thirds of the estate, and a
        checker that cries wolf gets switched off — which costs more than it was
        ever worth."""
        page = tmp_path / "p.html"
        page.write_text("<h2>Prose only</h2><p>No diagrams here.</p>")

        violations, n = check_arch.check_file(page)

        assert violations == [] and n == 0

    def test_a_malformed_svg_still_fails(self):
        """The narrow case that *should* fire: an <svg> exists but is unusable."""
        page = Path(__file__).parent / "_tmp_malformed.html"
        page.write_text("<svg width='10'><rect/></svg>")
        try:
            violations, _ = check_arch.check_file(page)
            assert {v.code for v in violations} == {"C6"}
        finally:
            page.unlink(missing_ok=True)

    def test_touching_edges_is_not_an_overlap(self):
        """Connectors legitimately start on a node's border, and adjacent boxes
        may abut. Only interior penetration counts, or the checker cries wolf
        and gets ignored."""
        touching = ('<svg viewBox="0 0 400 300">'
                    '<rect class="nd nd-module" x="20" y="20" width="100" height="40"/>'
                    '<rect class="nd nd-module" x="120" y="20" width="100" height="40"/>'
                    '</svg>')

        assert self._check(touching) == set()


# ════════════════════════════════════════════════════════════════════════════
# provenance
# ════════════════════════════════════════════════════════════════════════════

class TestProvenanceGate:
    """--check must answer 'is this page current' correctly across a git
    checkout, which does not preserve mtimes."""

    @pytest.fixture
    def pair(self, tmp_path):
        md = tmp_path / "A.md"
        md.write_text(_fm("## Section\n\nBody.\n"))
        out = tmp_path / "A.html"
        out.write_text(render_arch.build(md))
        return md, out

    def _rc(self, md, out):
        return subprocess.run(
            [sys.executable, str(TOOLS / "render.py"),
             "--check", "-i", str(md), "-o", str(out)],
            capture_output=True, text=True).returncode

    def test_current_page_passes(self, pair):
        assert self._rc(*pair) == 0

    def test_touching_the_source_does_not_trip_it(self, pair):
        """An mtime check reported STALE on a byte-identical file after every
        checkout. That fired on the first real merge."""
        md, out = pair
        md.touch()

        assert self._rc(md, out) == 0

    def test_editing_the_source_trips_it(self, pair):
        md, out = pair
        md.write_text(md.read_text() + "\nmore\n")

        assert self._rc(md, out) == 1

    def test_a_missing_output_trips_it(self, pair):
        md, out = pair
        out.unlink()

        assert self._rc(md, out) == 1

    def test_an_output_without_hashes_trips_it(self, pair):
        """An older generated file must not pass silently."""
        md, out = pair
        out.write_text("<html>no provenance</html>")

        assert self._rc(md, out) == 1

    def test_both_hashes_are_embedded(self, pair):
        """Source alone is not enough — change the renderer and every page is
        stale while its source is untouched."""
        _, out = pair
        text = out.read_text()

        assert render_arch.SRC_HASH_RE.search(text)
        assert render_arch.GEN_HASH_RE.search(text)


class TestPageAssembly:
    def test_accent_comes_from_frontmatter_not_the_renderer(self, tmp_path):
        """The palette is the repo's identity, not the tool's — that seam is what
        makes this promotable to other repos."""
        md = tmp_path / "A.md"
        md.write_text("---\ntitle: T\napplies_to: demo\naccent: \"#00FF99\"\n---\n\n## S\n")

        assert "#00FF99" in render_arch.build(md)

    def test_nav_is_built_from_the_h2s(self, tmp_path):
        md = tmp_path / "A.md"
        md.write_text(_fm("## First\n\n## Second\n"))
        out = render_arch.build(md)

        assert '<a href="#first">First</a>' in out
        assert '<a href="#second">Second</a>' in out

    def test_the_output_declares_itself_generated(self, tmp_path):
        """The single-source claim collapses the moment someone hand-edits the
        HTML, so the page has to say so."""
        md = tmp_path / "A.md"
        md.write_text(_fm("## S\n"))

        assert "DO NOT EDIT" in render_arch.build(md).upper()
