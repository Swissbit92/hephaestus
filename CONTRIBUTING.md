# Contributing to whetstone

Thanks for sharpening the workshop. A few rules keep the marketplace clean and releasable.

## Ground rules

- **Public-safe, always.** This repo is public. It must contain no references to any
  private or employer system. Run `scripts/check-public-safe.sh` before every commit — a
  non-zero exit blocks the change. When porting a pattern from a private source, re-author
  it from scratch in this repo's voice: **patterns in, private content out.**
- **`main` stays releasable.** Do feature work on short-lived branches and integrate via
  merge or PR. See the branch model in [CLAUDE.md](CLAUDE.md).
- **Tests green.** `pytest -q` must pass with no regression before you open a PR.

## Adding a plugin

1. Create `plugins/<name>/.claude-plugin/plugin.json` (`name`, `description`, `version`,
   `author`, `license`, `keywords`; `hooks`/`mcpServers`/`userConfig` as needed).
2. Add the plugin's content (`skills/`, `commands/`, `agents/`, `servers/` …).
3. Register it in `.claude-plugin/marketplace.json` (`name`, `source`, `description`,
   `category`, `tags`).
4. Give it a README and, if it needs external config, a `/setup` command + first-run hook.
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
