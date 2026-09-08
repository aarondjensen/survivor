"""Build a SAMPLE 18-week NFL-shaped season for the survivor optimizer.

Synthetic on purpose: real team names/divisions, but the matchups come from a
circle-method round robin, not the real 2026 slate. Structure is what the tool
needs to exercise -- 32 teams, 18 weeks, one game per team per week, exactly one
bye each in weeks 5-14. Win probabilities are derived from sample power ratings
through a normal-CDF spread model, never asserted as anyone's real forecast.
"""
import json, math, random

TEAMS = [
    # abbr, name, conf, div, SAMPLE power rating (points vs a league-average team)
    ("BUF","Buffalo Bills","AFC","East",  5.5), ("MIA","Miami Dolphins","AFC","East", -1.0),
    ("NE","New England Patriots","AFC","East", 1.5), ("NYJ","New York Jets","AFC","East", -3.5),
    ("BAL","Baltimore Ravens","AFC","North", 6.5),("CIN","Cincinnati Bengals","AFC","North", 2.5),
    ("CLE","Cleveland Browns","AFC","North",-4.5),("PIT","Pittsburgh Steelers","AFC","North", 0.5),
    ("HOU","Houston Texans","AFC","South", 2.0), ("IND","Indianapolis Colts","AFC","South", 0.0),
    ("JAX","Jacksonville Jaguars","AFC","South", 1.0),("TEN","Tennessee Titans","AFC","South",-5.5),
    ("DEN","Denver Broncos","AFC","West", 3.5),  ("KC","Kansas City Chiefs","AFC","West", 5.0),
    ("LV","Las Vegas Raiders","AFC","West",-2.0),("LAC","Los Angeles Chargers","AFC","West", 3.0),
    ("DAL","Dallas Cowboys","NFC","East", 0.5),  ("NYG","New York Giants","NFC","East",-4.0),
    ("PHI","Philadelphia Eagles","NFC","East", 6.0),("WAS","Washington Commanders","NFC","East", 2.0),
    ("CHI","Chicago Bears","NFC","North", 1.0),  ("DET","Detroit Lions","NFC","North", 5.0),
    ("GB","Green Bay Packers","NFC","North", 4.5),("MIN","Minnesota Vikings","NFC","North", 1.5),
    ("ATL","Atlanta Falcons","NFC","South",-0.5),("CAR","Carolina Panthers","NFC","South",-3.0),
    ("NO","New Orleans Saints","NFC","South",-6.0),("TB","Tampa Bay Buccaneers","NFC","South", 2.0),
    ("ARI","Arizona Cardinals","NFC","West",-2.5),("LAR","Los Angeles Rams","NFC","West", 4.0),
    ("SEA","Seattle Seahawks","NFC","West", 2.5),("SF","San Francisco 49ers","NFC","West", 4.0),
]
N, WEEKS, HFA, SIGMA = 32, 18, 2.0, 13.2

def winprob(spread):
    """Spread (positive = favoured, in points) -> win probability. Normal CDF,
    sigma 13.2 pts, the usual NFL margin-of-victory spread."""
    return 0.5 * (1 + math.erf(spread / (SIGMA * math.sqrt(2))))

# ---- circle-method round robin: 18 rounds, each a perfect matching on 32 teams
rot = list(range(1, N))
rounds = []
for r in range(WEEKS):
    pairs = [(0, rot[r % 31])]
    for i in range(1, N // 2):
        a, b = rot[(r + i) % 31], rot[(r - i) % 31]
        pairs.append((a, b))
    # alternate which side is home so nobody stacks all-home or all-away
    rounds.append([(a, b) if (r + k) % 2 == 0 else (b, a) for k, (a, b) in enumerate(pairs)])

# ---- carve out byes: pull 16 games from weeks 5-14 so every team sits exactly once
rng = random.Random(20260908)
BYE_WEEKS = range(4, 14)          # weeks 5-14, 0-indexed
MAX_PER_WEEK = 3                  # don't gut any single week

def carve_byes():
    """Pick 16 games out of weeks 5-14 whose 32 teams are all distinct, so every
    team sits exactly once. Greedy on the most-constrained team, with restarts --
    a plain sweep strands the last few teams (measured: 30 of 32)."""
    edges = [(w, g) for w in BYE_WEEKS for g in rounds[w]]
    for _ in range(5000):
        rng.shuffle(edges)
        byed, removed, per_week = set(), {w: [] for w in range(WEEKS)}, {w: 0 for w in BYE_WEEKS}
        for team in sorted(range(N), key=lambda _: rng.random()):
            if team in byed:
                continue
            for w, g in edges:
                if per_week[w] >= MAX_PER_WEEK or g[0] in byed or g[1] in byed or team not in g:
                    continue
                removed[w].append(g); byed.update(g); per_week[w] += 1
                break
        if len(byed) == N:
            return removed
    raise RuntimeError("could not carve a bye week for every team")

removed = carve_byes()

# ---- per-team, per-week schedule + win probability
sched = [[None] * WEEKS for _ in range(N)]
for w in range(WEEKS):
    for home, away in rounds[w]:
        if (home, away) in removed[w]:
            continue
        spread = TEAMS[home][4] - TEAMS[away][4] + HFA
        p = winprob(spread)
        sched[home][w] = {"o": away, "h": 1, "p": round(p, 4)}
        sched[away][w] = {"o": home, "h": 0, "p": round(1 - p, 4)}

for t in range(N):
    played = sum(1 for w in range(WEEKS) if sched[t][w])
    assert played == 17, f"{TEAMS[t][0]} plays {played} games, expected 17"

out = {
    "label": "Sample season",
    "note": "Synthetic schedule on a circle-method round robin -- NOT the real 2026 NFL slate. "
            "Win probabilities are derived from the sample power ratings below.",
    "weeks": WEEKS, "hfa": HFA, "sigma": SIGMA,
    "teams": [{"abbr": a, "name": n, "conf": c, "div": d, "rating": r} for a, n, c, d, r in TEAMS],
    "sched": sched,
}
print(json.dumps(out, separators=(",", ":")))
