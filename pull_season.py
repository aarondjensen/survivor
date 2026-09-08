#!/usr/bin/env python3
"""Pull the REAL NFL schedule and betting market, and write season.js.

    python pull_season.py --dump        # what does the source actually return? writes nothing
    python pull_season.py               # pull, price, write season.js
    python pull_season.py --source espn
    python pull_season.py --ratings my_ratings.csv

Run it beside index.html. The page loads season.js if it is there and falls back
to its embedded sample if it is not, so a failed pull leaves you on the labelled
sample rather than on a half-built board.

THREE TIERS OF TRUTH, AND THE PAGE PRINTS WHICH ONE EACH GAME GOT:

  MARKET   a posted moneyline, de-vigged. This is an actual traded price and it
           is as real as a win probability gets.
  MARKET   a posted point spread, through a normal curve (sigma 13.2 pts).
  MODEL    everything else -- priced off team ratings FITTED by least squares to
           the lines that do exist.

Nobody publishes real win probabilities for week 15 in September, because none
exist: every product you can buy is running the third tier over the first two.
So `note`, `market_games` and `model_games` ride in season.js and the page says
so under the board rather than letting a model output read as a quoted price.

SOURCES. nflverse is primary: one CSV, the whole season, real spreads AND
moneylines, served from raw.githubusercontent.com, which does not bot-filter a
script. ESPN is the fallback and needs 18 requests. ESPN answered HTTP 403 to a
bare urllib request in testing -- no Accept headers is a bot fingerprint -- so
BROWSER_HEADERS exists and --dump prints the response body on a refusal, because
"403" alone does not tell you whether it was the edge or the endpoint.

THE PARSERS ARE UNVERIFIED FROM WHERE THIS WAS WRITTEN. It was authored in a
sandbox where every outbound domain answered EGRESS_BLOCKED, so both schemas are
expected, not observed. That is why --dump leads the interface and prints raw
columns, and why failures name what they SAW rather than asserting a cause.
"""
from __future__ import annotations
import argparse, csv, datetime, io, json, math, pathlib, re, sys, urllib.request, urllib.error

NFLVERSE = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
ESPN = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        "?dates={year}&seasontype=2&week={week}")
WEEKS, HFA, SIGMA = 18, 2.0, 13.2

# Ridge pins the otherwise-free additive constant (the data only ever determines
# DIFFERENCES between ratings) and keeps the fit sane on thin data. It also
# SHRINKS, and 1.0 shrank hard: measured against known ratings over 40 seeded
# seasons at the density a real September pull has (112 lined games), it
# compressed the ladder 14% -- fitted range 13.6 pts against a true 15.6, mean
# error 0.49. Every unlined week is priced off these ratings, so that
# compression lands on the 160 games the tool is actually reasoning about,
# pulling them all toward a coin flip. 0.1 measures at 0.982 of true scale and
# 0.18 mean error, and is still large enough to condition the solve. Lower ridge
# won at EVERY density tested, including the thin end where regularisation was
# supposed to be earning its keep -- it buys ~0.1 pts of error there and costs
# a third of the scale. See test_fit.py.
RIDGE = 0.1

# One week of lines cannot fit 32 ratings: every team has appeared, but a team
# played once cannot be told apart from its single opponent. Measured slope of
# fitted against true, same 40 seasons -- 16 lined: 0.504, 32: 0.868, 48: 0.935,
# 64: 0.960, flat after. So the bar is three weeks of lines, not the one week
# the first cut used, which stayed silent at exactly the density that fails.
MIN_LINES = 48

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

TEAMS = [  # order is the contract: index -> team, and it must not drift
    ("BUF","Buffalo Bills","AFC","East"),      ("MIA","Miami Dolphins","AFC","East"),
    ("NE","New England Patriots","AFC","East"),("NYJ","New York Jets","AFC","East"),
    ("BAL","Baltimore Ravens","AFC","North"),  ("CIN","Cincinnati Bengals","AFC","North"),
    ("CLE","Cleveland Browns","AFC","North"),  ("PIT","Pittsburgh Steelers","AFC","North"),
    ("HOU","Houston Texans","AFC","South"),    ("IND","Indianapolis Colts","AFC","South"),
    ("JAX","Jacksonville Jaguars","AFC","South"),("TEN","Tennessee Titans","AFC","South"),
    ("DEN","Denver Broncos","AFC","West"),     ("KC","Kansas City Chiefs","AFC","West"),
    ("LV","Las Vegas Raiders","AFC","West"),   ("LAC","Los Angeles Chargers","AFC","West"),
    ("DAL","Dallas Cowboys","NFC","East"),     ("NYG","New York Giants","NFC","East"),
    ("PHI","Philadelphia Eagles","NFC","East"),("WAS","Washington Commanders","NFC","East"),
    ("CHI","Chicago Bears","NFC","North"),     ("DET","Detroit Lions","NFC","North"),
    ("GB","Green Bay Packers","NFC","North"),  ("MIN","Minnesota Vikings","NFC","North"),
    ("ATL","Atlanta Falcons","NFC","South"),   ("CAR","Carolina Panthers","NFC","South"),
    ("NO","New Orleans Saints","NFC","South"), ("TB","Tampa Bay Buccaneers","NFC","South"),
    ("ARI","Arizona Cardinals","NFC","West"),  ("LAR","Los Angeles Rams","NFC","West"),
    ("SEA","Seattle Seahawks","NFC","West"),   ("SF","San Francisco 49ers","NFC","West"),
]
IDX = {a: i for i, (a, *_) in enumerate(TEAMS)}
# nflverse spells the Rams "LA" and Washington "WAS"; ESPN says "WSH" and "LAR".
ALIAS = {"WSH":"WAS","LA":"LAR","JAC":"JAX","SD":"LAC","OAK":"LV","STL":"LAR","ARZ":"ARI","BLT":"BAL","HST":"HOU","CLV":"CLE"}
norm = lambda a: ALIAS.get((a or "").strip().upper(), (a or "").strip().upper())
num = lambda s: float(s) if (s or "").strip() not in ("", "NA", "NaN", "null", "None") else None


def get(url: str) -> bytes:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=BROWSER_HEADERS), timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", "replace")[:400].replace("\n", " ")
        except Exception: pass
        raise SystemExit(
            f"HTTP {e.code} from {url}\n"
            + {403: "  403 is a REFUSAL, not a missing page. Either the host's edge blocked the\n"
                    "  request (bot filtering) or the endpoint needs credentials. Open the URL in\n"
                    "  a browser: if it loads there, it is the edge, and --source nflverse avoids\n"
                    "  it entirely -- that is a plain CSV on raw.githubusercontent.com.",
               404: "  404 means that path is not published. For ESPN that usually means the week\n"
                    "  does not exist yet; check --year.",
               429: "  429 is rate limiting. Wait a few minutes and re-run.",
              }.get(e.code, "  Unexpected status; the response body is below.")
            + (f"\n  body: {body}" if body else ""))
    except Exception as e:
        raise SystemExit(f"{type(e).__name__}: {e}\n  URL: {url}\n"
                         "  Nothing was written. If this is a proxy or DNS failure it is local to\n"
                         "  this machine, not to the source.")


def ml_prob(m: float) -> float:
    """American moneyline -> implied probability, vig included."""
    return (-m) / ((-m) + 100) if m < 0 else 100 / (m + 100)


# ---------------------------------------------------------------- nflverse ---
def rows_nflverse(year: int, dump=False):
    text = get(NFLVERSE).decode("utf-8", "replace")
    rdr = csv.DictReader(io.StringIO(text))
    cols = rdr.fieldnames or []
    if dump:
        print(f"columns ({len(cols)}): {cols}\n")
    need = {"season", "week", "away_team", "home_team"}
    if not need <= set(cols):
        raise SystemExit(f"nflverse CSV is missing {sorted(need - set(cols))}.\n"
                         f"  It has: {cols}\n  The schema moved; fix rows_nflverse().")
    out, shown = [], 0
    for r in rdr:
        if str(r.get("season")) != str(year):
            continue
        if (r.get("game_type") or "REG").strip().upper() != "REG":
            continue
        try: wk = int(float(r["week"]))
        except (TypeError, ValueError): continue
        if not 1 <= wk <= WEEKS: continue
        h, a = norm(r["home_team"]), norm(r["away_team"])
        if h not in IDX or a not in IDX:
            print(f"  ! unrecognised team code(s) {h}/{a} -- add to ALIAS", file=sys.stderr); continue
        hml, aml = num(r.get("home_moneyline")), num(r.get("away_moneyline"))
        spread = num(r.get("spread_line"))          # positive = HOME favoured
        p = None
        if hml is not None and aml is not None:     # de-vig two real prices
            ph, pa = ml_prob(hml), ml_prob(aml)
            if ph + pa > 0: p, tier = ph / (ph + pa), "moneyline"
        if p is None and spread is not None:
            p, tier = norm_cdf(spread / SIGMA), "spread"
        if p is None:
            tier = None
        if dump and shown < 5:
            print(f"  wk{wk:<2} {a:>3} @ {h:<3}  spread={spread}  ml={aml}/{hml}  -> "
                  f"{'%.3f' % p if p is not None else 'no line'} ({tier or 'model'})")
            shown += 1
        out.append({"week": wk, "home": h, "away": a, "p_home": p, "tier": tier, "spread": spread})
    if dump:
        print(f"\n{year} REG rows: {len(out)}   with a market price: "
              f"{sum(1 for r in out if r['p_home'] is not None)}")
    return out


# -------------------------------------------------------------------- espn ---
def rows_espn(year: int, dump=False):
    out = []
    weeks = [int(dump)] if isinstance(dump, int) and dump is not True else range(1, WEEKS + 1)
    for w in weeks:
        d = json.loads(get(ESPN.format(year=year, week=w)).decode("utf-8", "replace"))
        ev = d.get("events", [])
        if dump:
            print(f"top-level keys: {sorted(d.keys())}\nseason: {d.get('season')}  week: {d.get('week')}")
            print(f"events: {len(ev)}")
        got = 0
        for e in ev:
            for comp in e.get("competitions", []):
                h = a = None
                for c in comp.get("competitors", []):
                    ab = norm((c.get("team") or {}).get("abbreviation"))
                    if ab not in IDX: continue
                    if c.get("homeAway") == "home": h = ab
                    elif c.get("homeAway") == "away": a = ab
                if not h or not a: continue
                spread, p, tier = espn_spread(comp, h), None, None
                if spread is not None:
                    p, tier = norm_cdf(spread / SIGMA), "spread"
                out.append({"week": w, "home": h, "away": a, "p_home": p, "tier": tier, "spread": spread})
                got += 1
                if dump and got <= 4:
                    print(f"  {a} @ {h}  odds={[o.get('details') for o in comp.get('odds') or []]}  spread={spread}")
        if not dump:
            print(f"week {w:>2}: {got:>2} games, {sum(1 for r in out if r['week']==w and r['p_home'] is not None):>2} with a line")
    return out


def espn_spread(comp: dict, home: str):
    """`details` names the FAVOURITE ("MIA -3.5"); a bare signed number does not
    say who it is signed against. Returns a HOME-perspective margin."""
    for o in comp.get("odds", []) or []:
        det = (o.get("details") or "").strip()
        if det.upper() in ("EVEN", "PK", "PICK", "PICK'EM"):
            return 0.0
        m = re.match(r"^([A-Z]{2,4})\s*([+-]?\d+(?:\.\d+)?)$", det)
        if m and norm(m.group(1)) in IDX:
            pts = abs(float(m.group(2)))
            return pts if norm(m.group(1)) == home else -pts
    return None


# --------------------------------------------------------------- lookahead ---
SPREAD_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)")
ORPHAN_MAX = 8        # spreads on a bye week before the table is refused
ORPHAN_AGREE = 1.0    # pts the two sides of one game may differ by before warning

def read_lookahead(path):
    """Parse a pasted LOOKAHEAD SPREAD table -- e.g. 4for4's, which posts a line
    for every team in every week, not just the games a book has hung yet. That is
    the input this tool is otherwise missing: real market numbers for week 15.

    THE SIGN CONVENTION IS THE BETTING ONE: negative means that team is FAVOURED
    by that many points, so their expected margin is the negation. It is stated
    rather than detected, and then CHECKED -- reconcile() holds every parsed cell
    against the real schedule, and a format misread shows up as a pile of
    spreads for teams that are on a bye.

    Two shapes are accepted, because a copy-paste lands as either:
      grid  TEAM, w1, w2, ... w18          (blank / BYE / - for a bye)
      long  TEAM, WEEK, SPREAD
    """
    p = pathlib.Path(path)
    if not p.exists():
        raise SystemExit(
            f"No such file: {path}\n\n"
            "  --lookahead reads a table YOU save; nothing downloads it, because the sites\n"
            "  that publish lookahead spreads sit behind a subscription. Copy the table out\n"
            "  of the page, save it beside this script, and pass that filename. Either shape\n"
            "  parses:\n\n"
            "      LAR,-3.5,-7,+1.5,BYE,-6,...        one row per team, week 1 onward\n"
            "      LAR,1,-3.5                         or team, week, spread\n\n"
            "  Negative means that team is FAVOURED. Nothing was written; the pull works\n"
            "  without it -- you just get model numbers for the weeks no book has lined yet.")
    got = {}                                   # (team_idx, week) -> team-perspective spread
    grid_rows = long_rows = skipped = 0
    for raw in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line: continue
        parts = [p.strip() for p in re.split(r"[,\t;|]", line)]
        if len(parts) < 2: continue
        team = norm(parts[0])
        if team not in IDX:
            skipped += 1; continue
        cells = parts[1:]
        if len(cells) == 2 and re.fullmatch(r"\d{1,2}", cells[0] or ""):
            wk = int(cells[0])
            v = parse_cell(cells[1])
            if 1 <= wk <= WEEKS and v is not None:
                got[(IDX[team], wk)] = v; long_rows += 1
            continue
        for i, cell in enumerate(cells[:WEEKS]):
            v = parse_cell(cell)
            if v is not None:
                got[(IDX[team], i + 1)] = v
        grid_rows += 1
    print(f"lookahead: {grid_rows} grid row(s), {long_rows} long row(s), "
          f"{len(got)} team-weeks with a spread"
          + (f", {skipped} line(s) skipped (no team code)" if skipped else ""))
    return got


def parse_cell(cell):
    c = (cell or "").strip()
    if not c or c.upper() in ("BYE", "-", "--", "NA", "OFF", "N/A"): return None
    if c.upper() in ("PK", "PICK", "EVEN", "PICK'EM"): return 0.0
    m = SPREAD_RE.search(c)                     # tolerates "at KC -3.5"
    return float(m.group(1)) if m else None


def apply_lookahead(rows, look):
    """Fold team-perspective spreads onto the real fixtures, and REPORT the join.
    A spread whose team is on a bye that week is the signature of a misread
    table, so it is counted and refused rather than quietly dropped."""
    by_slot = {}
    for g in rows:
        by_slot[(IDX[g["home"]], g["week"])] = (g, True)
        by_slot[(IDX[g["away"]], g["week"])] = (g, False)
    applied, orphan, agree = 0, [], []
    seen = set()
    for (t, wk), sp in sorted(look.items()):
        hit = by_slot.get((t, wk))
        if not hit:
            orphan.append(f"{TEAMS[t][0]} wk{wk}"); continue
        g, is_home = hit
        margin = -sp if is_home else sp         # -3.5 for a team = that team by 3.5
        key = (g["week"], g["home"], g["away"])
        if key in seen and g.get("_look") is not None:
            agree.append(abs(g["_look"] - margin))   # both sides listed: they should match
            margin = (g["_look"] + margin) / 2
        seen.add(key)
        g["_look"] = margin
        applied += 1
    for g in rows:
        if g.get("_look") is not None:
            g["spread"], g["p_home"], g["tier"] = g["_look"], norm_cdf(g["_look"] / SIGMA), "lookahead"
    print(f"           applied to {sum(1 for g in rows if g['tier']=='lookahead')} of {len(rows)} fixtures"
          + (f"; both sides listed, worst disagreement {max(agree):.1f} pts" if agree else ""))

    # Both sides of one game must state the same line with opposite signs. They
    # disagree only if the table was misaligned or the sign convention is not the
    # betting one -- either way the numbers are not what they look like.
    if agree and max(agree) > ORPHAN_AGREE:
        print(f"  ! The two sides of the same game disagree by up to {max(agree):.1f} pts.\n"
              f"  ! In a correct table they are equal and opposite. Suspect a column offset,\n"
              f"  ! or spreads written from the opponent's perspective.", file=sys.stderr)

    # A correct table has ZERO spreads on a bye week: every cell is a real fixture.
    # 8 is slack for a ragged paste, not a tolerance band -- a one-week column shift
    # produces about 32 (one per team), and the first cut's 20%-of-parsed threshold
    # sat at 108, so it waved exactly that through.
    if orphan:
        print(f"  ! {len(orphan)} spread(s) for a team that is NOT PLAYING that week: "
              f"{', '.join(orphan[:8])}{'...' if len(orphan) > 8 else ''}", file=sys.stderr)
        if len(orphan) > ORPHAN_MAX:
            raise SystemExit(
                f"\n{len(orphan)} spreads land on a bye. A correct table has none -- this is what a\n"
                "misread looks like, and a one-week column shift produces about one per team.\n"
                "Nothing written. Check the paste, or pass --lookahead-start to say which week\n"
                "the first column actually is.")
    return rows


# ------------------------------------------------------------------- maths ---
def norm_cdf(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def fit_ratings(rows):
    """Least squares: r_home - r_away + HFA = margin, over every game with a
    posted spread. Ridge-regularised, which pins the otherwise-free additive
    constant and keeps the fit sane when only a handful of games are lined."""
    n = len(TEAMS)
    A = [[0.0] * n for _ in range(n)]; b = [0.0] * n; used = 0
    for g in rows:
        if g.get("spread") is None: continue
        i, j = IDX[g["home"]], IDX[g["away"]]
        d = g["spread"] - HFA
        A[i][i] += 1; A[j][j] += 1; A[i][j] -= 1; A[j][i] -= 1
        b[i] += d; b[j] -= d; used += 1
    for i in range(n): A[i][i] += RIDGE
    return solve(A, b), used


def solve(A, b):
    """Gaussian elimination, partial pivoting. 32x32 -- no numpy, because a
    dependency for one small solve is one you have to install on draft morning."""
    n = len(b); M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12: continue
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r == c: continue
            f = M[r][c] / M[c][c]
            if f:
                for k in range(c, n + 1): M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]


def build(rows, ratings, year, source, tiers):
    sched = [[None] * WEEKS for _ in TEAMS]
    clash = []
    for g in rows:
        h, a, w = IDX[g["home"]], IDX[g["away"]], g["week"] - 1
        for me, opp in ((h, a), (a, h)):
            cur = sched[me][w]
            if cur is not None and cur["o"] != opp:
                clash.append(f"{TEAMS[me][0]} is booked twice in week {w+1}: "
                             f"vs {TEAMS[cur['o']][0]} and vs {TEAMS[opp][0]}")
        p = g["p_home"]
        if p is None:
            p = norm_cdf((ratings[h] - ratings[a] + HFA) / SIGMA)
        sched[h][w] = {"o": a, "h": 1, "p": round(p, 4)}
        sched[a][w] = {"o": h, "h": 0, "p": round(1 - p, 4)}
    mk = tiers["moneyline"] + tiers["spread"]
    return {
        "_clash": clash,
        "label": f"{year} NFL season",
        "note": (f"Real {year} schedule from {source}. "
                 f"{tiers['moneyline']} games priced from a posted moneyline and "
                 f"{tiers['spread']} from a posted spread; the remaining {tiers['model']} "
                 "are model output from ratings fitted to those lines, not quoted prices."),
        "source": source, "market_games": mk, "model_games": tiers["model"],
        "odds_games": mk,
        "pulled_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "weeks": WEEKS, "hfa": HFA, "sigma": SIGMA,
        "teams": [{"abbr": a, "name": n, "conf": c, "div": d, "rating": round(ratings[i], 2)}
                  for i, (a, n, c, d) in enumerate(TEAMS)],
        "sched": sched,
    }


def verify(rows, out):
    # A doubled fixture cannot be seen in the COUNTS -- the second write lands on
    # the same team-week cell and overwrites the first, so the team still shows 17.
    # build() is the only place that can notice, and it hands them over here.
    problems = list(out.get("_clash", []))
    weeks_seen = {g["week"] for g in rows}
    missing = [w for w in range(1, WEEKS + 1) if w not in weeks_seen]
    if missing:
        problems.append(f"no games at all in week(s) {missing}")
    # EXACTLY 17. Allowing 16 as slack was the first cut and it swallowed a test
    # season with three fixtures deleted -- the precise shape this refuses.
    for t, row in enumerate(out["sched"]):
        played = sum(1 for c in row if c)
        if played != 17:
            problems.append(f"{TEAMS[t][0]} has {played} games, expected 17"
                            + (" -- a fixture is missing" if played < 17 else " -- a fixture is doubled"))
    for w in range(WEEKS):
        if sum(1 for t in range(len(TEAMS)) if out["sched"][t][w]) % 2:
            problems.append(f"week {w+1} has an odd number of teams playing")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--source", choices=["nflverse", "espn"], default="nflverse")
    ap.add_argument("--dump", nargs="?", const=True, default=False,
                    help="show what the source returns and write nothing (ESPN: a week number)")
    ap.add_argument("--lookahead", metavar="CSV",
                    help="pasted lookahead-spread table (e.g. 4for4) -- real market numbers "
                         "for EVERY week, not just the games a book has hung yet")
    ap.add_argument("--lookahead-start", type=int, default=1, metavar="WEEK",
                    help="which week the grid's first column is (default 1)")
    ap.add_argument("--ratings", metavar="CSV", help="TEAM,rating per line instead of fitting")
    ap.add_argument("--out", default="season.js")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    pull = rows_nflverse if a.source == "nflverse" else rows_espn
    if a.dump:
        arg = int(a.dump) if a.source == "espn" and a.dump is not True else True
        pull(a.year, arg)
        return

    rows = pull(a.year)
    if not rows:
        raise SystemExit(f"No {a.year} regular-season games from {a.source}. Run --dump to see what came back.\n"
                         "  If the season is not released yet, try --year with last season.")

    if a.lookahead:
        look = read_lookahead(a.lookahead)
        if a.lookahead_start != 1:
            look = {(t, w + a.lookahead_start - 1): v for (t, w), v in look.items()}
        rows = apply_lookahead(rows, look)

    if a.ratings:
        vals = {}
        with open(a.ratings, newline="", encoding="utf-8") as fh:
            for r in csv.reader(fh):
                if len(r) >= 2 and norm(r[0]) in IDX:
                    try: vals[IDX[norm(r[0])]] = float(r[1])
                    except ValueError: pass
        if len(vals) < len(TEAMS):
            print(f"  ! {a.ratings} covers {len(vals)}/{len(TEAMS)} teams; the rest sit at 0.0", file=sys.stderr)
        ratings, fitted = [vals.get(i, 0.0) for i in range(len(TEAMS))], 0
    else:
        ratings, fitted = fit_ratings(rows)
        print(f"\nfitted ratings to {fitted} posted spreads (range {min(ratings):+.1f} to {max(ratings):+.1f})")
        if fitted < MIN_LINES:
            print(f"  ! Only {fitted} posted spreads -- under {MIN_LINES} (three weeks), the fit\n"
                  f"  ! recovers roughly half the true spread between teams, so every unlined\n"
                  f"  ! week is pulled toward a coin flip and future value is flattened with it.\n"
                  f"  ! Re-run once more games are lined, or pass --ratings / --lookahead.",
                  file=sys.stderr)

    tiers = {"moneyline": sum(1 for r in rows if r["tier"] == "moneyline"),
             "spread":    sum(1 for r in rows if r["tier"] in ("spread", "lookahead")),
             "model":     sum(1 for r in rows if r["tier"] is None)}
    out = build(rows, ratings, a.year, a.source, tiers)
    problems = verify(rows, out)
    if problems:
        print("\nVERIFICATION FAILED:", file=sys.stderr)
        for p in problems[:12]: print("  - " + p, file=sys.stderr)
        if not a.force:
            raise SystemExit("\nNothing written. The page keeps its labelled sample, which is the honest\n"
                             "outcome -- a schedule three games short renders exactly like a complete one.\n"
                             "Pass --force if you know why and want it anyway.")
        print("  (--force: writing anyway)", file=sys.stderr)

    out.pop("_clash", None)          # diagnostics, not board data
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("/* Generated by pull_season.py -- do not edit by hand. */\n")
        fh.write("window.SEASON = " + json.dumps(out, separators=(",", ":")) + ";\n")
    print(f"\nwrote {a.out}: {len(rows)} games -- {tiers['moneyline']} moneyline, "
          f"{tiers['spread']} spread, {tiers['model']} modelled.")
    print("Open index.html -- the masthead stamp turns green and names the pull.")


if __name__ == "__main__":
    main()
