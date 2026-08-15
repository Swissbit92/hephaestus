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
  it against a real fixture rather than trusting the prose.

## Adding a skill

Run `/crucible:author-skill` — it scaffolds a pre-structured `SKILL.md` (via
`scripts/new_skill.py`) and coaches each section against the repo's authoring patterns
(exemplar-first negatives, hard-gate vs. best-effort, code-backed helpers, progressive
disclosure, …), citing shipped skills as examples. Or run the scaffolder directly:

```bash
python3 scripts/new_skill.py <kebab-name> --description "<trigger-focused one-liner>"
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

It refuses to run unless you're on `main` with a clean tree, validates the plugin, then
commits, tags `<plugin>-v<x.y.z>`, pushes, and creates a GitHub release with notes from the
commits since that plugin's last tag.

## Docs

Markdown under any `docs/` directory carries cms frontmatter (the `cms` skill scaffolds and
lints it). Root files (README, CLAUDE, CHANGELOG, CONTRIBUTING) do not.
