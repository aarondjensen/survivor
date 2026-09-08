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


# ---------------------------------------------------------------------------
# SPLASH SPORTS. Two walks, and the second one is the one that counts.
#
#   ANONYMOUS (--discover, 2026-09-08): the walk reported split.io identifying
#   the visitor as `anonymous-user-...`, so it saw the PUBLIC view of a contest.
#   No entries and no picks appeared. That is the shape of a page nobody is
#   signed in to, not evidence about what Splash serves.
#
#   SIGNED IN (a HAR exported from the picks page by hand, 2026-09-08, after the
#   captcha refused the driven window). Five calls, and they settle the question:
#
#     GET /contests/<contest>                                        170,948 B
#     GET /contests/<contest>/slates                                   7,475 B
#     GET /contests/<contest>/users/<user>/entries?limit=150&offset=0    375 B
#     GET /slates/<slate>/picksheets?contestId=<contest>&sort=startTime          10,636 B
#     GET /slates/<slate>/picksheets?contestId=<contest>&entryId=<entry>&...     12,365 B
#
# PICKSHEETS IS THE PICK SURFACE, and it is the same endpoint twice: without
# `entryId` it is the slate, with it your own picks come back alongside. That is
# what a parser keys on.
#
# THERE IS NO OWNERSHIP ENDPOINT AND NO ENTRANTS LIST IN THAT CAPTURE, and that
# is the finding, not a gap in the walk -- the page was signed in, it rendered
# fully, and nothing resembling ESPN's `choiceCounters` was requested. So Splash
# can give POOL SIZE and YOUR OWN PICKS; the field's ownership has to keep coming
# from the model. Saying otherwise would be inventing a number.
#
# THE CALLS CARRY A `location-token-v2` HEADER. It is a per-session geolocation
# grant, it is a credential, and it is not in the repo: SPLASH_LOCATION_TOKEN in
# .env (gitignored) or the environment, sent to splashsports.com and nowhere
# else. Without it these may 401 -- which is a real answer and is printed as one.
# ---------------------------------------------------------------------------
SPLASH = "https://api.splashsports.com/contests-service/api"
SPLASH_SCOPE = "splashsports.com"


def contest_id(url_or_id: str) -> str:
    """The Splash URL can carry two UUIDs -- the contest and, in an invite link,
    the referrer. Take the one after /contest(s)/, never just the first match."""
    m = re.search(r"/contests?/([0-9a-f-]{36})", url_or_id, re.I)
    if m: return m.group(1)
    return group_id(url_or_id)


def splash_ids(url: str) -> dict:
    """A Splash picks URL carries three ids and they are not interchangeable:
    /contest/<contestId>/picks?entryId=<entryId>&slateId=<slateId>.

    The USER id is a fourth and the URL does not carry it -- it is in the entries
    path only. --splash-user takes it; without it the entries call is skipped
    rather than guessed at."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return {"contest": contest_id(url),
            "entry": (q.get("entryId") or [None])[0],
            "slate": (q.get("slateId") or [None])[0]}


def splash_endpoints(ids: dict, user: str | None = None) -> dict:
    """Exactly the five URLs the signed-in capture made, and no invented sixth.

    An endpoint whose ids we do not hold is LEFT OUT rather than built with a
    hole in it: a 404 from a URL we assembled ourselves reads like Splash
    refusing us, which is the confident wrong answer this file keeps avoiding."""
    cid, slate, entry = ids.get("contest"), ids.get("slate"), ids.get("entry")
    out = {"contest": f"{SPLASH}/contests/{cid}",
           "slates":  f"{SPLASH}/contests/{cid}/slates"}
    if user:
        out["entries"] = (f"{SPLASH}/contests/{cid}/users/{user}/entries"
                          f"?limit=150&offset=0")
    if slate:
        out["picksheets"] = (f"{SPLASH}/slates/{slate}/picksheets"
                             f"?contestId={cid}&sort=startTime")
        if entry:
            out["picksheets_mine"] = (f"{SPLASH}/slates/{slate}/picksheets"
                                      f"?contestId={cid}&entryId={entry}&sort=startTime")
    return out


def splash_token(env_path=None) -> str:
    """`location-token-v2`, read from the environment or .env. Never printed.

    It is short-lived and tied to a signed-in session, so the honest failure when
    it is absent is the endpoint's own 401 -- not a refusal here, because some of
    these calls may well be public and refusing in advance would hide that."""
    env = {}
    for p in ([pathlib.Path(env_path)] if env_path else [HERE / ".env"]):
        if not p.exists(): continue
        for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip().upper()] = v.strip().strip("'\"")
    return (os.environ.get("SPLASH_LOCATION_TOKEN")
            or env.get("SPLASH_LOCATION_TOKEN") or "")


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
NOISE = re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|woff2?|ttf|css|js|ico)(\?|$)", re.I)
# Ad and analytics hosts embed the page URL in their query string, so a filter
# that reads the whole URL matches every one of them. The ESPN walk returned 29
# "API calls" of which 22 were rubicon, criteo, doubleclick and friends, matched
# purely on `fantasy.espn.com` appearing inside `?rf=`. MATCH THE HOST.
ADTECH = re.compile(r"(doubleclick|rubicon|criteo|openx|tremorhub|adnxs|onelink|"
                    r"scorecardresearch|chartbeat|parsely|imrworldwide|analytics|"
                    r"quantserve|moatads|amazon-adsystem|casalemedia|pubmatic|"
                    r"im-apps|omtrdc|demdex|nielsen|segment|sentry|newrelic|"
                    r"googletagmanager|google-analytics|facebook|branch\.io)", re.I)


def is_api(url: str, site: str) -> bool:
    """Worth recording? Judged on the HOST plus the path, never the query string."""
    try:
        u = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host, path = (u.hostname or "").lower(), (u.path or "").lower()
    if not host or u.scheme not in ("http", "https"): return False
    if ADTECH.search(host) or NOISE.search(path): return False
    same_site = host == site or host.endswith("." + site)
    apiish = bool(re.search(r"(^|\.)(api|gambit|graphql|gateway|svc)\b", host)
                  or re.search(r"/(api|graphql|v\d+)(/|$)", path))
    return same_site or apiish


def registrable(url: str) -> str:
    """example.co.uk-style suffixes are not handled: this only has to be good
    enough to say 'the site you are looking at', and it is printed so a wrong
    guess is visible rather than silent."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


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


COOKIE_SCOPE = "espn.com"   # the only host our stored cookies belong to


def under(host: str, scope: str) -> bool:
    return host == scope or host.endswith("." + scope)


def fetch(url: str, cookies: dict, token: str = "") -> tuple[int, str]:
    """EVERY CREDENTIAL GOES TO ONE DOMAIN AND NOWHERE ELSE.

    The first cut attached the ESPN cookies -- session credentials for a whole
    ESPN account -- and an ESPN Referer to WHATEVER URL it was handed. Pointing
    --dump at another platform's API would have posted them straight to a third
    party. Now the host has to be under COOKIE_SCOPE or the request goes out
    bare, and the Referer is derived from the target rather than hardcoded.

    `token` is Splash's `location-token-v2` and follows the identical rule under
    SPLASH_SCOPE. Two secrets, two scopes, one gate -- adding the second one
    beside the first is how it ends up going somewhere it should not."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    scoped = under(host, COOKIE_SCOPE)
    splashy = under(host, SPLASH_SCOPE)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"https://fantasy.espn.com/games/{GAME}/" if scoped
                   else "https://app.splashsports.com/" if splashy
                   else f"https://{host}/",
    }
    if scoped and cookies:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    elif cookies:
        print(f"  (no cookies sent: {host} is outside {COOKIE_SCOPE})", file=sys.stderr)
    if token:
        if splashy:
            headers["location-token-v2"] = token
        else:
            print(f"  (no location token sent: {host} is outside {SPLASH_SCOPE})",
                  file=sys.stderr)
    req = urllib.request.Request(url, headers=headers)
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


def discover(url: str, env_path=None, skip_creds=False, hold=True):
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
    site = registrable(url)
    print(f"recording calls to {site} and any api-shaped host; ad and analytics "
          f"hosts are dropped")
    seen = []
    cookies = creds(env_path) if not skip_creds else {}
    # A PERSISTENT PROFILE, so a site we hold no stored credentials for is signed
    # into ONCE rather than on every run. Gitignored: it holds live session
    # cookies, the same reason draftkit keeps its browser profiles out of git.
    profile = HERE / ".browser" / site
    profile.mkdir(parents=True, exist_ok=True)
    # OPEN THE WINDOW THE WAY A PERSON'S BROWSER OPENS. Splash's login came back
    # "Wrong or expired reCaptcha", which is a challenge scoring the WINDOW, not
    # the account. Three things Playwright does by default cause it, and this is
    # the same fix draftkit's platforms/browser.py carries for Cloudflare
    # Turnstile:
    #   1. --enable-automation sets navigator.webdriver = true, the single
    #      most-checked bot signal, and it is on unless you turn it off.
    #   2. The BUNDLED Chromium instead of the Chrome you actually have --
    #      different build, different fingerprint, no reason for a person to run it.
    #   3. A spoofed user-agent, which is worse than none: a claim the rest of the
    #      fingerprint contradicts. Nothing is overridden; the browser reports itself.
    # NONE OF THIS DEFEATS A SECURITY CONTROL -- your account, your password, typed
    # by you into the site's own page. It corrects a false positive about the
    # window, and it is NOT a guarantee: if it still refuses, --har is the route
    # that involves no automation at all.
    CHANNELS = ("chrome", "msedge", None)
    ARGS = ["--disable-blink-features=AutomationControlled"]
    IGNORE = ["--enable-automation"]
    with sync_playwright() as pw:
        ctx = which = None
        for channel in CHANNELS:
            try:
                ctx = pw.chromium.launch_persistent_context(
                    str(profile), headless=False, channel=channel,
                    args=ARGS, ignore_default_args=IGNORE)
                which = channel or "playwright's bundled chromium"
                break
            except Exception as e:
                last = e
        if ctx is None:
            raise SystemExit(f"could not open any browser: {last}")
        print(f"  driving {which}"
              + ("  <- most likely to be challenged; install Chrome to avoid it"
                 if which and "bundled" in which else ""))
        if cookies:
            ctx.add_cookies([{"name": k, "value": v, "domain": "." + COOKIE_SCOPE,
                              "path": "/"} for k, v in cookies.items()])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.on("request", lambda r: (
            seen.append((r.method, r.url)) if is_api(r.url, site) else None))
        print(f"opening {url}")
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=90000)
        except Exception as e:
            print(f"  (navigation reported {type(e).__name__}; still recording)")
        if hold:
            # Six seconds is not enough to sign in, and a walk that closes mid-login
            # records the login page rather than the thing you went to look at.
            print("\n  Sign in if asked, then click through to what you want captured\n"
                  "  -- the picks page, the entrants list -- and let it RENDER.")
            try:
                input("  Press Enter here when done to stop recording... ")
            except (EOFError, KeyboardInterrupt):
                pass
        else:
            pg.wait_for_timeout(6000)
        ctx.close()
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
    """count / percentage recovers the size of whatever field is being counted.

    IT IS NOT ONE NUMBER, AND THAT IS A FINDING RATHER THAN AN ERROR. Measured on
    the real 2026 pull it decays monotonically -- 648k in week 1, 70k in week 2,
    then settling near 43k by week 18. A single game-wide entry count could not do
    that. The reading of `percentage` is fine (every week sums to 1.000 across the
    right number of teams); what varies is the DENOMINATOR ESPN counts against,
    which is entries that have made a pick for that week. Week 1 is inflated
    because far more people have touched a week-1 pick than a week-18 one.

    So it is reported PER WEEK and never averaged into one figure, and the totals
    are what the page shows -- shares, which are what the leverage model consumes
    and which are unaffected by any of this."""
    out = {}
    for wk in by_week:
        est = [c / by_week[wk][t] for t, c in counts[wk].items()
               if by_week[wk].get(t, 0) > 0.005 and c]
        if est:
            est.sort()
            out[wk] = int(est[len(est) // 2])
    return out


def counter_spread(by_week, counts):
    """Within one week, count/percentage must agree across teams -- that is what
    says `percentage` really is `count / (that week's total)`. Disagreement inside
    a week would mean the two fields answer different questions and the shares
    could not be trusted. Returns (week, min, max, spread) worst-first."""
    rows = []
    for wk in sorted(by_week):
        est = [c / by_week[wk][t] for t, c in counts[wk].items()
               if by_week[wk].get(t, 0) > 0.005 and c]
        if len(est) > 2:
            lo, hi = min(est), max(est)
            rows.append((wk, int(lo), int(hi), (hi - lo) / hi))
    rows.sort(key=lambda r: -r[3])
    return rows

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


SPLASH_RULES = {"pickReuseLimit": 0, "entryLives": 1, "expectedPicksCount": 1}


def write_splash(ids, out, token="", force=False):
    """The contest, as a pool the board can carry. Public endpoints, no session.

    IT REFUSES A CONTEST THAT IS NOT THIS GAME. The solver models one team a
    week, each at most once, one life -- and the contest states all three. A
    contest with two lives or a reuse allowance would render on this board
    perfectly and be a different game, which is the whole failure mode this repo
    is written against, so the rules are CHECKED rather than assumed."""
    cid = ids["contest"]
    st, body = fetch(f"{SPLASH}/contests/{cid}", {}, token=token)
    if st != 200:
        raise SystemExit(f"HTTP {st} on the contest. {body[:300]}")
    doc = json.loads(body)
    c = doc.get("contest") or doc
    stt = c.get("settings") or {}
    ent = c.get("entries") or {}

    bad = [f"{k} is {stt.get(k)!r}, not {v!r}" for k, v in SPLASH_RULES.items()
           if stt.get(k) != v]
    weeks = c.get("slateCount")
    if weeks not in (None, 18):
        bad.append(f"slateCount is {weeks!r}, not 18")
    if bad:
        print("THIS CONTEST IS NOT THE GAME THE BOARD MODELS:", file=sys.stderr)
        for b in bad: print("  - " + b, file=sys.stderr)
        if not force:
            raise SystemExit("\nNothing written. The optimizer solves one team a week, each at\n"
                             "most once, one life -- a contest with other rules would render on\n"
                             "this board perfectly and be a different game. --force overrides.")
        print("  (--force: writing anyway)", file=sys.stderr)

    size = ent.get("filled")
    if not isinstance(size, int) or size < 2:
        raise SystemExit(f"entries.filled came back {size!r}. That is the pool size and "
                         "everything\ndownstream is share-of-pool arithmetic, so nothing was written.")

    rec = {
        "source": "Splash Sports contests-service",
        "pulled_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "id": cid,
        "name": c.get("name") or "Splash",
        "size": size, "cap": ent.get("max"), "per_user": ent.get("max_per_user"),
        "weeks": weeks, "status": c.get("status"),
        "entry_fee": c.get("entry_fee_in_dollars"), "prize_pool": c.get("prize_pool_in_dollars"),
        "starts": c.get("contest_start_date"),
        # NO OWNERSHIP AND NO PICKS, and the page says so rather than falling
        # back to ESPN's numbers in silence. Measured: the signed-in walk showed
        # neither an entrants list nor anything like ESPN's choiceCounters.
        "ownership": None,
    }
    p = pathlib.Path(out)
    p.write_text("/* Generated by pull_field.py --platform splash -- do not edit by hand. */\n"
                 "window.SPLASH = " + json.dumps(rec, separators=(",", ":")) + ";\n",
                 encoding="utf-8")
    print(f"wrote {p}: {rec['name']} -- {size} entries"
          + (f" of a {rec['cap']} cap" if rec.get("cap") else "")
          + (f", ${rec['prize_pool']:,} pool" if rec.get("prize_pool") else ""))
    print("A CAP-AND-FILL CONTEST MOVES until the deadline, so re-run this on the morning\n"
          "of the draft rather than trusting a number pulled in August.")
    print("Open index.html -- it is a pool tab now. Ownership there stays ESPN's measured\n"
          "counters as a proxy, because Splash publishes none.")


# ---------------------------------------------------------------------------
# PICKS. Observed by --inspect on 2026-09-08, on the members response:
#
#   entry .picks[] .propositionId          -> which WEEK, via propositions[].id
#                  .outcomesPicked[] .outcomeId -> which TEAM, via that
#                                        proposition's possibleOutcomes[].id
#
# TWO INDIRECTIONS AND NEITHER IS GUESSABLE. A pick names a uuid on both axes;
# nothing in it says "week 3" or "KC". So the propositions response is the
# decoder ring, and a pick whose ids are not in it is DROPPED and named rather
# than filed under a guess -- the Michael Carter rule. A burned team we invent
# is a team the board stops offering you for the whole season.
# ---------------------------------------------------------------------------

def decode_picks(entry, prop):
    """[(week, TEAM)] for one entry, oldest week first, plus what did not decode."""
    week_of, team_of = {}, {}
    for pr in prop:
        pid, wk = pr.get("id"), pr.get("scoringPeriodId")
        if pid and isinstance(wk, int):
            week_of[pid] = wk
        for o in pr.get("possibleOutcomes") or []:
            if o.get("type") == "COMPETITOR" and o.get("id"):
                team_of[o["id"]] = ps.norm(o.get("abbrev"))

    out, bad = [], []
    for pk in (entry or {}).get("picks") or []:
        wk = week_of.get(pk.get("propositionId"))
        for o in pk.get("outcomesPicked") or []:
            ab = team_of.get(o.get("outcomeId"))
            if wk is None or ab is None or ab not in ps.IDX:
                bad.append(f"week={wk} outcome={str(o.get('outcomeId'))[:8]}...")
                continue
            out.append((wk, ab))
    out.sort()
    return out, bad


def my_entry(mem):
    """The members response holds YOUR entry. It is a list or a single object
    depending on the view, and picking [0] off the wrong one silently reads a
    stranger -- so both shapes are handled and the id is returned with it."""
    if isinstance(mem, list):
        return mem[0] if mem else {}
    for k in ("entries", "members", "data"):
        v = mem.get(k)
        if isinstance(v, list) and v:
            return v[0]
    return mem if isinstance(mem, dict) else {}


def skeleton(node, path="$", out=None, depth=0):
    """Every path in a document, with what sits at it. Values are NOT recorded --
    a diff of two probes is about what the response CARRIES, and a picks array
    full of real picks is exactly what must not be printed."""
    out = {} if out is None else out
    if depth > 6: return out
    if isinstance(node, dict):
        # A map keyed on uuids (Splash's teams) would otherwise make every key a
        # separate path and drown the diff. Collapse it to one representative.
        keys = list(node)
        idish = len(keys) > 4 and all(re.fullmatch(r"[0-9a-f-]{8,36}", str(k) or "", re.I) for k in keys)
        out[path] = f"object[{len(keys)}]" + (" keyed by id" if idish else "")
        for k in (keys[:1] if idish else sorted(keys)):
            skeleton(node[k], f"{path}.{'<id>' if idish else k}", out, depth + 1)
    elif isinstance(node, list):
        out[path] = f"list[{len(node)}]"
        if node: skeleton(node[0], path + "[0]", out, depth + 1)
    else:
        out[path] = type(node).__name__
    return out


def diff_probes(old: pathlib.Path, new: pathlib.Path):
    """What did locking the week actually add?

    A GUESS ABOUT THIS IS FREE AND WRONG HALF THE TIME. Platforms reveal picks
    after a deadline, or they do not, and the only honest way to find out is to
    hold a probe from before against a probe from after. Structure only: no
    value from either side is printed, so a diff can be pasted."""
    names = sorted({p.stem for p in list(old.glob("*.json")) + list(new.glob("*.json"))})
    if not names:
        raise SystemExit(f"No .json in {old} or {new}. Run --probe --save on each first.")
    load = lambda d, n: json.loads((d / f"{n}.json").read_text(encoding="utf-8"))
    for n in names:
        try: a = skeleton(load(old, n))
        except FileNotFoundError: a = None
        try: b = skeleton(load(new, n))
        except FileNotFoundError: b = None
        print("=" * 72)
        if a is None: print(f"{n}: only in {new} -- a NEW endpoint answered"); continue
        if b is None: print(f"{n}: only in {old} -- it stopped answering"); continue
        added = sorted(set(b) - set(a))
        gone = sorted(set(a) - set(b))
        moved = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        if not (added or gone or moved):
            print(f"{n}: identical structure"); continue
        print(n)
        for k in added: print(f"  + {k}: {b[k]}")
        for k in gone:  print(f"  - {k}: {a[k]}")
        for k in moved: print(f"  ~ {k}: {a[k]} -> {b[k]}")
    print("=" * 72)
    print("A `+ ...picks...` line is the one worth having. No values were read.")


def splash_inspect(d: pathlib.Path):
    """Read what --probe --platform splash saved and print the parts a parser
    keys on -- plus the two things only a comparison can answer: whether the
    team ids join to our board, and what signing in actually buys."""
    load = lambda n: json.loads((d / f"splash_{n}.json").read_text(encoding="utf-8"))
    try:
        con, sl, ps_all = load("contest"), load("slates"), load("picksheets")
    except FileNotFoundError as e:
        raise SystemExit(f"{e.filename} not there. "
                         f"Run --platform splash --probe --save {d} first.")
    try: mine = load("picksheets_mine")
    except FileNotFoundError: mine = None

    c = con.get("contest") or con
    st = c.get("settings") or {}
    ent = c.get("entries") or {}
    print("=" * 72, "\nCONTEST -- the numbers a pool tab is made of")
    for k, v in (("entries filled", ent.get("filled")), ("cap", ent.get("max")),
                 ("max per user", ent.get("max_per_user")),
                 ("entry fee $", c.get("entry_fee_in_dollars")),
                 ("prize pool $", c.get("prize_pool_in_dollars")),
                 ("weeks (slateCount)", c.get("slateCount")),
                 ("status", c.get("status")), ("starts", c.get("contest_start_date"))):
        print(f"  {k:<20} {v!r}")
    print("  RULES THE OPTIMIZER ASSUMES, as this contest states them:")
    for k, want in (("pickReuseLimit", 0), ("entryLives", 1), ("expectedPicksCount", 1)):
        got = st.get(k)
        flag = "" if got == want else f"   <-- NOT {want}: the board's model does not describe this contest"
        print(f"    {k:<20} {got!r}{flag}")

    print("=" * 72, "\nSLATES -- the week map, and when each one locks")
    rows = (sl.get("data") if isinstance(sl, dict) else sl) or []
    for i, r in enumerate(rows[:20], 1):
        print(f"  {i:>2}. {str(r.get('abbreviation') or r.get('name'))[:12]:<12} "
              f"games {str(r.get('gamesCount')):>2}  locks {r.get('picksLockAt')}  "
              f"{r.get('status')}  picksheet={r.get('isPicksheetAvailable')}")

    print("=" * 72, "\nTEAMS -- do Splash's ids join to our board?")
    teams = ps_all.get("teams") or {}
    hit, miss = [], []
    for tid, t in teams.items():
        a = ps.norm(t.get("alias"))
        (hit if a in ps.IDX else miss).append(a or tid)
    print(f"  {len(teams)} teams, {len(hit)} join our 32, {len(miss)} do not")
    if miss:
        print(f"  ! unmatched: {sorted(miss)} -- add to pull_season.ALIAS before "
              "anything keys on these")
    g = (ps_all.get("games") or [{}])[0]
    print("\n  one game, in full (this is where a pick would be marked):")
    detail(g, 1, "games[0]", maxdepth=4)

    if mine is None:
        print("\n  (no picksheets_mine saved -- nothing to compare)")
        return
    print("=" * 72, "\nWHAT THE entryId BUYS")
    a, b = set(ps_all), set(mine)
    print(f"  keys only on the entry view: {sorted(b - a)}")
    print(f"  keys only on the slate view: {sorted(a - b)}")
    gm = (mine.get("games") or [{}])[0]
    extra = set(gm) - set(g)
    print(f"  extra keys on games[0]: {sorted(extra) or 'none'}")
    tm = (list((mine.get('teams') or {}).values()) or [{}])[0]
    t0 = (list(teams.values()) or [{}])[0]
    print(f"  extra keys on a team:   {sorted(set(tm) - set(t0)) or 'none'}")
    print("\n  A PICK HAS TO BE SOMEWHERE. If those three lines are empty, this "
          "response\n  carries none -- which is the answer, and it means reading "
          "your own picks\n  needs the session the browser had.")


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



def from_har(path: pathlib.Path, site: str | None = None):
    """Read a HAR exported from your OWN browser -- F12 > Network > Save all as HAR.

    THE ROUTE THAT CANNOT BE CHALLENGED. There is no automated browser here at
    all: you are already signed in, in the browser you always use, and this only
    reads the recording afterwards. When a captcha refuses the driven window,
    this is the fallback that always works.

    A HAR CONTAINS YOUR SESSION COOKIES AND AUTH HEADERS. It is read locally and
    only SHAPES are printed -- never paste the file itself anywhere, and delete it
    when done. .gitignore carries *.har for the same reason."""
    try:
        har = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except FileNotFoundError:
        raise SystemExit(f"No such file: {path}")
    entries = (har.get("log") or {}).get("entries") or []
    if not entries:
        raise SystemExit(f"{path} has no log.entries -- is it a HAR?")
    site = site or ""
    shown = 0
    print(f"{len(entries)} recorded request(s); api-shaped ones below\n")
    for e in entries:
        url = (e.get("request") or {}).get("url", "")
        if site and not is_api(url, site):
            continue
        res = e.get("response") or {}
        body = ((res.get("content") or {}).get("text")) or ""
        status = res.get("status")
        print("=" * 72)
        print(f"{(e.get('request') or {}).get('method','?')} {url[:150]}")
        print(f"  HTTP {status}  ({len(body)} bytes)")
        if not body:
            print("  (no body captured -- tick 'preserve log' and reload before saving)")
            continue
        try:
            detail(json.loads(body), 1, "$", maxdepth=3)
        except json.JSONDecodeError:
            print("  not JSON: " + body[:150].replace("\n", " "))
        shown += 1
    if not shown:
        print("Nothing api-shaped matched. Re-run without --site to see everything.")
    print("=" * 72)
    print("Names are redacted. Paste the shapes -- never the HAR: it holds your cookies.")


# ---------------------------------------------------------------------------
# WHAT YOU TYPED LAST TIME. This is a WEEKLY command -- lines move, ownership
# moves, the pool shrinks -- and it took a 76-character URL, a --platform and a
# path to a credentials file, none of which change from week to week. A bare run
# failed on a default group URL carrying no id, which is a default that cannot
# ever work.
#
# THE PATH TO THE .env IS REMEMBERED; THE CREDENTIALS ARE NOT. A path is not a
# secret, and the file it points at stays the one copy -- which is the whole
# argument for --env over copying the cookies here in the first place.
# ---------------------------------------------------------------------------
MEMO = HERE / ".survivor.json"


def recall() -> dict:
    try: return json.loads(MEMO.read_text(encoding="utf-8"))
    except Exception: return {}


def remember(**kw):
    """Only ever on a run that WORKED. Remembering a url that just failed is how
    a typo becomes the default and every later run fails the same way."""
    d = recall()
    d.update({k: v for k, v in kw.items() if v})
    try: MEMO.write_text(json.dumps(d, indent=1), encoding="utf-8")
    except Exception: pass          # read-only checkout: not worth failing a pull


ESPN_DEFAULT = f"https://fantasy.espn.com/games/{GAME}/group"


def resolve_url(flag, positional, memo=None, key="group_url"):
    """--url, else a bare URL, else what worked last time, else the ESPN page.

    THE DEFAULT LIVES HERE AND NOT ON THE FLAG. With `default=ESPN_DEFAULT` on
    --url the flag is never falsy, so a Splash URL typed bare would be overruled
    by a default nobody asked for -- and it would walk the ESPN pool while the
    command on screen names a Splash contest."""
    return flag or positional or (memo or {}).get(key) or ESPN_DEFAULT


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=None,
                    help="your pool's page, the one with ?id=<uuid>")
    # AND THE SAME THING WITHOUT THE FLAG. Every example of this command ends in
    # a URL, so typing it bare is the natural gesture -- and argparse answered a
    # correctly-formed command with `unrecognized arguments`. It is only ever a
    # URL in that position, so there is nothing for a positional to be confused
    # with. --url still works and wins if both are given, since passing the flag
    # is the more deliberate of the two.
    ap.add_argument("url_pos", nargs="?", metavar="URL",
                    help="the same thing without the flag")
    ap.add_argument("--env", metavar="PATH",
                    help=r"read SWID/ESPN_S2 from here instead of a local .env "
                         r"(e.g. C:\dev\draftkit\.env) -- better than a second copy")
    ap.add_argument("--har", metavar="FILE",
                    help="read a HAR your own browser exported -- no automation, so "
                         "nothing for a captcha to refuse")
    ap.add_argument("--no-hold", action="store_true",
                    help="close the browser after a few seconds instead of waiting for Enter")
    ap.add_argument("--platform", choices=["espn", "splash"], default="espn",
                    help="which pool platform the URL belongs to")
    ap.add_argument("--splash-user", metavar="UUID",
                    help="your Splash user id -- the entries endpoint is keyed on it and "
                         "the picks URL does not carry it. Without it that one call is skipped")
    ap.add_argument("--no-creds", action="store_true",
                    help="open the browser with no stored cookies -- sign in by hand. "
                         "Use for a site we hold no credentials for yet")
    ap.add_argument("--discover", action="store_true",
                    help="open the page in a browser and print the API calls it makes")
    ap.add_argument("--probe", action="store_true",
                    help="fetch every OBSERVED endpoint and describe each response")
    ap.add_argument("--save", metavar="DIR",
                    help="with --probe, also write each raw response there")
    ap.add_argument("--out", default="field.js")
    ap.add_argument("--splash-out", default="splash.js",
                    help="where --platform splash writes. Its OWN file, not field.js: two "
                         "pullers writing one file means whichever ran last wins and the "
                         "other pool silently vanishes")
    ap.add_argument("--force", action="store_true",
                    help="write even if the ownership table fails verification")
    ap.add_argument("--inspect", metavar="DIR",
                    help="read what --probe --save wrote and print the parts a parser keys on")
    ap.add_argument("--against", metavar="DIR",
                    help="with --inspect, diff the STRUCTURE of two saved probes -- what a "
                         "week locking actually added. No values are read, so it can be pasted")
    ap.add_argument("--dump", metavar="URL", help="fetch one endpoint and describe the response")
    a = ap.parse_args()
    memo = recall()
    typed = a.url or a.url_pos
    a.url = resolve_url(a.url, a.url_pos, memo,
                        "splash_url" if a.platform == "splash" else "group_url")
    a.env = a.env or memo.get("env")
    if not typed and a.url != ESPN_DEFAULT:
        print(f"(no url given, so: the {a.platform} one from your last successful run. "
              f"Pass one to change it.)", file=sys.stderr)

    if a.discover:
        return discover(a.url, a.env, skip_creds=a.no_creds, hold=not a.no_hold)

    if a.har:
        return from_har(pathlib.Path(a.har), registrable(a.url) if a.url else None)

    if a.inspect and a.against:
        # OLD then NEW: --inspect is the probe you already had, --against is the
        # one you just took. Backwards prints every gain as a loss.
        return diff_probes(pathlib.Path(a.inspect), pathlib.Path(a.against))

    if a.inspect:
        d = pathlib.Path(a.inspect)
        # Routed on the FILES, not on --platform: the flag says what you are
        # pulling and this reads what is already on disk, so obeying it would
        # refuse a directory that plainly holds the other platform's probe.
        both = (d / "splash_contest.json").exists() and (d / "group.json").exists()
        if a.platform == "splash" or ((d / "splash_contest.json").exists() and not both):
            return splash_inspect(d)
        if both:
            # One --save dir can hold both platforms' probes, and reading the
            # ESPN half in silence looks like the Splash half is not there.
            print(f"({d} also holds a splash probe -- "
                  f"python pull_field.py --platform splash --inspect {d})\n")
        return inspect(d)

    if a.platform == "splash" and not (a.probe or a.discover or a.har or a.inspect or a.dump):
        write_splash(splash_ids(a.url), a.splash_out,
                     token=splash_token(a.env), force=a.force)
        remember(splash_url=a.url, env=a.env)
        return

    if a.probe:
        if a.platform == "splash":
            ids = splash_ids(a.url)
            print("ids read from the URL: " + ", ".join(f"{k}={v}" for k, v in ids.items()))
            cid = ids["contest"]
            out_dir = pathlib.Path(a.save) if a.save else None
            if out_dir: out_dir.mkdir(parents=True, exist_ok=True)
            eps = splash_endpoints(ids, a.splash_user)
            token = splash_token(a.env)
            print("location-token-v2: " + ("present" if token else
                  "ABSENT -- set SPLASH_LOCATION_TOKEN if these come back 401"))
            if not a.splash_user:
                print("no --splash-user, so the entries call is skipped rather than guessed")
            for name, url in eps.items():
                print("=" * 72)
                print(f"{name}\n  {url}")
                # No ESPN cookies here, ever. fetch() would refuse them anyway;
                # not passing them is the belt to that brace.
                status, body = fetch(url, {}, token=token)
                print(f"  HTTP {status}  ({len(body)} bytes)")
                if status != 200:
                    print("  " + body[:400].replace("\n", " ")); continue
                try: data = json.loads(body)
                except json.JSONDecodeError:
                    print("  not JSON: " + body[:200]); continue
                detail(data, 1, name, maxdepth=3)
                if out_dir:
                    (out_dir / f"splash_{name}.json").write_text(
                        json.dumps(data, indent=1), encoding="utf-8")
                    print(f"  -> saved {out_dir / ('splash_' + name + '.json')}")
            print("=" * 72)
            print("THE SIGNED-IN CAPTURE SHOWED NO OWNERSHIP AND NO ENTRANTS ENDPOINT, so\n"
                  "what Splash can supply is POOL SIZE and YOUR OWN PICKS. Ownership stays\n"
                  "modelled here; a number invented to fill that column would look exactly\n"
                  "like ESPN's measured one. Nothing was written to field.js.")
            return
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
        # DEMANDING ESPN COOKIES FOR A URL THAT IS NOT ESPN'S is how a good
        # session gets refused for the wrong reason -- and fetch() would decline
        # to send them there anyway. Ask for what the target actually needs.
        host = (urllib.parse.urlparse(a.dump).hostname or "").lower()
        espn = under(host, COOKIE_SCOPE)
        status, body = fetch(a.dump, creds(a.env) if espn else {},
                             token=splash_token(a.env) if under(host, SPLASH_SCOPE) else "")
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

    print("members ...", end=" ", flush=True)
    st, body = fetch(urls["members"], c)
    mem = json.loads(body) if st == 200 else {}
    mine, bad = decode_picks(my_entry(mem), prop)
    print(f"your entry has {len(mine)} pick(s): "
          + (", ".join(f"wk{w} {t}" for w, t in mine) or "none yet"))
    if bad:
        print(f"  ! {len(bad)} pick(s) did not decode and were DROPPED: {bad[:4]}\n"
              "  ! A burned team we invent is one the board stops offering you all season.",
              file=sys.stderr)

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

    spread = counter_spread(by_week, counts)
    if spread:
        wk, lo, hi, rel = spread[0]
        print(f"\ncounter agreement: worst week is {wk}, count/percentage implies "
              f"{lo:,}-{hi:,} ({rel*100:.1f}% spread)")
        if rel > 0.02:
            print("  ! Within one week the two fields disagree about the size of the field\n"
                  "  ! they are counting. `percentage` may not be `count / total`, and the\n"
                  "  ! shares are what everything downstream runs on. Worth a look before\n"
                  "  ! trusting the board.", file=sys.stderr)

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
        # YOUR OWN PICKS, decoded. This is the "teams already burned" box filled
        # in from the record rather than retyped -- and unlike ownership it is
        # about THIS pool exactly, not ESPN at large. Rivals' picks are not here:
        # the group view carries scores and no picks, so the field's burned teams
        # remain the largest modelled-away term in the leverage half.
        "mine": [{"week": w, "team": t} for w, t in mine],
    }
    p = pathlib.Path(a.out)
    p.write_text("/* Generated by pull_field.py -- do not edit by hand. */\n"
                 "window.FIELD = " + json.dumps(out, separators=(",", ":")) + ";\n",
                 encoding="utf-8")
    print(f"\nwrote {p}: ownership for {len(by_week)} week(s), "
          f"pool {out['group']['surviving']}/{out['group']['size']} alive, "
          f"{len(mine)} of your own pick(s).")
    print("Open index.html -- ownership now comes from ESPN's counters, not the softmax.")
    remember(group_url=a.url, env=a.env)
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
