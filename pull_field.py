#!/usr/bin/env python3
"""Read the REAL state of your ESPN survivor pool: who is alive, and what they burned.

    python pull_field.py --discover     # watch the page, print the API it calls. Writes nothing.
    python pull_field.py --dump URL     # fetch one endpoint and describe what came back.
    python pull_field.py                # (once the shape is known) write field.js

WHY THIS EXISTS. The board currently projects the field's ownership from a
softmax over win probability -- `exp(13 * (p - 0.5))`, normalised. That constant
was chosen to make the top favourite land near 30% and is fitted to NOTHING, so
projected ownership is a monotone function of win probability and carries no
information the win probabilities did not already carry. The leverage half of
the tool is therefore correct arithmetic over invented input.

Three things real data fixes, in rising order of value:

  1. THE ALIVE COUNT. Pools shrink every week; the board takes a static number,
     so the leverage denominator is wrong from week 2 onward.
  2. WHAT THE FIELD HAS BURNED. The board projects the field's week 11 picks as
     though all 32 teams were available to every rival. They are not. This is
     modelled NOWHERE today and it is the largest single error in the leverage
     half.
  3. WHAT THIS ROOM ACTUALLY DID. Past weeks give real ownership, which is what
     you calibrate against instead of guessing -- or replace outright, since a
     projection conditioned on each rival's remaining teams beats any curve.

PICKS ARE HIDDEN UNTIL LOCK, AND THAT IS THE GAME, NOT A LIMITATION TO ENGINEER
AROUND. Nothing here can show you this week's picks before the deadline. It reads
weeks that have already locked, which is what (1)(2)(3) need.

NOTHING IS GUESSED. ESPN's games platform (Gambit) is not the `ffl` fantasy API,
and its endpoints are not documented. Rather than try candidate URLs and read a
404 as an answer, --discover drives a real browser through your own session and
records the calls the page makes. That is the endpoint, observed rather than
assumed. Until one has been observed this script REFUSES to write anything.
"""
from __future__ import annotations
import argparse, json, os, pathlib, re, sys, urllib.request, urllib.error

HERE = pathlib.Path(__file__).resolve().parent
GAME = "nfl-survivor-2026"
# Hosts worth recording during --discover. ESPN serves its games platform off
# several; anything under espn.com carrying JSON is worth seeing.
API_HINT = re.compile(r"(gambit|fantasy|site|sports\.core|lm-api)[\w.-]*\.espn\.com", re.I)
NOISE = re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|woff2?|ttf|css|js|ico)(\?|$)", re.I)


def creds(env_path=None):
    """swid + espn_s2, the same pair draftkit keeps.

    PREFER POINTING AT draftkit's .env OVER COPYING IT. These are session cookies
    for a whole ESPN account, and two copies is two places to rotate -- the one
    you forget is the one still live. --env takes a path; a local .env still
    works, and is gitignored here."""
    env = {}
    for p in ([pathlib.Path(env_path)] if env_path else [HERE / ".env"]):
        if not p.exists():
            if env_path:
                raise SystemExit(f"No such file: {p}")
            continue
        # utf-8-sig: PowerShell writes a BOM often enough that a plain utf-8 read
        # turns the first key into an unrecognisable one, silently.
        for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip().upper()] = v.strip().strip("'\"")
    # draftkit's creds.py spells it ESPN_SWID; a bare SWID is what the browser
    # calls the cookie. Accept both, draftkit's name first, so pointing --env at
    # its file works without renaming anything over there.
    pick = lambda *names: next((v for n in names for v in (os.environ.get(n), env.get(n)) if v), "")
    swid = pick("ESPN_SWID", "SWID")
    s2 = pick("ESPN_S2", "S2")
    if not (swid and s2):
        raise SystemExit(
            "No ESPN cookies. This pool is private, so the request has to be you.\n\n"
            "  BEST -- point at the copy you already have, so there is only ever one:\n"
            "      python pull_field.py --env C:\\dev\\draftkit\\.env --discover ...\n\n"
            "  Or write a local one (gitignored here). In PowerShell, without ever\n"
            "  printing the values to your terminal:\n"
            "      Select-String C:\\dev\\draftkit\\.env -Pattern '^ESPN_S(WID|2)=' |\n"
            "        ForEach-Object { $_.Line } | Set-Content C:\\dev\\survivor\\.env\n\n"
            "  They are session cookies for your whole ESPN account: never commit them,\n"
            "  and rotate by signing out of ESPN and back in if they ever leak."
            + (f"\n\n  Read {pathlib.Path(env_path)} and found: {sorted(env) or 'nothing'}"
               if env_path else ""))
    if not swid.startswith("{"):
        swid = "{" + swid.strip("{}") + "}"
    return {"SWID": swid, "espn_s2": s2}


def group_id(url_or_id: str) -> str:
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", url_or_id, re.I)
    if not m:
        raise SystemExit(f"No group id in {url_or_id!r}. Pass the URL from the address bar,\n"
                         "  the one with ?id=<uuid> on the end.")
    return m.group(0)


def fetch(url: str, cookies: dict) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        "Referer": f"https://fantasy.espn.com/games/{GAME}/",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", "replace")[:600]
        except Exception: pass
        return e.code, body


def shape(node, depth=0, path="$"):
    """Describe a JSON body without printing all of it -- what keys exist, how
    long the lists are. A pool has hundreds of entries and the answer is the
    SHAPE, not the payload."""
    pad = "  " * depth
    if isinstance(node, dict):
        print(f"{pad}{path}: object ({len(node)} keys) {sorted(node)[:14]}")
        if depth < 2:
            for k in sorted(node)[:8]:
                shape(node[k], depth + 1, k)
    elif isinstance(node, list):
        print(f"{pad}{path}: list[{len(node)}]")
        if node and depth < 3:
            shape(node[0], depth + 1, path + "[0]")
    else:
        v = repr(node)
        print(f"{pad}{path}: {type(node).__name__} = {v[:70]}")


def discover(url: str, env_path=None):
    """Drive the real page through your own session and record what it calls.
    This is the whole point: the endpoint is OBSERVED, never guessed."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "--discover needs playwright, which the rest of this repo does not:\n"
            "    pip install playwright && playwright install chromium\n\n"
            "  Or do it by hand, which takes a minute and needs nothing installed:\n"
            "    open the pool page, F12 -> Network -> filter 'Fetch/XHR', reload,\n"
            "    and copy the request URLs that look like an API. Then run\n"
            "    python pull_field.py --dump \"<that url>\"")
    seen, cookies = [], creds(env_path)
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False)          # visible: you may need to click through
        ctx = b.new_context()
        ctx.add_cookies([{"name": k, "value": v, "domain": ".espn.com", "path": "/"}
                         for k, v in cookies.items()])
        pg = ctx.new_page()
        pg.on("request", lambda r: (
            seen.append((r.method, r.url))
            if API_HINT.search(r.url) and not NOISE.search(r.url) else None))
        print(f"opening {url}\n  (leave the window open until the pool renders)")
        pg.goto(url, wait_until="networkidle", timeout=90000)
        pg.wait_for_timeout(6000)
        b.close()
    if not seen:
        raise SystemExit("No API calls recorded. Either the page never loaded (check the window\n"
                         "  that opened) or the cookies are stale -- sign out of ESPN and back in.")
    uniq = sorted({u for _, u in seen})
    print(f"\n{len(uniq)} distinct API call(s) -- the survivor data is behind one of these:\n")
    for u in uniq:
        print("  " + u)
    print("\nNext: python pull_field.py --dump \"<the one that looks like entries or picks>\"")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=f"https://fantasy.espn.com/games/{GAME}/group",
                    help="your pool's page, the one with ?id=<uuid>")
    ap.add_argument("--env", metavar="PATH",
                    help=r"read SWID/ESPN_S2 from here instead of a local .env "
                         r"(e.g. C:\dev\draftkit\.env) -- better than a second copy")
    ap.add_argument("--discover", action="store_true",
                    help="open the page in a browser and print the API calls it makes")
    ap.add_argument("--dump", metavar="URL", help="fetch one endpoint and describe the response")
    a = ap.parse_args()

    if a.discover:
        return discover(a.url, a.env)

    if a.dump:
        status, body = fetch(a.dump, creds(a.env))
        print(f"HTTP {status}  ({len(body)} bytes)\n")
        if status != 200:
            print(body[:600])
            print("\n  401/403 means the cookies did not carry -- they expire; re-copy them.\n"
                  "  404 means that is not the endpoint. Run --discover rather than guessing.")
            return
        try:
            shape(json.loads(body))
        except json.JSONDecodeError:
            print("Not JSON. First 400 characters:\n" + body[:400])
        return

    raise SystemExit(
        "Nothing to write yet, and that is deliberate.\n\n"
        "  ESPN's games platform is undocumented and no endpoint has been OBSERVED for\n"
        "  this pool. Writing a parser against a guessed shape is how you get a file\n"
        "  that looks right and is not. Run this first:\n\n"
        "      python pull_field.py --url \"<your pool URL>\" --discover\n\n"
        "  then --dump the endpoint it finds, and the parser gets written against the\n"
        "  real response.\n\n"
        "  TARGET OUTPUT once the shape is known -- field.js, read by index.html:\n"
        "      window.FIELD = {\n"
        "        week: 3,                      last locked week\n"
        "        entries: 147, alive: 89,      real pool size, which shrinks\n"
        "        burned: {BUF: 42, KC: 31},    surviving entries that have spent each team\n"
        "        history: {1: {LAC: 51}, 2: {...}}   what this room ACTUALLY picked\n"
        "      }")


if __name__ == "__main__":
    main()
