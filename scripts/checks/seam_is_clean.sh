#!/bin/sh
# Fails when a generic plugin carries a domain token. See docs/INVARIANTS.md.
exec python3 -m pytest tests/test_seam.py -q -o addopts=
