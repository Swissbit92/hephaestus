# {{REPO_NAME}} — Agent Context

{{ONE_LINE_PURPOSE}}

**Ecosystem context lives in the root — fetch it on demand, don't re-read on every turn.**
Root: [../CLAUDE.md](../CLAUDE.md) · Vision: [../VISION.md](../VISION.md) · Shared contracts: [../docs/shared/](../docs/shared/)

## Critical invariants (read first, every session)

- {{INVARIANT_1}}
- {{INVARIANT_2}}
- {{INVARIANT_3}}

## Where things live

| What | Where |
|------|-------|
| Architecture + module map | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Full CLI reference + conventions | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Roadmap | [docs/ROADMAP.md](docs/ROADMAP.md) |
| Lessons learned | [docs/LESSONS_LEARNED.md](docs/LESSONS_LEARNED.md) |
| Decisions (ADRs) | [docs/decisions/](docs/decisions/) |
| Changelog | [CHANGELOG.md](CHANGELOG.md) |
| Shared/cross-repo contracts (if any) | [../docs/shared/](../docs/shared/) |

## Quick commands

```bash
# Run
python3 -m {{REPO_NAME}}

# Tests (fast gate)
pytest -m "not e2e and not slow" -v

# Lint docs (via the whetstone cms skill)
python3 "${CLAUDE_PLUGIN_ROOT}/skills/cms/scripts/check.py" .
```

Full command reference: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

## Session management

- `/clear` between unrelated tasks · `/compact` before switching repos
- `/cms` for any .md edit or creation · `/develop` for all implementation work
