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
import argparse, importlib.util, json, os, pathlib, re, sys, urllib.parse, urllib.request, urllib.error

WEEKS = 18
# The team table and its alias map live in pull_season.py. Importing beats a
# second copy: two spellings of "which code is Washington" is how a pull lands
# a team's ownership on nobody.
_spec = importlib.util.spec_from_file_location("_ps", pathlib.Path(__file__).with_name("pull_season.py"))
ps = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ps)

HERE = pathlib.Path(__file__).resolve().parent
GAME = "nfl-survivor-2026"

# ---------------------------------------------------------------------------
# OBSERVED, NOT GUESSED. Recorded by --discover against a live session on
# 2026-09-08: these are the calls the pool page actually makes.
#
#   nfl-survivor-2026 resolves to numeric challenge 287. Both spellings answer,
#   and the numeric one is what every sub-resource is keyed on.
#
#   THE GROUP CALL IS PAGINATED and the page asks for 30. A pool larger than one
#   page would otherwise read as a field of 30 -- the whole tool downstream is
#   share-of-pool arithmetic, so a silently truncated field is a silently wrong
#   board. page_group() walks offset until a page comes back short.
# ---------------------------------------------------------------------------
BASE = "https://gambit-api.fantasy.espn.com/apis/v1"
CHALLENGE = 287
PAGE = 50


def endpoints(gid: str, offset: int = 0, limit: int = PAGE) -> dict:
    filt = urllib.parse.quote(json.dumps(
        {"filterSortId": {"value": 0}, "limit": limit, "offset": offset},
        separators=(",", ":")))
    return {
        "challenge":    f"{BASE}/challenges/{GAME}/?platform=chui&view=chui_default",
        "group":        f"{BASE}/challenges/{CHALLENGE}/groups/{gid}/"
                        f"?platform=chui&view=chui_default_group&filter={filt}",
        "members":      f"{BASE}/challenges/{CHALLENGE}/members/?platform=chui&view=chui_default",
        "propositions": f"{BASE}/propositions/?challengeId={CHALLENGE}&platform=chui&view=chui_default",
    }
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



# --------------------------------------------------------------- the parse ---
# Shapes below are OBSERVED (probe + inspect, 2026-09-08), not assumed:
#   propositions[]            .scoringPeriodId  -> week   *** NOT the array index ***
#                             .possibleOutcomes[] .abbrev -> team
#                                                 .choiceCounters[] .count/.percentage
#   group .size, .entryStats.overallEntryCountStats {SURVIVING, ELIMINATED, TOTAL}
#         .entryStats.entryCountStatsByScoringPeriod{week}{...}
#
# THE ARRAY IS NOT IN WEEK ORDER. propositions[0] came back as a DECEMBER week
# carrying 28 outcomes (four teams on bye), so index-as-week would have silently
# filed December's ownership under week 1 and every number after it would still
# have looked like a number.

def parse_ownership(prop):
    """{week: {TEAM: share}} from ESPN's own pick counters, plus what they imply."""
    by_week, counts = {}, {}
    unknown = set()
    for p in prop:
        wk = p.get("scoringPeriodId")
        if not isinstance(wk, int) or not 1 <= wk <= WEEKS:
            continue
        share, cnt = {}, {}
        for o in p.get("possibleOutcomes") or []:
            if o.get("type") != "COMPETITOR":
                continue
            ab = ps.norm(o.get("abbrev"))
            if ab not in ps.IDX:
                unknown.add(o.get("abbrev") or "?"); continue
            cc = (o.get("choiceCounters") or [{}])[0]
            pctv, c = cc.get("percentage"), cc.get("count")
            if pctv is None and c is None:
                continue
            share[ab] = float(pctv or 0.0)
            cnt[ab] = int(c or 0)
        if share:
            by_week[wk], counts[wk] = share, cnt
    if unknown:
        print(f"  ! unrecognised team codes {sorted(unknown)} -- add them to pull_season.ALIAS",
              file=sys.stderr)
    return by_week, counts


def check_ownership(by_week, counts):
    """A share table that does not sum to 1 is not a share table. Refuse rather
    than normalise: if these are not what we think they are, normalising makes a
    wrong reading look like a right one."""
    problems = []
    for wk in sorted(by_week):
        tot = sum(by_week[wk].values())
        n = len(by_week[wk])
        if tot < 0.001:
            problems.append(f"week {wk}: every share is zero across {n} teams -- no picks counted yet")
        elif not 0.90 <= tot <= 1.10:
            problems.append(f"week {wk}: shares sum to {tot:.3f}, not ~1.00, over {n} teams")
        if n < 20:
            problems.append(f"week {wk}: only {n} teams offered (expect 28-32)")
    return problems


def implied_field(by_week, counts):
    """count / percentage recovers the size of the field being counted. It is a
    cross-check on the reading AND the number that says out loud these are
    ESPN-wide picks, not your pool's."""
    out = {}
    for wk in by_week:
        est = [c / by_week[wk][t] for t, c in counts[wk].items()
               if by_week[wk].get(t, 0) > 0.005 and c]
        if est:
            est.sort()
            out[wk] = int(est[len(est) // 2])
    return out

NAMEISH = re.compile(r"name|display|first|last|nick|email|avatar|logo", re.I)


def detail(node, depth=0, path="$", maxdepth=4, redact=True):
    """Targeted structure, deeper than shape() and with values for scalars.

    NAMES ARE REDACTED. Nothing in the parser keys on a human name -- entries
    have ids -- so there is no reason for the pool's roster of real people to be
    pasted into a chat to get a parser written."""
    pad = "  " * depth
    if isinstance(node, dict):
        print(f"{pad}{path}: {{{', '.join(sorted(node))}}}")
        if depth >= maxdepth: return
        for k in sorted(node):
            detail(node[k], depth + 1, k, maxdepth, redact)
    elif isinstance(node, list):
        print(f"{pad}{path}: list[{len(node)}]")
        if node and depth < maxdepth:
            detail(node[0], depth + 1, path + "[0]", maxdepth, redact)
    else:
        v = "<redacted>" if (redact and NAMEISH.search(path) and isinstance(node, str) and node) else repr(node)
        print(f"{pad}{path} = {v[:90]}")


def inspect(d: pathlib.Path):
    """Read what --probe saved and print the parts the parser has to key on."""
    load = lambda n: json.loads((d / f"{n}.json").read_text(encoding="utf-8"))
    try:
        grp, mem, prop, ch = load("group"), load("members"), load("propositions"), load("challenge")
    except FileNotFoundError as e:
        raise SystemExit(f"{e.filename} not there. Run --probe --save {d} first.")

    print("=" * 72, "\nGROUP -- how big is the field, and how many are alive")
    for k in ("size", "largeGroup", "locked", "forecastEligibleTeamsRemaining"):
        if k in grp: print(f"  {k} = {grp[k]!r}")
    print(f"  entries returned = {len(grp.get('entries', []))}")
    detail(grp.get("entryStats"), 1, "entryStats", maxdepth=3)
    print("\n  one entry, in full:")
    if grp.get("entries"): detail(grp["entries"][0], 1, "entries[0]", maxdepth=4)

    print("=" * 72, "\nMEMBERS -- where picks actually live")
    e = (mem.get("entries") or [{}])[0]
    print(f"  entry keys: {sorted(e)}")
    detail(e.get("picks"), 1, "picks", maxdepth=4)
    for k in ("id", "challengeGroups", "groupIds", "scoreByGroup"):
        if k in e: detail(e[k], 1, k, maxdepth=3)

    print("=" * 72, "\nPROPOSITIONS -- the pickable teams, and any pick counts")
    print(f"  {len(prop)} propositions (expect one per week)")
    p0 = prop[0] if prop else {}
    print(f"  keys: {sorted(p0)}")
    for k in sorted(p0):
        v = p0[k]
        if isinstance(v, (list, dict)) and v:
            detail(v, 1, k, maxdepth=3)
    print("\n  scanning every proposition for a pick-count / percentage field:")
    hits = set()
    def scan(n, path=""):
        if isinstance(n, dict):
            for k, v in n.items():
                if re.search(r"percent|pct|count|popular|selected|picked|tally", k, re.I) \
                   and isinstance(v, (int, float, str)):
                    hits.add(f"{path}.{k} = {v!r}"[:110])
                scan(v, f"{path}.{k}")
        elif isinstance(n, list):
            for x in n[:3]: scan(x, path + "[]")
    for p in prop[:3]: scan(p, "prop")
    for h in sorted(hits)[:25]: print("    " + h)
    if not hits: print("    none found -- ownership will have to come from the group picks view")

    print("=" * 72, "\nCHALLENGE -- period and lock state")
    detail(ch.get("currentScoringPeriod"), 1, "currentScoringPeriod", maxdepth=2)
    for k in ("gameId", "gameType", "scoringPeriods", "teams"):
        if k in ch: detail(ch[k], 1, k, maxdepth=2)


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
    ap.add_argument("--probe", action="store_true",
                    help="fetch every OBSERVED endpoint and describe each response")
    ap.add_argument("--save", metavar="DIR",
                    help="with --probe, also write each raw response there")
    ap.add_argument("--out", default="field.js")
    ap.add_argument("--force", action="store_true",
                    help="write even if the ownership table fails verification")
    ap.add_argument("--inspect", metavar="DIR",
                    help="read what --probe --save wrote and print the parts a parser keys on")
    ap.add_argument("--dump", metavar="URL", help="fetch one endpoint and describe the response")
    a = ap.parse_args()

    if a.discover:
        return discover(a.url, a.env)

    if a.inspect:
        return inspect(pathlib.Path(a.inspect))

    if a.probe:
        gid = group_id(a.url)
        c = creds(a.env)
        out_dir = pathlib.Path(a.save) if a.save else None
        if out_dir: out_dir.mkdir(parents=True, exist_ok=True)
        for name, url in endpoints(gid).items():
            print("=" * 72)
            print(f"{name}\n  {url[:150]}")
            status, body = fetch(url, c)
            print(f"  HTTP {status}  ({len(body)} bytes)")
            if status != 200:
                print("  " + body[:400].replace("\n", " "))
                continue
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                print("  not JSON: " + body[:200]); continue
            shape(data)
            if out_dir:
                p = out_dir / f"{name}.json"
                p.write_text(json.dumps(data, indent=1)[:4_000_000], encoding="utf-8")
                print(f"  -> saved {p}")
        print("=" * 72)
        print("Paste the shapes above (or the saved files) and the parser gets written\n"
              "against the real response. Nothing was written to field.js.")
        return

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

    gid = group_id(a.url)
    c = creds(a.env)
    urls = endpoints(gid)
    print("propositions ...", end=" ", flush=True)
    st, body = fetch(urls["propositions"], c)
    if st != 200:
        raise SystemExit(f"HTTP {st} on propositions. {body[:300]}")
    prop = json.loads(body)
    by_week, counts = parse_ownership(prop)
    print(f"{len(prop)} propositions -> ownership for {len(by_week)} week(s)")

    print("group ...", end=" ", flush=True)
    st, body = fetch(urls["group"], c)
    grp = json.loads(body) if st == 200 else {}
    stats = (grp.get("entryStats") or {}).get("overallEntryCountStats") or {}
    print(f"size {grp.get('size')}, surviving {stats.get('SURVIVING')}, "
          f"eliminated {stats.get('ELIMINATED')}")

    print("challenge ...", end=" ", flush=True)
    st, body = fetch(urls["challenge"], c)
    ch = json.loads(body) if st == 200 else {}
    cur = ch.get("currentScoringPeriod") or {}
    print(f"{cur.get('label')} (locked: {cur.get('allPropositionsLocked')})")

    implied = implied_field(by_week, counts)
    print("\nweek  teams   sum    top three                          implied field")
    for wk in sorted(by_week):
        sh = by_week[wk]
        top = sorted(sh.items(), key=lambda kv: -kv[1])[:3]
        print(f"{wk:>4}  {len(sh):>5}  {sum(sh.values()):>5.3f}   "
              + ", ".join(f"{t} {v*100:.1f}%" for t, v in top).ljust(34)
              + f"  {implied.get(wk, 0):,}")

    problems = check_ownership(by_week, counts)
    if problems:
        print("\nVERIFICATION FAILED:", file=sys.stderr)
        for p in problems[:12]: print("  - " + p, file=sys.stderr)
        if not a.force:
            raise SystemExit("\nNothing written. A share table that does not sum to 1 is not a share\n"
                             "table, and normalising it would make a wrong reading look like a right\n"
                             "one. Pass --force if you know why and want it anyway.")
        print("  (--force: writing anyway)", file=sys.stderr)

    out = {
        "source": f"ESPN gambit challenge {CHALLENGE} ({GAME})",
        "pulled_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "week": cur.get("id"), "week_label": cur.get("label"),
        "locked": bool(cur.get("allPropositionsLocked")),
        "group": {"size": grp.get("size"), "surviving": stats.get("SURVIVING"),
                  "eliminated": stats.get("ELIMINATED"), "total": stats.get("TOTAL")},
        # ESPN-WIDE, not your group. The implied field says so in numbers: your
        # pool is 25 and this is counted over tens of thousands.
        "scope": "espn-wide",
        "implied_field": implied,
        "ownership": {str(k): v for k, v in by_week.items()},
    }
    p = pathlib.Path(a.out)
    p.write_text("/* Generated by pull_field.py -- do not edit by hand. */\n"
                 "window.FIELD = " + json.dumps(out, separators=(",", ":")) + ";\n",
                 encoding="utf-8")
    print(f"\nwrote {p}: ownership for {len(by_week)} week(s), "
          f"pool {out['group']['surviving']}/{out['group']['size']} alive.")
    print("Open index.html -- ownership now comes from ESPN's counters, not the softmax.")
    return

    raise SystemExit(
        "Nothing to write yet, and that is deliberate.\n\n"
        "  The endpoints are known now (--discover found them; challenge 287 on\n"
        "  gambit-api.fantasy.espn.com). What is NOT known is the shape of what they\n"
        "  return, and a parser written against a guessed shape produces a file that\n"
        "  looks right and is not. So:\n\n"
        "      python pull_field.py --env <path> --url \"<your pool URL>\" --probe\n\n"
        "  and the parser gets written against the real response.\n\n"
        "  TARGET OUTPUT once the shape is known -- field.js, read by index.html:\n"
        "      window.FIELD = {\n"
        "        week: 3,                      last locked week\n"
        "        entries: 147, alive: 89,      real pool size, which shrinks\n"
        "        burned: {BUF: 42, KC: 31},    surviving entries that have spent each team\n"
        "        history: {1: {LAC: 51}, 2: {...}}   what this room ACTUALLY picked\n"
        "      }")


if __name__ == "__main__":
    main()
