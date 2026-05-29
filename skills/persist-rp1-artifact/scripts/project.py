#!/usr/bin/env python3
"""Project an rp1 artifact into a deterministic PR/issue comment body.

Pure and network-free: given an artifact file and the repo-relative source path
to display, emit the exact comment body on stdout. Warnings go to stderr.
This module never calls GitHub and never modifies the artifact.
"""
import argparse
import os
import re
import sys

MAX_BYTES = 65536

# A frontmatter key line: starts at column 0, identifier-ish key, then ": ".
# Indented continuation lines (multi-line quoted values) never match, so a colon
# inside a wrapped value cannot create a bogus key.
_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s?(.*)$")


def split_frontmatter(text):
    """Return (fm_dict, body). The frontmatter block is OPTIONAL.

    If the text does not open with a '---' block, fm is {} and body is the whole
    text. Values keep their first-line content; surrounding quotes are stripped.
    """
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        km = _KEY_RE.match(line)
        if not km:
            continue
        key, val = km.group(1).strip(), km.group(2).strip()
        if val and val[0] in "\"'":
            if len(val) >= 2 and val[-1] == val[0]:
                val = val[1:-1]   # both quotes on same line → strip both
            else:
                val = val[1:]     # only leading quote (multi-line value) → strip just the opener
        fm[key] = val
    return fm, m.group(2)
