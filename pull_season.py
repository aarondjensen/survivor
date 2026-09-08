#!/usr/bin/env python3
"""Pull the REAL NFL schedule and market spreads, and write season.js.

    python pull_season.py --dump 3      # what does the API actually return? writes nothing
    python pull_season.py               # pull the season, fit ratings, write season.js
    python pull_season.py --ratings my_ratings.csv    # supply ratings yourself

Run it beside index.html. The page loads season.js if it is there and falls back
to its embedded sample if it is not, so a failed pull leaves you on the sample
rather than on a half-built board.

WHAT IS REAL HERE AND WHAT IS MODELLED -- the whole point of this file:

  REAL     the schedule. Every fixture, home and away, byes included.
  REAL     the point spread on any game a book has posted a line for. In
           September that is this week and maybe next; it is not week 15.
  MODELLED every win probability. A spread becomes a probability through a
           normal curve (sigma 13.2 pts); a week with no posted line is priced
           from team ratings FITTED to the spreads that do exist.

Nobody publishes real win probabilities for week 15 in September, because none
exist -- every source you can buy is running the same kind of model over the
same kind of ratings. So this does not pretend: `note` and `odds_games` ride in
season.js and the page prints them under the board.

THE ENDPOINT IS UNVERIFIED FROM WHERE THIS WAS WRITTEN. It was authored in a
sandbox with no outbound network, so the response shape below is expected, not
observed. That is why --dump exists and why every failure names what it SAW
rather than asserting a cause: a confident wrong diagnosis costs more than a
vague right one. If the shape has moved, --dump shows you where.
"""
from __future__ import annotations
import argparse, csv, datetime, json, re, sys, urllib.request, urllib.error

API = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
       "?dates={year}&seasontype=2&week={week}")
WEEKS, HFA, SIGMA, RIDGE = 18, 2.0, 13.2, 1.0
UA = {"User-Agent": "Mozilla/5.0 (survivor/pull_season.py)"}

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
ALIAS = {"WSH": "WAS", "LA": "LAR", "JAC": "JAX", "SD": "LAC", "OAK": "LV", "STL": "LAR"}
norm = lambda a: ALIAS.get((a or "").upper(), (a or "").upper())


def fetch(year: int, week: int) -> dict:
    url = API.format(year=year, week=week)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"week {week}: HTTP {e.code} from {url}\n"
                         f"  A 404 usually means that week is not published yet.")
    except Exception as e:
        raise SystemExit(f"week {week}: {type(e).__name__}: {e}\n  URL: {url}")


def games(payload: dict, week: int) -> list[dict]:
    """Pull (away, home, spread) out of one week. Unknown abbreviations are
    DROPPED and named -- a game silently attached to the wrong team is worse
    than a missing one."""
    out, unknown = [], set()
    for ev in payload.get("events", []):
        for comp in ev.get("competitions", []):
            home = away = None
            for c in comp.get("competitors", []):
                ab = norm((c.get("team") or {}).get("abbreviation"))
                if ab not in IDX:
                    unknown.add(ab or "?"); continue
                if c.get("homeAway") == "home": home = ab
                elif c.get("homeAway") == "away": away = ab
            if home is None or away is None:
                continue
            out.append({"week": week, "home": home, "away": away, "spread": spread_of(comp)})
    if unknown:
        print(f"  ! week {week}: unrecognised team codes {sorted(unknown)} -- add them to ALIAS",
              file=sys.stderr)
    return out


def spread_of(comp: dict):
    """`details` is the authority, not the `spread` number: "MIA -3.5" names the
    favourite, and a bare signed number does not say who it is signed against.
    Returns (favoured_abbr, points) or None."""
    for o in comp.get("odds", []) or []:
        det = (o.get("details") or "").strip()
        m = re.match(r"^([A-Z]{2,4})\s*([+-]?\d+(?:\.\d+)?)$", det)
        if m and norm(m.group(1)) in IDX:
            pts = abs(float(m.group(2)))
            if pts > 0:
                return (norm(m.group(1)), pts)
        if det.upper() in ("EVEN", "PK", "PICK", "PICK'EM"):
            return None
    return None


def fit_ratings(rows: list[dict]) -> tuple[list[float], int]:
    """Least squares on the posted spreads: find ratings r such that
    r_fav - r_dog = points -/+ HFA for every game with a line. Ridge-regularised
    toward zero, which both pins the otherwise-free additive constant and keeps
    the fit sane when only a handful of games have been lined."""
    n = len(TEAMS)
    A = [[0.0] * n for _ in range(n)]
    b = [0.0] * n
    used = 0
    for g in rows:
        if not g["spread"]:
            continue
        fav, pts = g["spread"]
        dog = g["away"] if fav == g["home"] else g["home"]
        if fav not in IDX or dog not in IDX:
            continue
        # fav at home already carries HFA, so it explains that much of the line
        d = pts - HFA if fav == g["home"] else pts + HFA
        i, j = IDX[fav], IDX[dog]
        A[i][i] += 1; A[j][j] += 1; A[i][j] -= 1; A[j][i] -= 1
        b[i] += d;    b[j] -= d
        used += 1
    for i in range(n):
        A[i][i] += RIDGE
    return solve(A, b), used


def solve(A, b):
    """Gaussian elimination with partial pivoting. 32x32 -- no numpy, because a
    dependency for one small solve is a dependency you have to install on draft
    morning."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            continue
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r == c: continue
            f = M[r][c] / M[c][c]
            if f:
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]


def norm_cdf(x: float) -> float:
    import math
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def build(rows, ratings, year, odds_used):
    sched = [[None] * WEEKS for _ in TEAMS]
    clash = []          # two different fixtures claiming one team-week
    for g in rows:
        h, a, w = IDX[g["home"]], IDX[g["away"]], g["week"] - 1
        for me, opp in ((h, a), (a, h)):
            cur = sched[me][w]
            if cur is not None and cur["o"] != opp:
                clash.append(f"{TEAMS[me][0]} is booked twice in week {w+1}: "
                             f"vs {TEAMS[cur['o']][0]} and vs {TEAMS[opp][0]}")
        if g["spread"]:                       # a posted line beats the model
            fav, pts = g["spread"]
            margin = pts if fav == g["home"] else -pts
        else:
            margin = ratings[h] - ratings[a] + HFA
        p = norm_cdf(margin / SIGMA)
        sched[h][w] = {"o": a, "h": 1, "p": round(p, 4)}
        sched[a][w] = {"o": h, "h": 0, "p": round(1 - p, 4)}
    return {
        "_clash": clash,
        "label": f"{year} NFL season",
        "note": (f"Real {year} schedule pulled from the ESPN scoreboard API. "
                 f"{odds_used} games carried a posted point spread and are priced off it; "
                 "the rest are priced from team ratings fitted to those spreads."),
        "source": "site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "pulled_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "odds_games": odds_used,
        "weeks": WEEKS, "hfa": HFA, "sigma": SIGMA,
        "teams": [{"abbr": a, "name": n, "conf": c, "div": d, "rating": round(ratings[i], 2)}
                  for i, (a, n, c, d) in enumerate(TEAMS)],
        "sched": sched,
    }


def verify(rows, out):
    """Refuse to write a board that is the wrong shape. A schedule three games
    short renders exactly like a complete one."""
    # A doubled fixture cannot be seen in the game COUNTS -- the second write lands
    # on the same team-week cell and overwrites the first, so the team still shows
    # 17. build() is the only place that can notice, and it hands them over here.
    problems = list(out.get("_clash", []))
    per_week = {}
    for g in rows:
        per_week[g["week"]] = per_week.get(g["week"], 0) + 1
    missing = [w for w in range(1, WEEKS + 1) if w not in per_week]
    if missing:
        problems.append(f"no games at all in week(s) {missing}")
    # EXACTLY 17, never "about 17". Allowing 16 as slack was the first cut and it
    # swallowed a test season with three games deleted -- the precise shape this
    # function exists to refuse. Every team plays 17 and takes one bye; a team on
    # 16 means a fixture went missing, which is not slack, it is the bug.
    for t, row in enumerate(out["sched"]):
        played = sum(1 for c in row if c)
        if played != 17:
            problems.append(f"{TEAMS[t][0]} has {played} games, expected 17"
                            + (" -- a fixture is missing" if played < 17 else " -- a fixture is doubled"))
    for w in range(WEEKS):
        seen = [t for t in range(len(TEAMS)) if out["sched"][t][w]]
        if len(seen) % 2:
            problems.append(f"week {w+1} has an odd number of teams playing")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--dump", type=int, metavar="WEEK",
                    help="print what the API returns for one week and write nothing")
    ap.add_argument("--ratings", metavar="CSV",
                    help="TEAM,rating per line -- use your own instead of fitting from spreads")
    ap.add_argument("--out", default="season.js")
    ap.add_argument("--force", action="store_true", help="write even if verification fails")
    a = ap.parse_args()

    if a.dump:
        d = fetch(a.year, a.dump)
        print(f"top-level keys: {sorted(d.keys())}")
        print(f"season: {d.get('season')}  week: {d.get('week')}")
        ev = d.get("events", [])
        print(f"events: {len(ev)}")
        for e in ev[:4]:
            comp = (e.get("competitions") or [{}])[0]
            print(f"  {e.get('shortName'):<14} {e.get('date','')[:10]}  "
                  f"odds={[o.get('details') for o in comp.get('odds') or []]}  "
                  f"teams={[(c.get('team',{}).get('abbreviation'), c.get('homeAway')) for c in comp.get('competitors',[])]}")
        if not ev:
            print("\nNo events. That is what an unpublished week looks like, and also what a\n"
                  "changed endpoint looks like. Open the URL in a browser before blaming either:\n"
                  f"  {API.format(year=a.year, week=a.dump)}")
        return

    rows = []
    for w in range(1, WEEKS + 1):
        g = games(fetch(a.year, w), w)
        print(f"week {w:>2}: {len(g):>2} games, {sum(1 for x in g if x['spread']):>2} with a line")
        rows.extend(g)
    if not rows:
        raise SystemExit("No games in any week. Run --dump 1 to see what came back.")

    if a.ratings:
        vals = {}
        with open(a.ratings, newline="", encoding="utf-8") as fh:
            for r in csv.reader(fh):
                if len(r) >= 2 and norm(r[0]) in IDX:
                    try: vals[IDX[norm(r[0])]] = float(r[1])
                    except ValueError: pass
        if len(vals) < len(TEAMS):
            print(f"  ! {a.ratings} covers {len(vals)}/{len(TEAMS)} teams; the rest sit at 0.0",
                  file=sys.stderr)
        ratings, used = [vals.get(i, 0.0) for i in range(len(TEAMS))], 0
    else:
        ratings, used = fit_ratings(rows)
        print(f"\nfitted ratings to {used} posted spreads "
              f"(range {min(ratings):+.1f} to {max(ratings):+.1f})")
        if used < 16:
            print("  ! Fewer than one week of lines. The ratings are barely determined and every\n"
                  "  ! unlined week is close to a coin flip. Re-run once more games are lined, or\n"
                  "  ! pass --ratings with your own numbers.", file=sys.stderr)

    out = build(rows, ratings, a.year, used)
    problems = verify(rows, out)
    if problems:
        print("\nVERIFICATION FAILED:", file=sys.stderr)
        for p in problems[:12]:
            print("  - " + p, file=sys.stderr)
        if not a.force:
            raise SystemExit("\nNothing written. The page keeps using its embedded sample, which is\n"
                             "the honest outcome -- a schedule three games short renders exactly\n"
                             "like a complete one. Pass --force if you know why and want it anyway.")
        print("  (--force: writing anyway)", file=sys.stderr)

    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("/* Generated by pull_season.py -- do not edit by hand. */\n")
        out.pop("_clash", None)          # diagnostics, not board data
        fh.write("window.SEASON = " + json.dumps(out, separators=(",", ":")) + ";\n")
    print(f"\nwrote {a.out}: {len(rows)} games, {used} priced off a real line.")
    print("Open index.html -- the masthead stamp turns green and names the pull.")


if __name__ == "__main__":
    main()
