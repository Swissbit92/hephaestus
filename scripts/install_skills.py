#!/usr/bin/env python3
"""Install this marketplace's skills into agents that read `SKILL.md` directly.

Claude Code installs plugins — a container carrying skills, commands, agents, hooks and MCP
servers — through its own marketplace mechanism, and this script is not needed for it. Codex
and Pi have no equivalent container: they discover **skill directories**. So the portable
subset is exactly the skills, and everything else in a plugin is Claude Code only.

That asymmetry is reported rather than hidden. A skill that quietly loses its hook in one
agent is worse than one that never loaded: it appears to work, and the guarantee the hook
was providing is simply absent. `--report` lists what will not travel, per agent.

Targets, and why each path:

    claude   ~/.claude/skills          personal skills, alongside installed plugins
    codex    ~/.codex/skills           discovered by name+description, invoked with `$name`
    pi       ~/.pi/agent/skills        global discovery

Linking beats copying: a link keeps every agent on one source of truth, so a fix lands
everywhere at once and no agent drifts onto a stale copy. On Windows a symlink needs
Developer Mode or elevation, so the script degrades to a copy **and says so** — a silent
copy would be the drift it is trying to prevent.

Nothing is written without `--apply`. The default prints the plan.

Exit codes:
    0 - planned or applied cleanly
    1 - at least one target could not be installed
    2 - could not determine (no skills found, unwritable home). NOT a success.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

AGENTS: Dict[str, Path] = {
    "claude": Path(".claude") / "skills",
    "codex": Path(".codex") / "skills",
    "pi": Path(".pi") / "agent" / "skills",
}

# What a plugin carries that a skills-only agent cannot receive. Listed so the gap is
# stated at install time rather than discovered as a missing guarantee later.
NOT_PORTABLE = {
    "commands": "slash commands",
    "agents": "subagents",
    "hooks": "hooks (declared in plugin.json)",
    ".mcp.json": "MCP servers",
}


def _utf8_stdio() -> None:
    """Force UTF-8 on the streams this script writes to.

    A Windows console defaults to a legacy codepage, so a single arrow in otherwise
    successful output raises UnicodeEncodeError after the work is done, turning a passing
    run into exit 1.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def find_skills(repo: Path) -> List[Path]:
    """Every skill directory in the marketplace, as the directory holding its SKILL.md."""
    plugins = repo / "plugins"
    if not plugins.is_dir():
        return []
    return sorted({p.parent for p in plugins.rglob("SKILL.md")})


def non_portable(repo: Path) -> List[Tuple[str, str]]:
    """Plugin-level assets that exist here and cannot travel to a skills-only agent."""
    out = []
    plugins = repo / "plugins"
    for plugin in sorted(p for p in plugins.iterdir() if p.is_dir()):
        for marker, label in NOT_PORTABLE.items():
            if marker == "hooks":
                manifest = plugin / ".claude-plugin" / "plugin.json"
                if manifest.is_file() and '"hooks"' in manifest.read_text(encoding="utf-8"):
                    out.append((plugin.name, label))
            elif (plugin / marker).exists():
                out.append((plugin.name, label))
    return out


def link_or_copy(source: Path, dest: Path) -> str:
    """Point dest at source. Returns the method actually used: 'link' or 'copy'."""
    if dest.is_symlink() or dest.exists():
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        else:
            shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.symlink_to(source, target_is_directory=True)
        return "link"
    except (OSError, NotImplementedError):
        # Windows without Developer Mode, or a filesystem that has no symlinks.
        shutil.copytree(source, dest)
        return "copy"


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="marketplace root")
    parser.add_argument("--agent", default="all", choices=sorted(AGENTS) + ["all"],
                        help="which agent to install for (default: all)")
    parser.add_argument("--home", default=None,
                        help="override the home directory (testing, or a non-standard setup)")
    parser.add_argument("--apply", action="store_true",
                        help="actually write; without it the plan is printed and nothing changes")
    parser.add_argument("--report", action="store_true",
                        help="also list what a skills-only agent will NOT receive")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    skills = find_skills(repo)
    if not skills:
        print("no SKILL.md found under {}/plugins".format(repo.as_posix()), file=sys.stderr)
        return 2

    home = Path(args.home).resolve() if args.home else Path(os.path.expanduser("~"))
    if not home.is_dir():
        print("home is not a directory: {}".format(home.as_posix()), file=sys.stderr)
        return 2

    targets = sorted(AGENTS) if args.agent == "all" else [args.agent]

    print("{} skill(s) from {}".format(len(skills), repo.as_posix()))
    if not args.apply:
        print("PLAN ONLY — nothing is written without --apply")

    failures = 0
    for agent in targets:
        root = home / AGENTS[agent]
        print()
        print("{}: {}".format(agent, root.as_posix()))
        if agent == "claude":
            print("  note: Claude Code installs this marketplace as plugins; linking bare "
                  "skills here is only for using them outside a plugin install")
        for skill in skills:
            dest = root / skill.name
            if not args.apply:
                print("  would install {}".format(skill.name))
                continue
            try:
                how = link_or_copy(skill, dest)
            except OSError as exc:
                failures += 1
                print("  FAILED {} — {}".format(skill.name, exc), file=sys.stderr)
                continue
            if how == "copy":
                print("  {} (COPIED — no symlink support here, so it will not track "
                      "updates)".format(skill.name))
            else:
                print("  {}".format(skill.name))

    if args.report or not args.apply:
        gaps = non_portable(repo)
        if gaps:
            print()
            print("NOT portable to codex/pi — these are Claude Code plugin features:")
            for plugin, label in gaps:
                print("  {:16s} {}".format(plugin, label))
            print("a skill whose hook does not travel still loads; the guarantee the hook "
                  "provided is simply absent, which is why this is printed rather than "
                  "assumed")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
