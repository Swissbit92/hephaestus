#!/usr/bin/env python3
"""Scaffold a new Claude Code skill, pre-structured with crucible's authoring patterns.

The emitted SKILL.md is not blank boilerplate — it lays out the high-leverage patterns
(exemplar-first negatives, good/bad pairs, hard-gate vs best-effort, visible reasoning,
progressive disclosure) as guided placeholders so the skill starts mature. Pair with the
`author-skill` skill, which explains each pattern with real exemplars.

Usage:
    new_skill.py <name> [--skills-dir DIR] [--description TEXT] [--force]

`<name>` is kebab-case (lowercase letters, digits, single hyphens). Default skills-dir is
the crucible plugin's skills/ directory.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_DEFAULT_SKILLS_DIR = (
    Path(__file__).resolve().parent.parent
    / "plugins" / "crucible" / "skills"
)

STUB = """\
---
name: {name}
description: {description}
---

<!-- Authoring guide: run `/crucible:author-skill` for the patterns + real exemplars.
     Delete these comments as you fill each section in. -->

You are <role>. <One sentence on the job this skill does and the outcome it produces.>

## When this fires
<The trigger. Be specific — the description above is what the model matches on.>

## Do-not (lead with the failure mode)
<Exemplar-first: the worst, most common mistake FIRST, as a concrete bad example.
 e.g. "Never X — it silently breaks Y." Show the wrong thing, then the right thing.>

```
# BAD  — <why it breaks>
<bad example>
# GOOD — <why this is right>
<good example>
```

## Steps / phases
1. <Step.>  <!-- Mark each gate: HARD GATE (must pass to proceed) vs best-effort. -->
2. <Step.>

## Output
<Concrete output schema — a fixed shape the result must take, specific enough to verify.
 Require visible reasoning where a judgement is made ("show why: ...").>

## Guardrails
- <Non-negotiable rule.>
- <Non-negotiable rule.>

<!-- If this skill needs heavy reference material, keep THIS file light and put the detail
     in a sibling file, loaded on demand: ${{CLAUDE_SKILL_DIR}}/REFERENCE.md
     (progressive disclosure). If it needs deterministic work, back it with a script in
     scripts/ rather than prose (code-backed). -->
"""


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


def create_skill(
    skills_dir: str | Path,
    name: str,
    description: str = "TODO: one-line, trigger-focused description",
    *,
    force: bool = False,
) -> Path:
    """Create <skills_dir>/<name>/SKILL.md from the stub. Returns the SKILL.md path.

    Raises ValueError on a bad name, or FileExistsError if the skill exists and not force.
    """
    if not valid_name(name):
        raise ValueError(
            f"invalid skill name {name!r}: use kebab-case (lowercase letters, digits, "
            "single hyphens), e.g. 'my-skill'"
        )
    skill_dir = Path(skills_dir) / name
    target = skill_dir / "SKILL.md"
    if target.exists() and not force:
        raise FileExistsError(f"skill already exists: {target} (use --force to overwrite)")
    skill_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(STUB.format(name=name, description=description))
    return target


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Scaffold a new Claude Code skill")
    ap.add_argument("name", help="skill name (kebab-case)")
    ap.add_argument("--skills-dir", default=str(_DEFAULT_SKILLS_DIR),
                    help="directory to create the skill under (default: crucible plugin skills/)")
    ap.add_argument("--description", default="TODO: one-line, trigger-focused description",
                    help="skill description (the trigger the model matches on)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing SKILL.md")
    args = ap.parse_args(argv)

    try:
        path = create_skill(args.skills_dir, args.name, args.description, force=args.force)
    except (ValueError, FileExistsError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    print(f"created {path}")
    print("Next: open it, run /crucible:author-skill for the patterns, fill the sections.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
