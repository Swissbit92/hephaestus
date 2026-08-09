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


class TestReadability:
    """Mechanics, not decoration. Each of these was measurably wrong."""

    def _page(self, tmp_path, body="## S\n\ntext\n"):
        md = tmp_path / "A.md"
        md.write_text(_fm(body), encoding="utf-8")
        return render_arch.build(md)

    def test_measure_is_tuned_for_monospace(self, tmp_path):
        """45-75ch assumes ~0.5em glyphs; mono runs ~0.6em, so the same ch count
        is a materially longer line. 78ch was over the top of the range."""
        out = self._page(tmp_path)

        assert "max-width:68ch" in out
        assert "max-width:78ch" not in out

    def test_figures_are_tabular(self, tmp_path):
        assert "tabular-nums" in self._page(tmp_path)

    def test_the_accent_ramp_is_derived_not_concatenated(self, tmp_path):
        """Appending hex alpha to the frontmatter value assumes 6-digit hex and
        produces garbage for anything else."""
        md = tmp_path / "A.md"
        md.write_text("---\ntitle: T\napplies_to: d\naccent: \"oklch(70% 0.15 40)\"\n---\n\n## S\n",
                      encoding="utf-8")
        out = render_arch.build(md)

        assert "color-mix(in oklch" in out
        assert "oklch(70% 0.15 40)18" not in out      # the old bug, spelled out

    def test_tables_pin_their_header_and_their_label_column(self, tmp_path):
        out = self._page(tmp_path, "| a | b |\n|---|---|\n| 1 | 2 |\n")

        assert "position:sticky" in out
        assert "tbody td:first-child" in out

    def test_code_blocks_carry_a_copy_button_in_the_markup(self, tmp_path):
        """Server-rendered, so the block does not reflow after paint."""
        out = self._page(tmp_path, "```\nsome code\n```\n")

        assert "data-copy" in out
        assert out.index("data-copy") < out.index("some code")


class TestTextSibling:
    """The second reader. An agent handed the rendered page wades through 40KB
    of CSS and SVG coordinates to reach three sentences."""

    def test_diagrams_become_sentences(self, tmp_path):
        v = {"id": "v", "caption": "how it hangs together",
             "nodes": [{"id": "a", "label": "Alpha", "sub": "does things"},
                       {"id": "b", "label": "Beta", "kind": "store"}],
             "edges": [{"from": "a", "to": "b", "label": "writes"}]}
        md = tmp_path / "A.md"
        md.write_text(_fm(_block("archview", v)), encoding="utf-8")
        txt = render_arch.build_text(md)

        assert "how it hangs together" in txt
        assert "Alpha — does things" in txt
        assert "Alpha -> Beta [writes]" in txt
        assert "<svg" not in txt and "viewBox" not in txt

    def test_flows_become_numbered_steps(self, tmp_path):
        v = {"id": "v", "caption": "c", "nodes": [{"id": "a", "label": "A"}], "edges": []}
        fl = {"view": "v", "flows": [{"id": "f", "label": "The walk",
                                      "steps": [{"node": "a", "note": "first thing"}]}]}
        md = tmp_path / "A.md"
        md.write_text(_fm(_block("archview", v) + _block("archflow", fl)), encoding="utf-8")
        txt = render_arch.build_text(md)

        assert "[flow] The walk" in txt
        assert "1. a — first thing" in txt

    def test_presentation_only_blocks_are_dropped(self, tmp_path):
        md = tmp_path / "A.md"
        md.write_text(_fm("```html\n<div id='decor'></div>\n```\n"), encoding="utf-8")

        assert "decor" not in render_arch.build_text(md)


class TestStatsAndPills:
    """Two small vocabularies. Both are only useful while they stay small."""

    def test_a_gauge_row_renders_its_values(self):
        out = render_arch.render_stats([
            {"label": "Carry", "value": "Live", "note": "SUB1", "state": "bad"},
            {"label": "Venue", "value": "KuCoin"},
        ])

        assert 'class="gauges"' in out
        assert "<dt>Carry</dt>" in out
        assert "data-state=bad" in out
        assert "<small>SUB1</small>" in out

    def test_a_gauge_missing_a_value_is_an_error_not_a_blank_cell(self):
        with pytest.raises(render_arch.ArchStatError):
            render_arch.render_stats([{"label": "Carry"}])

    def test_an_invented_state_is_rejected(self):
        """The vocabulary is four. A fifth colour means nothing at a glance."""
        with pytest.raises(render_arch.ArchStatError) as e:
            render_arch.render_stats([{"label": "a", "value": "b", "state": "critical"}])

        assert "ok" in str(e.value)

    @pytest.mark.parametrize("state", ["ok", "warn", "bad", "mute"])
    def test_pills_render_inline_anywhere(self, state):
        out = render_arch.render_markdown(f"Status is [[{state}:Halted]] today.\n")

        assert f'<span class="pill pill-{state}">Halted</span>' in out

    def test_a_pill_survives_being_next_to_code_and_bold(self):
        out = render_arch.render_markdown("[[ok:Safe]] `run.py` is **fine**\n")

        assert 'class="pill pill-ok">Safe<' in out
        assert "<code>run.py</code>" in out
        assert "<strong>fine</strong>" in out

    def test_pills_work_inside_a_table_cell(self):
        out = render_arch.render_markdown(
            "| Lever | Effect |\n|---|---|\n| x | [[bad:Global]] no orders |\n")

        assert 'pill pill-bad' in out
        assert "<td>" in out

    def test_an_unknown_pill_state_is_left_as_written(self):
        """Silently swallowing it would hide the typo; leaving it visible does not."""
        out = render_arch.render_markdown("[[critical:Boom]]\n")

        assert "pill" not in out
        assert "[[critical:Boom]]" in out


class TestHeadingsAreFindable:
    def test_headings_use_the_serif_face_at_a_readable_size(self, tmp_path):
        """A heading set in the same width and nearly the same size as the
        paragraph beneath it is not doing the one job a heading has."""
        md = tmp_path / "A.md"
        md.write_text(_fm("## Trust boundary\n\ntext\n"), encoding="utf-8")
        out = render_arch.build(md)

        assert "--serif:ui-serif" in out
        assert "h2{margin:2.4rem 0 0;font-family:var(--serif);font-size:1.5rem" in out


class TestNodeDetail:
    """The readout said "refuse — rung restscode in this repo" — three inline
    spans with no gap between them. Structure, not string-sniffing, is what
    these assert."""

    def _v(self, **extra):
        nd = {"id": "a", "label": "Refuse", "sub": "rung rests", "kind": "module"}
        nd.update(extra)
        return {"id": "v", "caption": "c", "nodes": [nd, {"id": "b", "label": "B"}],
                "edges": [{"from": "a", "to": "b"}]}

    def test_the_three_fields_are_separate_elements(self):
        out = render_arch.render_diagram(self._v())

        assert 'class="ins-head"' in out       # label/kind/tech get their own row
        assert 'class="ins-s"' in out          # the sentence is its own block
        assert 'class="ins-links"' in out

    def test_an_authored_note_is_what_the_reader_sees(self):
        out = render_arch.render_diagram(self._v(note="Refuses the crossing and leaves the rung resting."))

        assert 'data-note="Refuses the crossing and leaves the rung resting."' in out

    def test_a_node_without_a_note_says_so_rather_than_inventing_one(self):
        """No tool synthesizes this sentence from label+kind, because there is
        not enough signal — a bad generated sentence is worse than a short gap."""
        out = render_arch.render_diagram(self._v())

        assert 'data-note=""' in out

    def test_relationships_are_derived_because_that_is_a_traversal(self):
        out = render_arch.render_diagram(self._v())

        assert "→ B" in out

    def test_every_diagram_gets_a_walker_not_only_flow_ones(self):
        """The ask was prev/next everywhere. A diagram with no authored sequence
        still gets one — labelled as layout order, so it does not pass a derived
        order off as a narrative."""
        out = render_arch.render_diagram(self._v())

        assert 'class="tour"' in out
        assert "data-tour-prev" in out and "data-tour-next" in out
        assert "layout order" in out

    def test_a_flow_step_note_reaches_the_node_it_describes(self):
        """The archview is emitted before the archflow below it is parsed, so
        this only works via a pre-pass — and without it the author would have to
        write the same sentence twice."""
        v = self._v()
        fl = {"view": "v", "flows": [{"id": "f", "label": "F", "steps": [
            {"node": "a", "note": "Over the cap, so the crossing is refused."}]}]}
        page = render_arch.render_markdown(_block("archview", v) + _block("archflow", fl))

        assert 'data-note="Over the cap, so the crossing is refused."' in page

    def test_an_explicit_node_note_beats_the_flow_step_note(self):
        v = self._v(note="The node's own words.")
        fl = {"view": "v", "flows": [{"id": "f", "label": "F", "steps": [
            {"node": "a", "note": "The flow's words."}]}]}
        page = render_arch.render_markdown(_block("archview", v) + _block("archflow", fl))

        assert "The node&#x27;s own words." in page or "The node's own words." in page
        assert 'data-note="The flow&#x27;s words."' not in page


# --- archplot: the mechanism figure without the hand-rolled SVG ---------------
# Every assertion below is a defect that actually happened while these figures
# were being drawn by hand. The primitive exists to make them unrepeatable.

def _plot(**over):
    spec = {"series": [{"label": "a", "tone": "good", "points": [0, 1, 2, 1]}]}
    spec.update(over)
    return spec


def test_generated_data_must_be_declared_schematic():
    """A curve drawn from a seed that reads as a measurement is the one failure
    mode of a figure like this, so the render refuses rather than guessing."""
    spec = _plot(series=[{"label": "walk", "walk": {"seed": 1}}])

    with pytest.raises(render_arch.ArchPlotError, match="schematic"):
        render_arch.render_plot(spec)


def test_generated_data_renders_once_declared():
    spec = _plot(schematic=True, series=[{"label": "walk", "walk": {"seed": 1}}])

    out = render_arch.render_plot(spec)

    assert "<polyline" in out and "schem" in out


def test_explicit_points_need_no_declaration():
    """Authored numbers are the author's claim to defend; only generated ones
    are forced to carry the badge."""
    assert "<polyline" in render_arch.render_plot(_plot())


def test_an_unlabelled_series_is_refused():
    with pytest.raises(render_arch.ArchPlotError, match="no label"):
        render_arch.render_plot(_plot(series=[{"points": [0, 1]}]))


def test_an_unknown_tone_is_refused():
    """Tones map to the theme's palette. A free-form colour is how a figure
    ends up failing contrast in one theme and not the other."""
    with pytest.raises(render_arch.ArchPlotError, match="tone"):
        render_arch.render_plot(_plot(series=[{"label": "a", "tone": "hotpink",
                                               "points": [0, 1]}]))


def test_a_hedged_leg_is_the_exact_negation_of_its_leg():
    """Two seeds would let the legs drift apart and quietly stop being a hedge."""
    gen = {"seed": 5, "vol": 0.1}
    a = render_arch._plot_walk(gen, 40)
    b = render_arch._plot_walk({**gen, "mirror": True}, 40)

    assert [round(x + y, 12) for x, y in zip(a, b)] == [0.0] * 40


def test_gated_spans_are_derived_from_the_line_not_placed_by_hand():
    vals = [2.0, 0.5, 0.4, -1.0, -0.5, 2.0]

    assert render_arch._plot_gate(vals, on=1.0, off=0.0) == [
        True,      # crossed on
        True,      # inside the band: holds
        True,      # still inside: still holds
        False,     # clean exit below off
        False,     # back inside the band from below: still off
        True,      # crossed on again
    ]


def test_a_span_gating_on_a_missing_series_is_refused():
    spec = _plot(spans=[{"label": "x", "gate": {"series": "nope", "on": 1, "off": 0}}])

    with pytest.raises(render_arch.ArchPlotError, match="nope"):
        render_arch.render_plot(spec)


def _gutter_ys(svg):
    """Baselines of the labels in the right-hand gutter."""
    xs = [(float(m.group(1)), float(m.group(2)))
          for m in re.finditer(r'<text class="nds" x="([\d.]+)" y="([\d.]+)"', svg)]
    right = max(x for x, _ in xs)
    return sorted(y for x, y in xs if x == right)


def test_gutter_labels_never_land_on_each_other():
    """The real defect: a series endpoint was nudged clear of other series but
    not of the threshold labels, so 'price' and 'Close, actual' overprinted and
    both became unreadable."""
    spec = _plot(
        series=[{"label": "price", "tone": "ink", "points": [5.0, 5.0]}],
        thresholds=[{"value": 5.0, "label": "Close, actual", "tone": "good"},
                    {"value": 5.0, "label": "Close, recorded", "tone": "bad"}])

    ys = _gutter_ys(render_arch.render_plot(spec))

    assert len(ys) == 3
    assert all(b - a >= 10 for a, b in zip(ys, ys[1:])), ys


def test_the_right_gutter_is_wide_enough_for_its_longest_label():
    """Clipping was the first thing that went wrong by hand: the label was drawn
    past the viewBox and simply vanished."""
    long = "a considerably longer series label than usual"
    svg = render_arch.render_plot(_plot(series=[{"label": long, "tone": "good",
                                                 "points": [0, 1]}]))
    width = float(re.search(r'viewBox="0 0 ([\d.]+)', svg).group(1))
    x = max(float(m.group(1))
            for m in re.finditer(r'<text class="nds" x="([\d.]+)"', svg))

    assert x + len(long) * 5.6 <= width


def test_an_empty_plot_is_refused():
    with pytest.raises(render_arch.ArchPlotError):
        render_arch.render_plot({"series": []})


# --- any document, not just ARCHITECTURE -------------------------------------
# The renderer grew a second job: the site build feeds it README, SECURITY,
# ROADMAP and the rest. Everything below is about it naming those correctly,
# because a page titled "Architecture" that is actually the threat model is
# worse than no page.

def test_frontmatter_title_wins():
    meta = {"title": "Threat Level"}
    assert render_arch._doc_title(Path("docs/THREAT_LEVEL.md"), meta) == "Threat Level"


def test_conventional_filenames_get_readable_titles():
    """Root docs are exempt from frontmatter, so the filename is all there is."""
    t = render_arch._doc_title
    assert t(Path("README.md"), {}) == "Overview"
    assert t(Path("LESSONS_LEARNED.md"), {}) == "Lessons learned"
    assert t(Path("SECURITY.md"), {}) == "Security"


def test_an_unrecognised_filename_still_reads_as_words():
    """Falling back to a raw stem would put MIGRATION_NOTES in a browser tab."""
    assert render_arch._doc_title(Path("MIGRATION_NOTES.md"), {}) == "Migration Notes"


def test_repo_name_comes_from_the_repo_not_the_path_depth(tmp_path):
    """Regression: `md_path.parents[1].name` assumed every doc lives under
    docs/. For a doc at the repo root that resolved to the *parent directory of
    the repo*, so eeva-exec/SECURITY.md rendered as belonging to `nephilim`."""
    repo = tmp_path / "acme-exec"
    (repo / "docs").mkdir(parents=True)
    root_doc, nested_doc = repo / "SECURITY.md", repo / "docs" / "ROADMAP.md"

    assert render_arch._repo_name(root_doc, repo) == "acme-exec"
    assert render_arch._repo_name(nested_doc, repo) == "acme-exec"


def test_source_label_is_repo_relative(tmp_path):
    repo = tmp_path / "acme"
    (repo / "docs").mkdir(parents=True)

    assert render_arch._source_label(repo / "SECURITY.md", repo) == "SECURITY.md"
    assert render_arch._source_label(repo / "docs" / "ROADMAP.md", repo) == "docs/ROADMAP.md"


def test_a_non_architecture_doc_renders_with_its_own_identity(tmp_path):
    repo = tmp_path / "acme"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "THREAT_LEVEL.md").write_text(
        "---\ntitle: Threat Level\nstatus: active\ncreated: 2026-01-01\n"
        "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: acme\n---\n\n"
        "## Rating\n\nHigh.\n", encoding="utf-8")

    page = render_arch.build(repo / "docs" / "THREAT_LEVEL.md", repo)

    assert "<title>acme — Threat Level</title>" in page
    assert "DOCS/THREAT_LEVEL.MD" in page
    assert "ARCHITECTURE" not in page.split("<footer>")[1]


# --- the multi-repo site build -----------------------------------------------
# Loaded by path, not by name: `site` is a stdlib module, and the local helper
# `_spec` in this file is a diagram spec — both collide with the obvious names.
def _load_site_module():
    import importlib.util
    s = importlib.util.spec_from_file_location("cms_site", TOOLS / "site.py")
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    return mod


cms_site = _load_site_module()


def _repo(tmp_path, name, files):
    r = tmp_path / name
    (r / "docs").mkdir(parents=True)
    for rel, text in files.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return r


def test_a_page_exists_only_when_its_sources_do(tmp_path):
    """The rule the whole design rests on: no per-repo configuration, and no nav
    entry promising a page that was never written."""
    repo = _repo(tmp_path, "acme", {"README.md": "# Acme\n\nHi.\n"})

    cfg = {"repos": [{"path": "acme"}]}
    repos = cms_site.discover(tmp_path, cfg)
    slugs = {p["slug"] for p in repos[0]["pages"]}

    assert "index" in slugs
    assert "running" not in slugs      # no DEPLOYMENT/OPERATIONS/... exists
    assert "architecture" not in slugs


def test_adding_a_document_adds_its_page(tmp_path):
    repo = _repo(tmp_path, "acme", {"README.md": "# Acme\n"})
    cfg = {"repos": [{"path": "acme"}]}
    assert "running" not in {p["slug"] for p in cms_site.discover(tmp_path, cfg)[0]["pages"]}

    (repo / "docs" / "DEPLOYMENT.md").write_text("# Deploy\n", encoding="utf-8")

    assert "running" in {p["slug"] for p in cms_site.discover(tmp_path, cfg)[0]["pages"]}


def test_unclaimed_docs_become_reference_pages(tmp_path):
    """Otherwise the site silently drops most of a research-heavy repo, and every
    link pointing into it dies."""
    _repo(tmp_path, "acme", {"README.md": "# Acme\n",
                             "docs/FINDINGS_2026.md": "# Findings\n",
                             "docs/SPEC.md": "# Spec\n"})

    pages = cms_site.discover(tmp_path, {"repos": [{"path": "acme"}]})[0]["pages"]
    refs = [p for p in pages if p.get("reference")]

    assert {p["title"] for p in refs} == {"FINDINGS 2026", "SPEC"}
    assert any(p["slug"] == "reference" for p in pages)


def test_a_link_to_a_document_in_the_site_is_rewritten(tmp_path):
    src = tmp_path / "acme" / "docs" / "A.md"
    src.parent.mkdir(parents=True)
    target = tmp_path / "acme" / "docs" / "B.md"
    target.write_text("# B\n", encoding="utf-8")
    linkmap = {target.resolve(): "acme/b.html"}

    out = cms_site.rewrite_links("see [B](B.md) now", src, linkmap, "acme/a.html")

    assert out == "see [B](b.html) now"


def test_a_link_to_nothing_is_unwrapped_rather_than_left_dead(tmp_path):
    """A dead link tells the reader something is there when nothing is. The words
    survive; only the false promise goes."""
    src = tmp_path / "acme" / "docs" / "A.md"
    src.parent.mkdir(parents=True)

    out = cms_site.rewrite_links("see [the config](../config/x.json) now",
                                 src, {}, "acme/a.html")

    assert out == "see the config now"


def test_external_and_anchor_links_are_untouched(tmp_path):
    src = tmp_path / "acme" / "docs" / "A.md"
    src.parent.mkdir(parents=True)
    md = "[x](https://example.com) and [y](#section)"

    assert cms_site.rewrite_links(md, src, {}, "acme/a.html") == md


def test_a_merged_page_does_not_repeat_the_documents_own_title(tmp_path):
    """The merge supplies the section heading; keeping the source's `# Security`
    printed it twice and listed both in the in-page nav."""
    repo = _repo(tmp_path, "acme", {
        "SECURITY.md": "# Security\n\nposture text\n",
        "docs/THREAT_LEVEL.md": "# Threat Level: High\n\nrating text\n"})

    md = cms_site.merge_sources([repo / "SECURITY.md",
                                 repo / "docs" / "THREAT_LEVEL.md"], repo)

    assert md.count("## Security") == 1
    assert "# Security\n\nposture" not in md
    assert "posture text" in md and "rating text" in md


def test_a_repo_that_does_not_exist_fails_loudly(tmp_path):
    with pytest.raises(cms_site.SiteError, match="does not exist"):
        cms_site.discover(tmp_path, {"repos": [{"path": "nope"}]})


def test_no_repos_configured_is_an_error_not_an_empty_site(tmp_path):
    with pytest.raises(cms_site.SiteError, match="no repos"):
        cms_site.discover(tmp_path, {"repos": []})


# --- search ------------------------------------------------------------------

def test_the_index_covers_every_page_that_has_sources(tmp_path):
    _repo(tmp_path, "acme", {"README.md": "# Acme\n\nthe overview\n",
                             "docs/ARCHITECTURE.md": "# Arch\n\nthe shape\n",
                             "docs/NOTES.md": "# Notes\n\nloose notes\n"})
    repos = cms_site.discover(tmp_path, {"repos": [{"path": "acme"}]})

    idx = cms_site.build_search_index(repos)
    urls = {e["u"] for e in idx}

    assert "acme/index.html" in urls
    assert "acme/architecture.html" in urls
    assert "acme/ref-notes.html" in urls        # reference docs are searchable
    assert not any(e["u"].endswith("reference.html") for e in idx)  # the index page has no text


def test_indexed_text_drops_code_fences_and_markup(tmp_path):
    md = ("---\ntitle: T\n---\n\n# H\n\nreal **words** here\n\n"
          "```python\nsecret_token = 'not prose'\n```\n\nmore words\n")

    txt = cms_site._plain_text(md)

    assert "real words here" in txt and "more words" in txt
    assert "secret_token" not in txt      # fenced code is not prose
    assert "**" not in txt


def test_headings_are_indexed_for_ranking(tmp_path):
    _repo(tmp_path, "acme", {"README.md": "# Acme\n\n## Funding mechanics\n\nbody\n"})
    repos = cms_site.discover(tmp_path, {"repos": [{"path": "acme"}]})

    entry = next(e for e in cms_site.build_search_index(repos)
                 if e["u"] == "acme/index.html")

    assert "Funding mechanics" in entry["h"]


def test_the_search_page_carries_its_index_inline(tmp_path):
    """Inlined rather than fetched, so the page works from a file:// URL like
    every other page on the site."""
    _repo(tmp_path, "acme", {"README.md": "# Acme\n\ndistinctiveword\n"})
    repos = cms_site.discover(tmp_path, {"repos": [{"path": "acme"}]})

    page = cms_site.render_search_page(repos, {"title": "T"})

    assert "distinctiveword" in page
    assert "fetch(" not in page and "XMLHttpRequest" not in page
