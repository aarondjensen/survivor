"""What a URL is allowed to carry, and where a credential is allowed to go.

Everything here is a rule that fails SILENTLY when it breaks. A first-match id
regex returns a real UUID that is somebody else's contest; an endpoint built
with a hole in it 404s and reads like Splash refusing us; and a header attached
to the wrong host is a credential posted to a third party, which nothing on
screen would ever report.
"""
import urllib.request

import pull_field as F

PICKS = ("https://app.splashsports.com/contest/66612ae5-07b7-4f1a-b904-a22110323029"
         "/picks?entryId=01a08295-d551-4904-9a4d-52f6bda9a9ac"
         "&slateId=692ffa5b-11ae-49e8-949c-eedef7d9e6b0&isEdit=")
CONTEST = "66612ae5-07b7-4f1a-b904-a22110323029"


def test_contest_id_is_the_one_after_contest_not_the_first_uuid():
    # An invite link carries the referrer's uuid too, and it sorts first.
    invite = ("https://app.splashsports.com/join?ref=5b7856e4-318a-4c07-89aa-57f61d005bce"
              "&next=/contest/66612ae5-07b7-4f1a-b904-a22110323029/detail")
    assert F.contest_id(invite) == CONTEST
    assert F.contest_id(PICKS) == CONTEST


def test_splash_ids_reads_all_three_and_does_not_confuse_them():
    ids = F.splash_ids(PICKS)
    assert ids["contest"] == CONTEST
    assert ids["entry"] == "01a08295-d551-4904-9a4d-52f6bda9a9ac"
    assert ids["slate"] == "692ffa5b-11ae-49e8-949c-eedef7d9e6b0"
    assert len({ids["contest"], ids["entry"], ids["slate"]}) == 3


def test_an_endpoint_we_lack_ids_for_is_omitted_never_built_with_a_hole():
    bare = F.splash_endpoints({"contest": CONTEST})
    assert set(bare) == {"contest", "slates"}
    assert all("None" not in u for u in bare.values())

    full = F.splash_endpoints(F.splash_ids(PICKS), user="a-user-id")
    assert set(full) == {"contest", "slates", "entries", "picksheets", "picksheets_mine"}
    assert all("None" not in u for u in full.values())
    # picksheets is ONE endpoint twice: the slate, and the slate plus your entry.
    assert full["picksheets_mine"].startswith(full["picksheets"].split("?")[0])
    assert "entryId=" in full["picksheets_mine"]
    assert "entryId=" not in full["picksheets"]


def _headers_for(url, cookies, token, monkeypatch):
    seen = {}

    class Fake:
        status = 200
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def urlopen(req, timeout=None):
        seen.update(req.headers)      # urllib title-cases them
        return Fake()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    F.fetch(url, cookies, token=token)
    return {k.lower(): v for k, v in seen.items()}


def test_espn_cookies_never_leave_espn(monkeypatch):
    c = {"SWID": "{secret}", "espn_s2": "secret"}
    h = _headers_for("https://gambit-api.fantasy.espn.com/apis/v1/x", c, "", monkeypatch)
    assert "SWID" in h["cookie"]

    h = _headers_for("https://api.splashsports.com/contests-service/api/x", c, "", monkeypatch)
    assert "cookie" not in h
    assert "espn" not in h["referer"]


def test_the_splash_token_never_leaves_splash(monkeypatch):
    h = _headers_for("https://api.splashsports.com/contests-service/api/x", {},
                     "loc-token", monkeypatch)
    assert h["location-token-v2"] == "loc-token"

    h = _headers_for("https://gambit-api.fantasy.espn.com/apis/v1/x", {},
                     "loc-token", monkeypatch)
    assert "location-token-v2" not in h


def test_a_lookalike_host_is_not_under_the_scope():
    # splashsports.com.evil.example must not read as splashsports.com.
    assert not F.under("api.splashsports.com.evil.example", F.SPLASH_SCOPE)
    assert not F.under("notespn.com", F.COOKIE_SCOPE)
    assert F.under("api.splashsports.com", F.SPLASH_SCOPE)
    assert F.under("espn.com", F.COOKIE_SCOPE)


def test_a_bare_url_is_not_overruled_by_the_espn_default():
    # argparse answered a correctly-formed command with `unrecognized arguments`
    # before the positional existed. The half that would be worse: a default on
    # the flag makes it never falsy, so a bare Splash URL walks the ESPN pool
    # while the command on screen names a Splash contest.
    assert F.resolve_url(None, PICKS) == PICKS
    assert F.resolve_url(PICKS, None) == PICKS
    assert F.resolve_url("https://flag.example", PICKS) == "https://flag.example"
    assert F.resolve_url(None, None) == F.ESPN_DEFAULT


def _splash_fixture(d, alias_of_first="ARI", reuse=0):
    import json
    ab = ["ARI", "ATL", "BAL", "BUF"]
    ab[0] = alias_of_first
    teams = {f"id{i}": {"alias": a, "id": f"id{i}", "name": a} for i, a in enumerate(ab)}
    game = {"awayTeam": {"id": "id0"}, "homeTeam": {"id": "id1"}, "id": "g1",
            "isGameSelectable": True, "startDate": "2026-09-14T17:00:00Z", "status": "SCHEDULED"}
    (d / "splash_contest.json").write_text(json.dumps({"contest": {
        "entries": {"filled": 112, "max": 1000, "max_per_user": 10},
        "slateCount": 18, "status": "SCHEDULED",
        "settings": {"pickReuseLimit": reuse, "entryLives": 1, "expectedPicksCount": 1}}}))
    (d / "splash_slates.json").write_text(json.dumps({"data": [
        {"abbreviation": "WK1", "gamesCount": 16, "status": "SCHEDULED"}]}))
    (d / "splash_picksheets.json").write_text(json.dumps({"games": [game], "teams": teams}))
    (d / "splash_picksheets_mine.json").write_text(json.dumps(
        {"games": [game], "teams": teams, "userId": "u1", "livesRemaining": 1}))


def test_inspect_routes_on_the_files_not_the_flag(tmp_path, capsys):
    # --platform says what you are PULLING; --inspect reads what is on disk, so
    # obeying the flag would refuse a directory plainly holding a splash probe.
    _splash_fixture(tmp_path)
    F.splash_inspect(tmp_path)
    out = capsys.readouterr().out
    assert "entries filled       112" in out
    assert "4 teams, 4 join our 32, 0 do not" in out


def test_a_team_code_that_does_not_join_is_named(tmp_path, capsys):
    # A wrong alias is the silent one: it joins to nothing, that team drops out,
    # and every remaining number still looks like a number.
    _splash_fixture(tmp_path, alias_of_first="ZZZ")
    F.splash_inspect(tmp_path)
    out = capsys.readouterr().out
    assert "3 join our 32, 1 do not" in out and "ZZZ" in out


def test_a_contest_that_is_not_this_game_says_so(tmp_path, capsys):
    # pickReuseLimit 0 IS "each team once". Anything else is a different game
    # and the board's whole assignment model stops describing it.
    _splash_fixture(tmp_path, reuse=2)
    F.splash_inspect(tmp_path)
    out = capsys.readouterr().out
    assert "does not describe this contest" in out
