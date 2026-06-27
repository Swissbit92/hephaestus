# Contributing to whetstone

Thanks for sharpening the workshop. A few rules keep the marketplace clean and releasable.

## Ground rules

- **Public-safe, always.** This repo is public. It must contain no references to any
  private or employer system. Run `scripts/check-public-safe.sh` before every commit — a
  non-zero exit blocks the change. When porting a pattern from a private source, re-author
  it from scratch in this repo's voice: **patterns in, private content out.**
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

Run `/whetstone:author-skill` — it scaffolds a pre-structured `SKILL.md` (via
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
4. Give it a README (the top-level `whetstone` plugin is the exception — it uses the
   repo-root README) and, if it needs external config, a `/setup` command + first-run hook.
5. Keep it vendor-neutral and, where possible, zero-config so anyone can try it instantly.

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
