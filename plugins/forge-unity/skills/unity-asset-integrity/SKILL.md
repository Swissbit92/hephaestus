---
name: unity-asset-integrity
description: Check a Unity project's asset bookkeeping for the failures neither the compiler nor a test suite can see — source files the editor never imported, .meta records whose asset is gone, components bound to a script that no longer resolves, and behaviours wired to nothing. Use before merging Unity work, when a new script does not appear in menus or cannot be attached, when a component silently does nothing at runtime, or as a recurring health check. Reports; never repairs.
---

You check the **second record** Unity keeps of every asset, and report where it disagrees
with the disk. You never edit a `.meta` file.

## Why this and not a compiler

Unity's `.meta` files are what the editor believes, and the editor acts on that belief
rather than on the filesystem. When the two disagree, **nothing errors**:

| Condition | What you actually observe |
|---|---|
| Source file with no `.meta` | Not imported, so it does not compile, does not appear in menus, and cannot be attached. The file looks completely normal in git and in a listing |
| `.meta` whose asset is gone | A record pointing at nothing, left by a delete outside the editor |
| `m_Script: {fileID: 0}` | A component bound to nothing. It serialises fine, loads fine, and does nothing at runtime |
| Behaviour referenced by no scene or prefab | Either dead code or a feature mid-construction — and the probe cannot tell which |

None of these fail a build. None fail a test. None appear in a diff review. That is the
entire case for checking them mechanically, and it is the one Unity-specific thing that has
not changed across engine releases.

## Run it

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/asset_integrity.py" --root Assets/_Project
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/asset_integrity.py" --root Assets --json
```

`--root` is the **first-party** source root. Point it at your own code, not at `Assets/`
wholesale — a vendored SDK's bookkeeping is its author's problem, and including it buries
your findings under theirs.

`0` clean · `1` problems found · `2` could not determine (bad root) — which is not a pass.

## Reading the output

**Three of the four are defects. The fourth is a question**, and it does not affect the exit
code on purpose. `unwired` means a behaviour's GUID appears in no scene, prefab or asset —
which is exactly what a half-built feature looks like, and exactly what dead code looks
like. Report it as a question and let a human answer; deleting on this signal alone is how a
feature in progress gets removed.

The check already excludes what cannot be wired — interfaces, enums, structs, static
helpers, and editor tooling invoked from menus. On a real project that filter took the list
from 29 entries to 1, which is the difference between a report someone reads and one they
skim.

## Never repair by hand

**Editing a `.meta` is how a GUID ends up duplicated across two assets** — which breaks
every reference to both, and cannot be undone by editing it back, because the references
now point at an ambiguous id. Repair goes through the editor or the importer API:

- **No `.meta`** — open the editor and let it import, or refresh assets.
- **Orphan `.meta`** — delete through the editor.
- **`fileID: 0`** — reassign the script in the inspector. Until then that object does
  nothing at runtime, however correct it looks.

## When to run it

- **Before merging any Unity work.** It is seconds, needs no running editor, and catches
  the class of defect that otherwise ships.
- **When a new script "does not exist"** — no menu item, cannot be attached, a missing-type
  error that looks like a compile failure. Check for a missing `.meta` before debugging the
  code, which is fine.
- **After any file operation outside the editor** — a move, a rename, a merge, a revert.
  This is where orphans come from.
- **On a schedule**, as a health check whose result can be trended.
