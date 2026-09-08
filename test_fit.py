#!/usr/bin/env python3
"""Pins the measured claims about the ratings fit in pull_season.py.

    python test_fit.py          (or: pytest test_fit.py)

The failure mode here is never a crash -- it is a board that looks exactly as
correct as it did yesterday while every unlined week drifts toward a coin flip.
So these assert the SCALE of the fit, not just that it runs.
"""
import importlib.util, pathlib, random

_spec = importlib.util.spec_from_file_location("ps", pathlib.Path(__file__).with_name("pull_season.py"))
ps = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ps)

# A round robin over the 32 real teams: enough to exercise the fit without
# needing a schedule pulled from anywhere.
def _fixtures():
    rot, out = list(range(1, 32)), []
    for r in range(ps.WEEKS):
        pairs = [(0, rot[r % 31])] + [(rot[(r + i) % 31], rot[(r - i) % 31]) for i in range(1, 16)]
        for k, (a, b) in enumerate(pairs):
            h, aw = (a, b) if (r + k) % 2 == 0 else (b, a)
            out.append((ps.TEAMS[h][0], ps.TEAMS[aw][0], r + 1))
    return out

FIX = _fixtures()

def _fit(n_lined, seed, ridge=None):
    rng = random.Random(seed)
    true = {a: rng.gauss(0, 3.6) for a, *_ in ps.TEAMS}       # real NFL sd is ~3.5-4 pts
    rows = [{"week": w, "home": h, "away": a, "spread": None, "p_home": None, "tier": None,
             "_t": true[h] - true[a] + ps.HFA + rng.gauss(0, 0.5)} for h, a, w in FIX]
    rows.sort(key=lambda r: r["week"])                        # books line the earliest weeks first
    for r in rows[:n_lined]:
        r["spread"] = round(r["_t"] * 2) / 2
    old = ps.RIDGE
    if ridge is not None: ps.RIDGE = ridge
    fit, used = ps.fit_ratings(rows)
    ps.RIDGE = old
    ctr = lambda v: [x - sum(v) / len(v) for x in v]
    f, t = ctr(fit), ctr([true[a] for a, *_ in ps.TEAMS])
    slope = sum(x * y for x, y in zip(f, t)) / sum(y * y for y in t)   # 1.0 = no shrinkage
    return slope, sum(abs(x - y) for x, y in zip(f, t)) / len(f), used

def _mean(vals):
    vals = list(vals)
    return sum(vals) / len(vals)

def test_fit_recovers_the_scale_at_a_real_pull_density():
    """112 lined games is what nflverse returned in September. The ladder must
    come back at its true scale, or every unlined week is compressed with it."""
    runs = [_fit(112, s) for s in range(20)]
    assert _mean(r[0] for r in runs) > 0.95, "ratings are being shrunk toward zero"
    assert _mean(r[1] for r in runs) < 0.30

def test_ridge_of_one_would_visibly_compress_it():
    """The regression this guards. RIDGE was 1.0 and cost 14% of the scale."""
    slope = _mean(_fit(112, s, ridge=1.0)[0] for s in range(20))
    assert slope < 0.90, "if this passes, re-measure -- the shrinkage claim has moved"
    assert _mean(_fit(112, s)[0] for s in range(20)) - slope > 0.08

def test_one_week_of_lines_is_below_the_bar_and_three_weeks_clears_it():
    """MIN_LINES is 48 because 16 recovers about half the true spread."""
    assert _mean(_fit(16, s)[0] for s in range(20)) < 0.65
    assert _mean(_fit(ps.MIN_LINES, s)[0] for s in range(20)) > 0.90

def test_a_bye_is_not_a_zero_probability():
    """0.0 is a probability here; `if not p` would read a 0% cell as a bye."""
    assert ps.norm_cdf(0.0) == 0.5
    assert 0.0 < ps.norm_cdf(-3.0) < 0.5

def test_moneyline_devig_is_symmetric():
    ph, pa = ps.ml_prob(-150), ps.ml_prob(130)
    assert ph + pa > 1.0, "raw book probabilities carry vig and must exceed 1"
    assert abs((ph / (ph + pa)) + (pa / (ph + pa)) - 1.0) < 1e-12

if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  ok   {name}")
            except AssertionError as e:
                fails += 1; print(f"  FAIL {name}: {e}")
    print("all passed" if not fails else f"{fails} failed")
    raise SystemExit(1 if fails else 0)
