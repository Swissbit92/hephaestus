# Contributing to hephaestus

Thanks for sharpening the workshop. A few rules keep the marketplace clean and releasable.

## Ground rules

- **No secrets, ever.** This repo must contain no references to any
  employer/secret system (the generic plugins were extracted clean-room from a private
  fork). Run `scripts/check-public-safe.sh` before every commit — a non-zero exit blocks the
  change. The generic↔domain seam is enforced separately by `tests/test_seam.py`. When
  porting a pattern from a private source, re-author it from scratch: **patterns in, private
  content out.**
- **`main` stays releasable.** Do feature work on short-lived branches and integrate via
  merge or PR. See the branch model in [CLAUDE.md](CLAUDE.md).
- **Tests green.** `pytest -q` must pass with no regression before you open a PR. CI
  (`.github/workflows/ci.yml`) runs the suite + `validate_manifests.py` +
  `check-public-safe.sh` on every push/PR to `main`. The live skill-eval tier is a
  separate, opt-in CI job (needs an `ANTHROPIC_API_KEY` secret) — see the workflow comments
  and `evals/README.md`.
- **Skills make behavioral claims → add an eval.** When a skill gains a falsifiable
  behavior (e.g. "refuses X", "never writes without approval"), add a scenario to
  `evals/scenarios.json` (see [evals/README.md](evals/README.md)). The eval harness asserts
  it against a real fixture rather than trusting the prose. If the edit *describes* behaviour
  already implemented in scripts rather than *instructing* a model, name the deterministic
  tests that pin it instead — and check that at least one of them fails when the description
  stops being true. `.crucible/evidence.json` spells out both branches; pick one out loud.
- **Never read `st_mtime` in shipped plugin code.** git neither records nor restores
  modification times, so a clone stamps every file with the checkout time and anything
  derived from mtime reports every file as brand new on someone else's machine — while
  looking perfectly healthy. Use the git committer date
  (`plugins/crucible/skills/cms/scripts/doc_age.py`) or a date carried in the file's content.
  Enforced by `scripts/checks/mtime_is_never_a_clock.sh`.
- **A check nobody has watched fail is not a check.** Before you trust a new gate, test or
  prediction-check, reintroduce the defect and confirm it goes red. This repo settled three
  predictions on instruments that could not have distinguished success from failure, so
  `predictions.py record` now requires `--baseline` — what the check shows before the change.
- **Exit 2 when you could not check.** `0` means it passed, `1` means it failed, `2` means
  the check could not run — a malformed config, a missing tool, an unreadable input. Folding
  the third into `0` is how a tool that has stopped working keeps reporting clean; folding it
  into `1` turns a missing capability into an accusation. `sync.py` returned `0` for any
  facts file outside its YAML subset until this was fixed.

## Adding a skill

Run `/crucible:skill-craft` — it scaffolds a pre-structured `SKILL.md` (via
`plugins/crucible/scripts/new_skill.py`) and coaches each section against the repo's authoring patterns
(exemplar-first negatives, hard-gate vs. best-effort, code-backed helpers, progressive
disclosure, …), citing shipped skills as examples. Or run the scaffolder directly:

```bash
python3 plugins/crucible/scripts/new_skill.py <kebab-name> --description "<trigger-focused one-liner>"
```

## Adding a plugin

1. Create `plugins/<name>/.claude-plugin/plugin.json` (`name`, `description`, `version`,
   `author`, `license`, `keywords`; `hooks`/`mcpServers`/`userConfig` as needed).
2. Add the plugin's content (`skills/`, `commands/`, `agents/`, `servers/` …).
3. Register it in `.claude-plugin/marketplace.json` (`name`, `source`, `description`,
   `category`, `tags`).
4. Give it a README (the top-level `crucible` plugin is the exception — it uses the
   repo-root README) and, if it needs external config, a `/setup` command + first-run hook.
5. Keep it vendor-neutral and, where possible, zero-config so anyone can try it instantly.

## Local development (live-load)

Marketplace-installed plugins load from a **version-pinned cache copy**, so edits to the
source don't appear on `/reload-plugins` until you bump the version and reinstall. For fast
iteration, load the plugin **directly** from your clone with `--plugin-dir` — no cache, no
reinstall, no git pull (and the private-repo auth bug is irrelevant, since nothing touches
git):

```bash
claude --plugin-dir /absolute/path/to/hephaestus/plugins/crucible
# edit the plugin, then in-session:
/reload-plugins   # changes are live immediately
```

A `--plugin-dir` plugin takes precedence over the same-named installed one for that
session, so the marketplace install stays in place as your released fallback. To have it on
by default, bake the flag into a shell alias (escape hatch: `command claude` runs without
it):

```bash
alias claude='claude --plugin-dir /absolute/path/to/hephaestus/plugins/crucible'
```

This is **per-developer** — the path is your local clone, so it is not (and cannot be) part
of the plugin's distributed setup. End users install the released version from the
marketplace and never need it.

## Releasing

The `version` in a plugin's `plugin.json` is what triggers updates for installed users —
pushing commits without bumping it does nothing for them. Use the helper, which keeps the
manifest version and git tag in lockstep:

```bash
scripts/release.sh <plugin> patch            # 0.1.0 -> 0.1.1
scripts/release.sh <plugin> minor            # 0.1.0 -> 0.2.0
scripts/release.sh <plugin> major            # 0.1.0 -> 1.0.0
scripts/release.sh <plugin> 1.2.3            # explicit version
scripts/release.sh <plugin> patch --dry-run  # preview, change nothing
```

It refuses to run unless you're on `main` with a clean tree, **runs the release gates**
(`pytest`, `check-public-safe.sh`, `validate_manifests.py` — ADR-002 promoted the middle
one to a release gate and the script did not run it), validates the plugin, then commits,
tags `<plugin>-v<x.y.z>`, pushes, creates a GitHub release, and **fast-forwards `dev` to
`main`** so the next feature branch does not fork from a base missing the version bump.

**`main` requires status checks and enforces them on admins**, so a release commit cannot
be pushed directly — a fresh commit has no checks yet. The script detects this *before*
touching anything and prints the PR route, rather than bumping the manifest and tagging
locally and then failing, which is the half-completed release its own comments warn about.

**Notes are scoped by excluding sibling plugins, not by including the plugin's directory.**
A release routinely lands work outside its own tree — a gate in `scripts/`, tests in
`tests/`, an ADR in `docs/` — and the old `-- plugins/<name>` filter could see none of it:
5 of 11 non-merge commits were dropped across three releases before this was fixed. Merge
subjects and `Co-Authored-By` / `Claude-Session` trailers are stripped. A commit touching
*only* another plugin is excluded; one touching another plugin *and* shared tooling is
included, because it genuinely did work this release contains. When no commits match at
all, the script says so on stderr rather than quietly emitting "Maintenance release".

## Docs

Markdown under any `docs/` directory carries cms frontmatter (the `cms` skill scaffolds and
lints it). Root files (README, CLAUDE, CHANGELOG, CONTRIBUTING) do not.
