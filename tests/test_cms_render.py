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

import html
import json
import re
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
        page.write_text("<h2>Prose only</h2><p>No diagrams here.</p>", encoding="utf-8")

        violations, n = check_arch.check_file(page)

        assert violations == [] and n == 0

    def test_a_malformed_svg_still_fails(self):
        """The narrow case that *should* fire: an <svg> exists but is unusable."""
        page = Path(__file__).parent / "_tmp_malformed.html"
        page.write_text("<svg width='10'><rect/></svg>", encoding="utf-8")
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
        md.write_text(_fm("## Section\n\nBody.\n"), encoding="utf-8")
        out = tmp_path / "A.html"
        out.write_text(render_arch.build(md), encoding="utf-8")
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
        md.write_text(md.read_text(encoding="utf-8") + "\nmore\n", encoding="utf-8")

        assert self._rc(md, out) == 1

    def test_a_missing_output_trips_it(self, pair):
        md, out = pair
        out.unlink()

        assert self._rc(md, out) == 1

    def test_an_output_without_hashes_trips_it(self, pair):
        """An older generated file must not pass silently."""
        md, out = pair
        out.write_text("<html>no provenance</html>", encoding="utf-8")

        assert self._rc(md, out) == 1

    def test_both_hashes_are_embedded(self, pair):
        """Source alone is not enough — change the renderer and every page is
        stale while its source is untouched."""
        _, out = pair
        text = out.read_text(encoding="utf-8")

        assert render_arch.SRC_HASH_RE.search(text)
        assert render_arch.GEN_HASH_RE.search(text)


class TestPageAssembly:
    def test_accent_comes_from_frontmatter_not_the_renderer(self, tmp_path):
        """The palette is the repo's identity, not the tool's — that seam is what
        makes this promotable to other repos."""
        md = tmp_path / "A.md"
        md.write_text("---\ntitle: T\napplies_to: demo\naccent: \"#00FF99\"\n---\n\n## S\n", encoding="utf-8")

        assert "#00FF99" in render_arch.build(md)

    def test_nav_is_built_from_the_h2s(self, tmp_path):
        md = tmp_path / "A.md"
        md.write_text(_fm("## First\n\n## Second\n"), encoding="utf-8")
        out = render_arch.build(md)

        assert '<a href="#first">First</a>' in out
        assert '<a href="#second">Second</a>' in out

    def test_the_output_declares_itself_generated(self, tmp_path):
        """The single-source claim collapses the moment someone hand-edits the
        HTML, so the page has to say so."""
        md = tmp_path / "A.md"
        md.write_text(_fm("## S\n"), encoding="utf-8")

        assert "DO NOT EDIT" in render_arch.build(md).upper()


# ════════════════════════════════════════════════════════════════════════════
# DOM identity, accessibility and the flow walker
# ════════════════════════════════════════════════════════════════════════════

def _view(nodes, edges, vid="v1", groups=None):
    return {"id": vid, "caption": "cap",
            "nodes": nodes, "edges": edges, "groups": groups or []}


def _block(lang, obj):
    return f"```{lang}\n{json.dumps(obj)}\n```\n"


class TestDiagramIdentity:
    """Every emitted shape has to be findable from the model that produced it.

    Without this the diagram is a picture: correct, and completely inert. The
    flow walker, the text alternative and any future tooling all need a handle
    back to the archview node that produced a given box.
    """

    def test_nodes_carry_scoped_id_and_data_node(self):
        spec = _view([{"id": "alpha", "label": "Alpha"}], [])
        out = render_arch.render_diagram(spec, 3)

        assert 'id="f3-nd-alpha"' in out
        assert 'data-node="alpha"' in out

    def test_ids_are_scoped_per_figure_so_two_diagrams_cannot_collide(self):
        """Two diagrams on one page may both name a node `wallet`. Unscoped ids
        would make that invalid HTML and send getElementById to the wrong box."""
        spec = _view([{"id": "wallet", "label": "W"}], [])
        page = render_arch.render_markdown(
            _block("archview", spec) + _block("archview", dict(spec, id="v2"))
        )

        assert 'id="f1-nd-wallet"' in page
        assert 'id="f2-nd-wallet"' in page

    @pytest.mark.parametrize("raw,slug", [
        ("worker.py", "worker-py"),
        ("a/b", "a-b"),
        ("Has Spaces", "has-spaces"),
        ("...", "x"),
    ])
    def test_slug_id_survives_ids_that_are_illegal_in_a_selector(self, raw, slug):
        assert render_arch._slug_id(raw) == slug

    def test_edges_carry_identity_on_a_wrapping_g_not_the_path(self):
        """check_arch.RE_PATH demands d= immediately after class=. An attribute
        slipped between them stops it matching *any* connector, so every page
        would pass while checking nothing. This is that regression guard."""
        spec = _view([{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                     [{"from": "a", "to": "b"}])
        out = render_arch.render_diagram(spec)

        assert 'data-edge-from="a" data-edge-to="b"' in out
        assert '<path class="wire" d="' in out
        assert check_arch.RE_PATH.search(out) is not None

    def test_nodes_are_labelled_without_a_title_element(self):
        """<title> renders as a native browser tooltip, which would fight the
        flow caption. aria-label says the same thing and shows nothing."""
        spec = _view([{"id": "a", "label": "A", "sub": "does things",
                       "tech": "Python"}], [])
        out = render_arch.render_diagram(spec)

        assert "<title>" not in out
        assert 'role="graphics-symbol"' in out
        assert "A — does things — built with Python" in out

    def test_text_alternative_table_names_every_node_and_its_targets(self):
        spec = _view([{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}],
                     [{"from": "a", "to": "b", "label": "writes"}])
        out = render_arch.render_diagram(spec)

        assert 'class="sr-only"' in out
        assert "<td>Alpha</td>" in out
        assert "Beta (writes)" in out

    def test_legend_is_not_an_svg_so_the_checker_cannot_count_it_as_a_diagram(self):
        """An <svg viewBox> legend swatch is picked up by check_arch's diagram
        regex — it reported six diagrams on a page holding one."""
        spec = _view([{"id": "a", "label": "A", "kind": "store"},
                      {"id": "b", "label": "B", "kind": "external"}], [])
        out = render_arch.render_diagram(spec)

        assert '<span class="lgs lgs-store"' in out
        assert len(check_arch.RE_SVG.findall(out)) == 1

    def test_legend_is_omitted_when_one_kind_explains_itself(self):
        spec = _view([{"id": "a", "label": "A"}, {"id": "b", "label": "B"}], [])
        assert 'class="legend"' not in render_arch.render_diagram(spec)


class TestArchFlow:
    """A flow that points at nothing must fail the build, not the reader.

    check_arch only ever reads the emitted SVG, so a dangling reference is
    invisible to it — a picker whose third step highlights nothing looks exactly
    like one that works.
    """

    def _page(self, flows, view=None):
        v = view or _view(
            [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            [{"from": "a", "to": "b"}],
        )
        return _block("archview", v) + _block("archflow", {"view": "v1", "flows": flows})

    def test_a_valid_flow_emits_a_listbox_and_a_live_caption(self):
        page = render_arch.render_markdown(self._page([
            {"id": "f", "label": "Flow", "steps": [
                {"node": "a", "note": "starts here"},
                {"edge": ["a", "b"]},
            ]},
        ]))

        assert 'role="listbox"' in page
        assert 'aria-live="polite"' in page
        assert 'data-view="fig-f1"' in page
        assert "data-flow-next" in page

    def test_unknown_view_names_what_is_available(self):
        page = _block("archview", _view([{"id": "a", "label": "A"}], [])) + \
            _block("archflow", {"view": "nope", "flows": []})
        with pytest.raises(render_arch.ArchFlowError) as e:
            render_arch.render_markdown(page)

        assert "nope" in str(e.value)
        assert "v1" in str(e.value)

    def test_a_flow_declared_before_its_view_is_an_error_not_a_silent_pass(self):
        """The registry is a single forward pass. Ordering is a real constraint,
        so it has to fail loudly rather than render an inert picker."""
        page = _block("archflow", {"view": "v1", "flows": []}) + \
            _block("archview", _view([{"id": "a", "label": "A"}], []))
        with pytest.raises(render_arch.ArchFlowError):
            render_arch.render_markdown(page)

    def test_step_pointing_at_a_missing_node_raises_with_the_valid_ids(self):
        with pytest.raises(render_arch.ArchFlowError) as e:
            render_arch.render_markdown(self._page([
                {"id": "f", "label": "F", "steps": [{"node": "ghost"}]},
            ]))

        assert "ghost" in str(e.value)
        assert "'a'" in str(e.value)

    def test_step_pointing_at_a_missing_edge_raises(self):
        with pytest.raises(render_arch.ArchFlowError):
            render_arch.render_markdown(self._page([
                {"id": "f", "label": "F", "steps": [{"edge": ["b", "a"]}]},
            ]))

    def test_a_step_must_be_exactly_one_of_node_or_edge(self):
        with pytest.raises(render_arch.ArchFlowError):
            render_arch.render_markdown(self._page([
                {"id": "f", "label": "F", "steps": [{"node": "a", "edge": ["a", "b"]}]},
            ]))

    def test_duplicate_flow_ids_raise(self):
        with pytest.raises(render_arch.ArchFlowError):
            render_arch.render_markdown(self._page([
                {"id": "dup", "label": "One", "steps": [{"node": "a"}]},
                {"id": "dup", "label": "Two", "steps": [{"node": "b"}]},
            ]))

    def test_a_note_cannot_break_out_of_the_data_flows_attribute(self):
        """Step notes are author-written prose that ends up inside an HTML
        attribute holding JSON. If escaping is wrong the page stops being a
        document and starts being an injection point."""
        hostile = '</script><img src=x onerror=alert(1)>"\' & <b>b</b>'
        page = render_arch.render_markdown(self._page([
            {"id": "f", "label": "F", "steps": [{"node": "a", "note": hostile}]},
        ]))
        raw = re.search(r'data-flows="([^"]*)"', page).group(1)

        assert '"' not in raw and "<" not in raw
        assert json.loads(html.unescape(raw))[0]["steps"][0]["note"] == hostile

    def test_an_unnamed_view_is_still_addressable_by_position(self):
        v = _view([{"id": "a", "label": "A"}], [])
        del v["id"]
        page = _block("archview", v) + _block("archflow", {
            "view": "f1", "flows": [{"id": "x", "label": "X", "steps": [{"node": "a"}]}]})

        assert 'role="listbox"' in render_arch.render_markdown(page)

    def test_a_page_with_a_flow_still_passes_the_geometry_checker(self):
        """Groups, a back edge and a flow walker have never co-occurred on a real
        page. This is the combination that would surface a routing bug latest."""
        v = _view(
            [{"id": "a", "label": "A"}, {"id": "b", "label": "B"},
             {"id": "c", "label": "C"}],
            [{"from": "a", "to": "b"}, {"from": "b", "to": "c"},
             {"from": "c", "to": "a", "label": "retry"}],
            groups=[{"id": "G", "label": "boundary", "members": ["a", "b"]}],
        )
        page = render_arch.render_markdown(
            _block("archview", v) + _block("archflow", {"view": "v1", "flows": [
                {"id": "f", "label": "F", "steps": [
                    {"node": "a"}, {"edge": ["c", "a"]}]},
            ]}))
        body = check_arch.RE_SVG.findall(page)

        assert len(body) == 1
        assert check_arch.check_svg(body[0][1], body[0][0]) == []


class TestThemeAndPrint:
    def test_theme_is_stamped_before_the_stylesheet_to_avoid_a_flash(self, tmp_path):
        """Setting the theme after paint shows the wrong one for a frame."""
        md = tmp_path / "A.md"
        md.write_text(_fm("## S\n"), encoding="utf-8")
        out = render_arch.build(md)

        assert out.index("arch-theme") < out.index("<style>")

    def test_a_light_theme_and_print_rules_exist(self, tmp_path):
        md = tmp_path / "A.md"
        md.write_text(_fm("## S\n"), encoding="utf-8")
        out = render_arch.build(md)

        assert ':root[data-theme="light"]' in out
        assert "@media print" in out

    def test_the_dead_smil_pause_calls_are_gone(self, tmp_path):
        """pauseAnimations() drives SMIL. Every animation here is CSS keyframes,
        so the call never did anything."""
        md = tmp_path / "A.md"
        md.write_text(_fm("## S\n"), encoding="utf-8")

        assert "pauseAnimations" not in render_arch.build(md)

    def test_published_url_becomes_a_canonical_link(self, tmp_path):
        md = tmp_path / "A.md"
        md.write_text(
            "---\ntitle: T\napplies_to: demo\n"
            "published_url: https://example.invalid/a/b\n---\n\n## S\n",
            encoding="utf-8")
        out = render_arch.build(md)

        assert 'href="https://example.invalid/a/b"' in out
        assert "CANONICAL" in out

    def test_a_non_url_is_not_rendered_as_a_link(self, tmp_path):
        """A half-filled frontmatter field must not become a broken promise."""
        md = tmp_path / "A.md"
        md.write_text("---\ntitle: T\napplies_to: demo\npublished_url: tbd\n---\n\n## S\n",
                      encoding="utf-8")

        assert "CANONICAL" not in render_arch.build(md)


class TestPublishManifest:
    """`--publish` renders and then tells the agent what to do.

    It deliberately does not upload. This renderer is pure stdlib with no network
    and no credentials, and the moment it grows either, every repo that runs it
    inherits that surface.
    """

    def _repo(self, tmp_path, extra=""):
        d = tmp_path / "docs"
        d.mkdir()
        (d / "ARCHITECTURE.md").write_text(
            f"---\ntitle: T\napplies_to: demo\n{extra}---\n\n## S\n", encoding="utf-8")
        return tmp_path

    def _run(self, repo, *flags):
        return subprocess.run(
            [sys.executable, str(TOOLS / "render.py"), str(repo), *flags],
            capture_output=True, text=True)

    def test_a_bound_doc_prints_its_existing_address(self, tmp_path):
        r = self._run(self._repo(tmp_path, "published_url: https://example.invalid/x\n"),
                      "--publish")

        assert r.returncode == 0
        assert "PUBLISH " in r.stdout
        assert "url=https://example.invalid/x" in r.stdout

    def test_an_unbound_doc_asks_for_a_new_address(self, tmp_path):
        r = self._run(self._repo(tmp_path), "--publish")

        assert r.returncode == 0
        assert "PUBLISH-NEW" in r.stdout

    def test_rendering_without_the_flag_prints_no_manifest(self, tmp_path):
        r = self._run(self._repo(tmp_path, "published_url: https://example.invalid/x\n"))

        assert "PUBLISH" not in r.stdout

    def test_a_dangling_flow_reference_writes_nothing_and_exits_two(self, tmp_path):
        """Half a page is worse than no page — it looks rendered."""
        d = tmp_path / "docs"
        d.mkdir()
        view = {"id": "v", "caption": "c",
                "nodes": [{"id": "a", "label": "A"}], "edges": []}
        flow = {"view": "v", "flows": [
            {"id": "f", "label": "F", "steps": [{"node": "ghost"}]}]}
        (d / "ARCHITECTURE.md").write_text(
            "---\ntitle: T\napplies_to: demo\n---\n\n"
            + _block("archview", view) + _block("archflow", flow),
            encoding="utf-8")

        r = self._run(tmp_path)

        assert r.returncode == 2
        assert "ghost" in r.stderr
        assert not (d / "ARCHITECTURE.html").exists()


class TestFlowIdentityCannotCollide:
    """Four ways a flow could quietly claim a handle that is not uniquely its own.

    Every one of these renders successfully and looks right. They were found by
    review, not by a failing page, which is the argument for keeping them here.
    """

    def _view(self, nodes, edges):
        return {"id": "v", "caption": "c", "nodes": nodes, "edges": edges}

    def test_two_ids_that_slugify_the_same_are_a_collision(self):
        """'Flow A' and 'Flow-A' are different strings and one DOM id."""
        page = _block("archview", self._view([{"id": "a", "label": "A"}], [])) + \
            _block("archflow", {"view": "v", "flows": [
                {"id": "Flow A", "label": "One", "steps": [{"node": "a"}]},
                {"id": "Flow-A", "label": "Two", "steps": [{"node": "a"}]},
            ]})
        with pytest.raises(render_arch.ArchFlowError) as e:
            render_arch.render_markdown(page)

        assert "flow-a" in str(e.value)

    def test_collision_is_detected_across_separate_archflow_blocks(self):
        """Splitting the happy path and the error path into two blocks is a
        reasonable way to write a page, and it used to defeat the check."""
        v = _block("archview", self._view([{"id": "a", "label": "A"}], []))
        one = _block("archflow", {"view": "v", "flows": [
            {"id": "x", "label": "One", "steps": [{"node": "a"}]}]})
        with pytest.raises(render_arch.ArchFlowError):
            render_arch.render_markdown(v + one + one)

    def test_a_flow_without_an_id_gets_a_sentence_not_a_keyerror(self):
        page = _block("archview", self._view([{"id": "a", "label": "A"}], [])) + \
            _block("archflow", {"view": "v", "flows": [
                {"label": "No id", "steps": [{"node": "a"}]}]})
        with pytest.raises(render_arch.ArchFlowError) as e:
            render_arch.render_markdown(page)

        assert "id" in str(e.value)

    def test_a_flow_without_a_label_is_rejected_too(self):
        page = _block("archview", self._view([{"id": "a", "label": "A"}], [])) + \
            _block("archflow", {"view": "v", "flows": [
                {"id": "x", "steps": [{"node": "a"}]}]})
        with pytest.raises(render_arch.ArchFlowError):
            render_arch.render_markdown(page)

    def test_edge_identity_survives_a_node_id_containing_the_old_delimiter(self):
        """Joining ids with '__' made (a -> b__c) and (a__b -> c) the same key,
        and querySelector silently returned whichever came first."""
        spec = self._view(
            [{"id": "a", "label": "A"}, {"id": "b__c", "label": "BC"},
             {"id": "a__b", "label": "AB"}, {"id": "c", "label": "C"}],
            [{"from": "a", "to": "b__c"}, {"from": "a__b", "to": "c"}],
        )
        out = render_arch.render_diagram(spec)

        assert 'data-edge-from="a" data-edge-to="b__c"' in out
        assert 'data-edge-from="a__b" data-edge-to="c"' in out
        assert "data-edge=" not in out


class TestScaffoldTemplate:
    def test_the_init_template_actually_renders(self, tmp_path):
        """`/cms init` hands this file to a fresh repo. A scaffold that fails
        `/cms render` is worse than no scaffold — the first thing the new repo
        does with it is hit an error."""
        tpl = (TOOLS.parent / "templates" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        d = tmp_path / "docs"
        d.mkdir()
        (d / "ARCHITECTURE.md").write_text(tpl.replace("{{REPO_NAME}}", "demo"),
                                           encoding="utf-8")
        out = render_arch.build(d / "ARCHITECTURE.md")

        assert 'role="listbox"' in out          # it demonstrates archflow
        assert "<svg" in out                    # and archview


class TestChainLayout:
    """A pipeline laid out as a column is worse than the list it replaced.

    Seven sequential steps through the general layerer become seven rows — about
    800px of vertical scroll for something that reads left to right. A path gets
    serpentine placement instead; anything that branches is untouched.
    """

    def _chain(self, n):
        return {"id": "c", "caption": "c",
                "nodes": [{"id": f"s{i}", "label": f"step {i}"} for i in range(n)],
                "edges": [{"from": f"s{i}", "to": f"s{i+1}"} for i in range(n - 1)]}

    def test_a_path_is_detected_as_a_chain(self):
        spec = self._chain(7)
        assert render_arch._chain_order(spec["nodes"], spec["edges"]) == [
            f"s{i}" for i in range(7)]

    def test_a_branching_graph_is_not_a_chain(self):
        nodes = [{"id": x, "label": x} for x in ("a", "b", "c", "d")]
        edges = [{"from": "a", "to": "b"}, {"from": "a", "to": "c"},
                 {"from": "b", "to": "d"}]
        assert render_arch._chain_order(nodes, edges) is None

    def test_a_cycle_is_not_a_chain(self):
        nodes = [{"id": x, "label": x} for x in ("a", "b", "c", "d")]
        edges = [{"from": "a", "to": "b"}, {"from": "b", "to": "c"},
                 {"from": "c", "to": "d"}, {"from": "d", "to": "a"}]
        assert render_arch._chain_order(nodes, edges) is None

    def test_a_chain_is_wider_than_it_is_tall(self):
        """The whole point. Under the layered engine this was a column."""
        out = render_arch.render_diagram(self._chain(7))
        m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', out)
        w, h = float(m.group(1)), float(m.group(2))

        assert w > h, f"chain rendered {w}x{h} — still a column"

    def test_a_chain_still_passes_the_geometry_checker(self):
        out = render_arch.render_diagram(self._chain(9))
        vb, body = check_arch.RE_SVG.findall(out)[0]

        assert check_arch.check_svg(body, vb) == []

    def test_a_short_sequence_keeps_the_column(self):
        """Below the floor, wrapping just looks arbitrary."""
        assert render_arch._chain_order(*(lambda s: (s["nodes"], s["edges"]))(
            self._chain(3))) is None
