"""Tests for the declared-Python-floor checker.

Every case here is drawn from the failure that motivated the script rather than invented.
The repository promised "Python 3.9+" in its README while shipping a backslash inside an
f-string expression — PEP 701 syntax, legal only from 3.12. The consequence was not a
degraded feature: `pytest` could not *collect* on 3.9, 3.10 or 3.11, so the whole suite
was unavailable on the majority of interpreters. CI missed it because all three jobs
pinned 3.12; the matrix varied the OS and never the Python.

Two traps are pinned deliberately because both cost real time:

- `ast.parse(feature_version=(3, 9))` does **not** reject the construct. PEP 701 changed
  the tokenizer, and `feature_version` only gates grammar. The obvious guard is the one
  that cannot work, so `test_feature_version_alone_would_miss_it` records why.
- Adjacent string literals merge into one `JoinedStr`, so an AST-derived delimiter can
  belong to a *different* fragment than the expression being judged. That produced a false
  positive on correct code in the first draft of this checker;
  `test_adjacent_literal_concatenation_is_not_a_finding` is its regression test.
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "python_floor.py"


def _load():
    spec = importlib.util.spec_from_file_location("python_floor", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pf = _load()

NEEDS_312 = sys.version_info >= (3, 12)


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _w(root: Path, name: str, body: str) -> Path:
    p = root / name
    p.write_text(body, encoding="utf-8")
    return p


# --- the constructs the floor forbids -------------------------------------------------

def test_clean_file_passes(tmp_path):
    _w(tmp_path, "ok.py", 'cls = " on"\nx = f"<a{cls}>"\n')
    r = _run("--repo", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 failing" in r.stdout


def test_backslash_in_fstring_expression_is_caught(tmp_path):
    """The construct that actually broke the repo — caught on every interpreter.

    Which *path* catches it differs by version, and both are correct. Below 3.12 the file
    does not parse, so the interpreter's own SyntaxError is reported; that is the stronger
    signal. From 3.12 the file parses fine and only the tokenize pass can see it. The test
    asserts the outcome on both and the wording only where this pass is the one running.
    """
    _w(tmp_path, "bad.py", 'p = {"s": "x"}\ny = f\'{" class=\\"on\\"" if p else ""}\'\n')
    r = _run("--repo", str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "bad.py" in r.stdout
    if NEEDS_312:
        assert "backslash in an f-string expression" in r.stdout
        assert "bind the value to a name" in r.stdout
    else:
        assert "cannot include a backslash" in r.stdout


def test_quote_reuse_in_fstring_expression_is_caught(tmp_path):
    if not NEEDS_312:
        # Below 3.12 the file cannot parse at all, which check_file reports instead —
        # a stronger signal, asserted by test_new_grammar_is_caught_at_the_floor's sibling
        # path. Nothing to add here.
        return
    # Reuse means the *same* quote as the literal's own delimiter. Mixing styles
    # (f'{d["k"]}') has always been legal and must not be flagged — see the
    # mixed-quote assertion below.
    _w(tmp_path, "bad.py", "d = {'k': 1}\ny = f'{d['k']}'\n")
    r = _run("--repo", str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "own quote character" in r.stdout


def test_mixed_quote_styles_are_legal_and_not_flagged():
    """The rule is reuse of the *same* delimiter, not any nested quote at all."""
    assert pf.fstring_findings('d = {"k": 1}\ny = f\'{d["k"]}\'\n') == []


def test_multiline_fstring_expression_is_caught(tmp_path):
    if not NEEDS_312:
        return
    _w(tmp_path, "bad.py", 'a = 1\nb = 2\ny = f"{a\n + b}"\n')
    r = _run("--repo", str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "spans multiple lines" in r.stdout


def _host_parses(src: str) -> bool:
    """Whether the interpreter running the tests can parse this at all."""
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False


def test_new_grammar_is_caught_at_the_floor(tmp_path):
    """`match` is 3.10 grammar, so a 3.9 floor must reject it.

    The second assertion is conditional, and the reason is the third distinct way
    `feature_version` has misled this module — it is worth stating rather than working
    around. **`feature_version` can only make the parser stricter, never more permissive.**
    Running on 3.9, `ast.parse(src, feature_version=(3, 10))` still cannot parse `match`,
    because the host parser has no such grammar to enable. It is not a version simulator;
    it is a restriction on the host's own parser.

    So "a higher floor accepts it" is only a meaningful claim on a host that can parse it,
    and asserting it unconditionally fails on exactly the oldest interpreter this matrix
    exists to cover. Caught by CI on 3.9 — the job doing its job, on my test rather than
    on the shipped code.
    """
    match_src = "def f(x):\n    match x:\n        case 1:\n            return 2\n"
    _w(tmp_path, "m.py", match_src)

    r = _run("--repo", str(tmp_path), "--floor", "3.9")
    assert r.returncode == 1, r.stdout + r.stderr

    if _host_parses(match_src):
        r_ok = _run("--repo", str(tmp_path), "--floor", "3.10")
        assert r_ok.returncode == 0, r_ok.stdout + r_ok.stderr


def test_feature_version_cannot_grant_grammar_the_host_lacks():
    """Pins the limitation itself, so the conditional above is never 'simplified' away."""
    match_src = "def f(x):\n    match x:\n        case 1:\n            return 2\n"
    if _host_parses(match_src):
        return  # 3.10+: nothing to demonstrate here
    try:
        ast.parse(match_src, feature_version=(3, 10))
        raise AssertionError("feature_version unexpectedly upgraded the host parser")
    except SyntaxError:
        pass  # the documented behaviour, and the reason the assertion above is guarded


# --- stdlib newer than the floor --------------------------------------------------------

def test_module_level_import_of_newer_stdlib_is_caught(tmp_path):
    """The second defect in the same file: `import tomllib` (3.11) at module scope.

    Not a syntax error, so no parser catches it — the module simply raises
    ModuleNotFoundError on import, which takes the importing test module down at
    collection just as thoroughly.
    """
    _w(tmp_path, "s.py", "import tomllib\n\n\ndef go(t):\n    return tomllib.loads(t)\n")
    r = _run("--repo", str(tmp_path), "--floor", "3.9")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "tomllib" in r.stdout and "3.11" in r.stdout

    at_311 = _run("--repo", str(tmp_path), "--floor", "3.11")
    assert at_311.returncode == 0, at_311.stdout + at_311.stderr


def test_deferred_import_is_the_fix_and_is_not_flagged(tmp_path):
    """A check that punishes its own remedy gets switched off."""
    _w(tmp_path, "s.py",
       "def go(t):\n"
       "    try:\n"
       "        import tomllib\n"
       "    except ModuleNotFoundError:\n"
       "        return None\n"
       "    return tomllib.loads(t)\n")
    r = _run("--repo", str(tmp_path), "--floor", "3.9")
    assert r.returncode == 0, r.stdout + r.stderr


def test_guarded_top_level_import_is_not_flagged(tmp_path):
    """`try: import tomllib / except ImportError:` at module scope is also a real degrade."""
    _w(tmp_path, "s.py",
       "try:\n    import tomllib\nexcept ModuleNotFoundError:\n    tomllib = None\n")
    r = _run("--repo", str(tmp_path), "--floor", "3.9")
    assert r.returncode == 0, r.stdout + r.stderr


def test_from_import_of_newer_stdlib_is_caught(tmp_path):
    _w(tmp_path, "s.py", "from tomllib import loads\n")
    r = _run("--repo", str(tmp_path), "--floor", "3.9")
    assert r.returncode == 1, r.stdout + r.stderr


# --- the two traps ---------------------------------------------------------------------

def test_feature_version_alone_would_miss_it():
    """Why the checker cannot rely on `feature_version`, recorded so it is not 'simplified'.

    PEP 701 is a tokenizer change. `ast.parse` on a modern interpreter accepts the new
    f-string syntax whatever floor is requested, so the guard that looks sufficient is
    exactly the one that fails silently.
    """
    if not NEEDS_312:
        return
    src = 'p = {"s": "x"}\ny = f\'{" class=\\"on\\"" if p else ""}\'\n'
    ast.parse(src, feature_version=(3, 9))  # must NOT raise — that is the whole point
    assert pf.fstring_findings(src), "the tokenize-based pass is what has to catch it"


def test_adjacent_literal_concatenation_is_not_a_finding():
    """Implicit concatenation must not borrow a neighbouring fragment's delimiter.

    `"</div>" f'...{d["k"]}...' "</div>"` is one JoinedStr whose source segment starts with
    a double quote, while the expression sits in a single-quoted fragment where `"` is
    legal. Reading the delimiter off the merged node reported correct code as broken.
    """
    src = 'd = {"k": 1}\ns = (\n    "</div>"\n    f\'<span>{d["k"]}</span>\'\n    "</div>"\n)\n'
    assert pf.fstring_findings(src) == []


# --- exit-code discipline (the repo's own invariant) ------------------------------------

def test_missing_directory_is_undetermined_not_a_pass(tmp_path):
    r = _run("--repo", str(tmp_path / "nope"))
    assert r.returncode == 2, r.stdout + r.stderr


def test_unparseable_floor_is_undetermined_not_a_pass(tmp_path):
    _w(tmp_path, "ok.py", "x = 1\n")
    r = _run("--repo", str(tmp_path), "--floor", "three-nine")
    assert r.returncode == 2, r.stdout + r.stderr


def test_empty_tree_is_undetermined_not_a_pass(tmp_path):
    r = _run("--repo", str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr


def test_virtualenvs_and_caches_are_pruned(tmp_path):
    _w(tmp_path, "ok.py", "x = 1\n")
    vendored = tmp_path / ".venv" / "lib"
    vendored.mkdir(parents=True)
    (vendored / "new_syntax.py").write_text(
        "def f(x):\n    match x:\n        case 1:\n            return 2\n", encoding="utf-8")
    r = _run("--repo", str(tmp_path), "--floor", "3.9")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 file(s) scanned" in r.stdout


# --- the promise and the enforcement may not drift --------------------------------------

def test_readme_states_the_floor_the_checker_enforces():
    """Prose and enforcement share one number, or the promise rots unnoticed."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    declared = "Python {}.{}+".format(*pf.DECLARED_FLOOR)
    assert declared in readme, "README must state {!r}".format(declared)


def test_this_repository_honours_its_own_floor():
    r = _run("--repo", str(REPO_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
