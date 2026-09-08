#!/usr/bin/env python3
"""Emit the Artifact-shaped fragment of index.html on stdout.

index.html is the source of truth and a complete document -- it opens by
double-click and serves from anywhere. The Artifact host supplies its own
`<!doctype><head></head><body>` shell and REFUSES a page that brings one, so
publishing means handing it the same page with the shell taken off. Doing that
by hand is how the two copies drift; this does it mechanically.

    python build_artifact.py > artifact.html      # then publish artifact.html
"""
import re, sys, pathlib

SRC = pathlib.Path(__file__).with_name("index.html")

def fragment(doc: str) -> str:
    head = re.search(r"<head>(.*?)</head>", doc, re.S)
    body = re.search(r"<body>(.*?)</body>", doc, re.S)
    if not head or not body:
        raise SystemExit("index.html has no <head>/<body> pair -- did the file get flattened?")
    # The three metas are the host's job, not ours; everything else in head is the page.
    keep = re.sub(r"^\s*<meta[^>]*>\s*$", "", head.group(1), flags=re.M).strip()
    return keep + "\n\n" + body.group(1).strip() + "\n"

# `<head` is a prefix of `<header`, which the page opens with -- so the guard
# has to close on a tag boundary or it refuses every correct build.
SHELL = re.compile(r"<!doctype|<\s*(?:html|head|body)\s*[>/]", re.I)

if __name__ == "__main__":
    out = fragment(SRC.read_text(encoding="utf-8"))
    stray = SHELL.search(out)
    if stray:
        raise SystemExit(f"refusing to emit a fragment still carrying {stray.group(0)!r}")
    sys.stdout.write(out)
