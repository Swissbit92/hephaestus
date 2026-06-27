"""Tests for the release flow's version math (scripts/bump_version.py)."""
from __future__ import annotations

import pytest

from bump_version import next_version


@pytest.mark.parametrize(
    "current,bump,expected",
    [
        ("0.1.0", "patch", "0.1.1"),
        ("0.1.0", "minor", "0.2.0"),
        ("0.1.0", "major", "1.0.0"),
        ("0.2.0", "minor", "0.3.0"),
        ("1.2.3", "patch", "1.2.4"),
        ("1.9.9", "major", "2.0.0"),
        ("1.2.3", "minor", "1.3.0"),
    ],
)
def test_next_version_bumps(current, bump, expected):
    assert next_version(current, bump) == expected


@pytest.mark.parametrize("explicit", ["1.2.3", "10.0.1", "0.0.9"])
def test_next_version_explicit_pin(explicit):
    # An explicit X.Y.Z is returned verbatim regardless of current.
    assert next_version("0.1.0", explicit) == explicit


def test_next_version_strips_whitespace():
    assert next_version(" 0.1.0 ", " minor ") == "0.2.0"


@pytest.mark.parametrize("bump", ["sideways", "", "Patch", "1.2", "1.2.3.4"])
def test_next_version_rejects_bad_bump(bump):
    with pytest.raises(ValueError):
        next_version("0.1.0", bump)


@pytest.mark.parametrize("current", ["notsemver", "1.2", "v1.2.3", ""])
def test_next_version_rejects_bad_current(current):
    # Only matters when bump is relative (a valid explicit pin ignores current).
    with pytest.raises(ValueError):
        next_version(current, "patch")
