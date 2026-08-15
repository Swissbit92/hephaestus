# cms — the evidence behind the rules

Every rule `SKILL.md` states was adopted for a reason, and the reasons are cited here
rather than inline: they are what you read when deciding whether a rule still applies
or should change, which is rare, while the rules themselves are read every time the
skill loads. Keeping provenance here is the same progressive-disclosure move the skill
asks of the documents it lints.

- **ETH Zurich finding:** auto-generated CLAUDE.md content is ~20% more expensive and 0.5-2% worse on task success than hand-curated. This skill **moves structure, does not paraphrase prose**.
- **Plain links are lazy, @path is eager:** discovered during a live migration when `@path` was incorrectly introduced as a "lazy-loading" mechanism. It is not. In the ecosystem this skill was built for, converting all `@path` to plain links cut session token load by ~39% (836 → 507 total CLAUDE.md lines across 6 repos).
- **Codex 32 KiB cap + proximity hierarchy:** Claude loads the nearest CLAUDE.md first. Keep root lean, per-repo specialised, avoid duplication.
- **UK Gov staleness pattern:** `last_reviewed_on + review_in → review_by` exposes doc expiry machine-readably.
- **GitLab/Datadog tiered CI:** Error blocks, Warning informs — keeps enforcement trustworthy at scale.
- **Nx/Kubernetes creation-time enforcement:** scaffold correctly at `/cms init` rather than audit retroactively.
- **Skill content is lazy-loaded correctly:** skill descriptions are small and load at session start; the full skill body only loads on invocation. The right pattern for large reference content needed only for specific tasks.
