#!/usr/bin/env python3
"""Pins what --lookahead will and will NOT read out of a pasted spread table.

    python test_lookahead.py        (or: pytest test_lookahead.py)

The table is copied by hand out of a subscription page (4for4's, at
pull_season.LOOKAHEAD_URL), so it arrives in whatever shape the copy lands in.
Every failure here is silent by nature: a misread cell lands on a real fixture,
so neither the bye-week check nor the two-sides check can see it, and it renders
as a market number rather than as an error.
"""
import importlib.util, pathlib, tempfile

_spec = importlib.util.spec_from_file_location("ps", pathlib.Path(__file__).with_name("pull_season.py"))
ps = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ps)


def _read(text):
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
        fh.write(text); path = fh.name
    return ps.read_lookahead(path)


def test_a_team_name_carrying_digits_is_not_a_spread():
    """`at 49ers -3.5` parsed as 49.0 -- a 47-point error priced at 99.99%, on a
    real fixture, in every cell that names San Francisco."""
    assert ps.parse_cell("at 49ers -3.5") == -3.5
    assert ps.parse_cell("@SF49 -3") == -3.0
    assert ps.parse_cell("49ers") is None

def test_a_candidate_must_be_a_number_not_contain_one():
    assert ps.parse_cell("@KC -3.5") == -3.5      # opponent in the cell
    assert ps.parse_cell("@KC-3.5") == -3.5       # ... with no space
    assert ps.parse_cell("-3.5 (-110)") == -3.5   # the price is not the line
    assert ps.parse_cell("-3.5(-110)") == -3.5
    assert ps.parse_cell("-3.5 O/U 47") == -3.5   # signed wins over unsigned

def test_a_bye_is_not_a_zero_and_a_pickem_is():
    for bye in ("BYE", "", "-", "--", "N/A", "OFF", "TBD"):
        assert ps.parse_cell(bye) is None, bye
    for pk in ("PK", "PICK", "PICK'EM", "EVEN"):
        assert ps.parse_cell(pk) == 0.0, pk

def test_an_unreadable_cell_is_dropped_and_named():
    """Dropped costs that fixture its market number. Guessed costs the board a
    number that looks exactly like the ones that are real."""
    why = []
    assert ps.parse_cell("3.5 / 7", why) is None
    assert why and "ambiguous" in why[0]

def test_an_impossible_magnitude_is_refused():
    assert ps.parse_cell("-3.5") == -3.5
    assert ps.parse_cell(f"-{ps.MAX_SPREAD + 1:g}") is None
    assert ps.MAX_SPREAD < 49, "49ers must not be a plausible spread"

def test_both_shapes_parse_to_the_same_thing():
    grid = _read("TEAM,1,2,3\nKC,-3.5,BYE,+1.5\nBUF,+2,-7,BYE\n")
    long = _read("KC,1,-3.5\nKC,3,+1.5\nBUF,1,+2\nBUF,2,-7\n")
    assert grid == long
    assert grid[(ps.IDX["KC"], 1)] == -3.5 and (ps.IDX["KC"], 2) not in grid

def test_the_header_row_is_skipped_not_read_as_a_team():
    got = _read("TEAM,1,2\nKC,-3.5,+1.5\n")
    assert len(got) == 2

def test_a_team_perspective_spread_becomes_a_home_margin():
    """Negative means that team is FAVOURED, so their expected margin negates."""
    rows = [{"week": 1, "home": "KC", "away": "BUF", "spread": None, "p_home": None, "tier": "model"}]
    ps.apply_lookahead(rows, {(ps.IDX["KC"], 1): -3.5})
    assert rows[0]["spread"] == 3.5 and rows[0]["tier"] == "lookahead"
    assert rows[0]["p_home"] > 0.5

def test_a_column_shift_is_refused_rather_than_applied():
    """A one-week offset puts a spread on ~32 byes. ORPHAN_MAX is 8."""
    rows = [{"week": 1, "home": "KC", "away": "BUF", "spread": None, "p_home": None, "tier": "model"}]
    look = {(t, 1): -3.0 for t in range(ps.ORPHAN_MAX + 3)}
    try:
        ps.apply_lookahead(rows, look)
    except SystemExit as e:
        assert "bye" in str(e)
    else:
        raise AssertionError("spreads landing on byes were applied, not refused")


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
