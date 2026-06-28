"""Baseline freeze + compare — the match-or-beat gate at the report level. Pure stdlib.

A "report" is a dict mapping name -> numeric score (higher is better): per-case
scores, per-metric scores, whatever the repo measures. Freeze an immutable
baseline before a change; compare a candidate against it; a regression beyond
`tolerance` blocks. Baselines are immutable (freeze refuses to overwrite an
existing path) and meant to be versioned alongside code, one file per version.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def freeze_baseline(path, label: str, report: dict, results: Optional[dict] = None,
                    *, stamp: Optional[str] = None, force: bool = False) -> dict:
    """Write an immutable baseline {label, stamp, report, results}. Refuses to
    overwrite unless force=True (baselines are append-a-new-version, never mutate)."""
    path = Path(path)
    if path.exists() and not force:
        raise FileExistsError(
            f"baseline exists (immutable): {path}. Freeze a new versioned path, or force=True.")
    payload = {
        "label": label,
        "stamp": stamp or datetime.now().isoformat(timespec="seconds"),
        "report": report,
        "results": results,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True))
    return payload


def load_baseline(path) -> dict:
    return json.loads(Path(path).read_text())


def compare_to_baseline(candidate: dict, baseline: dict, tolerance: float = 0.0) -> dict:
    """Compare candidate vs baseline reports (name -> score, higher better).

    `tolerance` is the match-or-beat slack: 0.0 for regression gates (no drop
    allowed), a small positive value (e.g. 0.02) for capability evals. Returns
    regressions / improvements / new / missing keys and a `clean` flag (no
    regressions and nothing missing = match-or-beat satisfied).
    """
    regressions, improvements, new = [], [], []
    for name, cval in candidate.items():
        if name not in baseline:
            new.append(name)
        elif cval < baseline[name] - tolerance:
            regressions.append(name)
        elif cval > baseline[name] + tolerance:
            improvements.append(name)
    missing = [name for name in baseline if name not in candidate]
    clean = not regressions and not missing
    return {
        "regressions": sorted(regressions),
        "improvements": sorted(improvements),
        "new": sorted(new),
        "missing": sorted(missing),
        "clean": clean,
    }
