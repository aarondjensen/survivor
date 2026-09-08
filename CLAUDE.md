# CLAUDE.md — survivor

An NFL survivor pool optimizer. One self-contained HTML file, no server, no build
step, no dependencies. Open `index.html` and it works.

Lives at `C:\dev\survivor`, beside `C:\dev\draftkit` — Windows / PowerShell.
Separate repo on purpose: it shares no data, no model and no screens with draftkit,
and nothing imports across. Python is only ever needed for the two helper scripts;
the page itself needs nothing installed.

Built to the three pillars in Rick Gehman's *The Lone Survivor* (RickRunGood,
2026-09-03). Published as an Artifact:
https://claude.ai/code/artifact/e20117d2-eaca-4216-a0f0-57886fc8b496

This file exists so you start informed instead of rediscovering the same decisions.
Read it before touching anything.

---

## The one idea the whole tool is built on

**A survivor pool is an assignment problem wearing a weekly disguise.** One team per
week, each team at most once, maximise the chance of getting through all of them.
That is exactly a rectangular assignment on `-log p`, so it is solved **EXACTLY**
(Hungarian / Jonker-Volgenant, `O(n²m)`, 18×32 — microseconds) and never
approximated greedily.

Greedy weekly picking is the failure this exists to prevent, and it is not a small
one: it takes the best team available now and cannot see that it has just spent the
only team that carries week 11. That is the entire content of "future value" as a
concept, and an exact solver gets it for free rather than by heuristic.

Every number on the page is one question asked of that one solver:

| | asks | how |
|---|---|---|
| **the plan** (pillar 1) | best path over the weeks you have left | solve once |
| **future value** (pillar 2) | what does burning this team cost? | solve again without them, diff |
| **this week** (pillar 3) | what is each candidate worth? | solve again with them forced into this week's slot |

There is no second value model anywhere, deliberately. A tool that answers "who
should I take" one way and "what is he worth later" another way is a tool that
disagrees with itself, and you cannot tell which half is wrong.

## The three numbers, and what each one is FOR

    Path  = P(this week) × exp(OPT(remaining weeks, remaining teams))
    Lev   = p_you / Σ_j ownership_j × p_j
    Score = Path × Lev^λ

**`Path` is why spending a team here is priced by what it costs there.** It is the
probability of running the entire table if you take this team now and play
optimally afterwards — not this week's win probability with a note beside it.

**`Lev` MUST BE `E[1/x]` AND NEVER `1/E[x]`, AND IT TOOK TWO WRONG CUTS TO GET
THERE.** It is the expected value of `1 / (surviving share of the pool)` given your
team wins — how much of what is left you own — taken over the field's WHOLE
distribution.

- **Cut one scored `p_you / F`, where `F` is the field's survival rate.** `F` is
  **the same number for every candidate**, so dividing by it cannot reorder
  anything: ownership was rendered in its own column and had **zero** effect on the
  ranking. Measured — piling 60% of the pool onto the top pick left the board
  identical, and `lev / win` came back as the same constant, `1.445579`, on every
  row. Worse, since `Lev ∝ p`, `Lev^λ ∝ p^λ`, so the pool-size slider **ran
  backwards**: a bigger pool chased win probability harder.
- **Cut two conditioned the denominator on your team winning**, `p_t / (F + pop_t(1
  − p_t))`. That ranks correctly and is still wrong by a factor of **25**. With 99%
  of the room on a 75% chalk against 1% on a 73% dog it says 0.97 for the dog; the
  truth is **25.75**. Averaging the survivor count before inverting erases the only
  branch that pays — the chalk loses, and a sliver of the pool is left holding your
  ticket. Jensen's inequality, and the gap IS the prize.

So the whole distribution is computed. The surviving share is a sum of independent
per-team indicators, which is a convolution — exact, and **deterministic**, where
sampling would have made the board irreproducible run to run.

**IT REPRODUCES THE ARTICLE'S OWN WORKED EXAMPLE WITHOUT BEING TOLD IT.** On
Gehman's Week 1 numbers (LAC 80%/35%, JAX 73%/23%, DET 74%/16%, LV 65%/7%) the
exact calculation picks **Detroit** — his leverage case, the one where you pay six
points of win probability to get off the chalk. Both earlier cuts picked LAC.

**AND THE CHALK IS NOT AUTOMATICALLY WRONG.** On those same numbers LAC is second,
not last: an 80-against-74 edge is large and 35% ownership does not overcome it in
one week. Gehman agrees — *"if our only goal was surviving this week, Los Angeles
would be the easy answer"* — and his stated reason for fading them is FUTURE VALUE,
not leverage. Measured as ownership climbs on a fixed 74% team: rank 1 at 5% owned,
4 at 20%, 6 at 35%, 17 at 60%, last at 90%. `test_leverage.js` pins all of it,
including a test that fails if ownership stops reordering the board.

**WHAT THIS STILL DOES NOT MODEL:** survivor is multi-week and winner-take-all, so
equity is CONVEX in pool share and a differentiated pick buys variance worth real
win probability. This prices one week. λ above 1.00 is the knob for leaning further
than one-week EV justifies, and it is labelled as exactly that.

**`λ = 1.00` IS NOT A WEIGHTING, IT IS THE OBJECTIVE.** There `Path × Lev`
multiplies out to rest-of-season survival times this week's expected equity, which
is the thing you are maximising rather than a weighting of it. It used to default
to `log₁₀(entries)/4` — a bridge invented for a leverage term that could not see
ownership at all. The term can now, and **pool size enters `Lev` directly**,
through the one-entry floor `1/N` that stops a team nobody is projected on from
dividing by zero. Above 1.00 leans harder into differentiation than one week of EV
justifies, which is defensible for the convexity reason above and is labelled as a
lean. **Nothing here is fitted to outcomes**: there is no survivor result log to
fit it on.

## REAL DATA: `pull_season.py` WRITES `season.js`, AND THE PAGE PREFERS IT

    python pull_season.py --dump 3      # what does the API actually return? writes nothing
    python pull_season.py               # pull the season, fit ratings, write season.js
    python pull_season.py --ratings my_ratings.csv

`index.html` carries `<script src="season.js">` before its own script. Present, the
board runs on it and the masthead stamp turns green and names the pull; absent (the
published Artifact, a fresh clone) it 404s **silently** and the embedded sample is
used. They are never merged — a half-real slate is the worst of both.

**THREE TIERS OF TRUTH, AND THE PAGE PRINTS WHICH ONE EACH GAME GOT.**

| tier | what it is |
|---|---|
| **market** | a posted **moneyline**, de-vigged — an actual traded price, as real as a win probability gets |
| **market** | a posted **spread**, through a normal curve (σ 13.2) |
| **model** | everything else — priced off ratings **fitted by least squares** to the lines that do exist (ridge λ=1, which also pins the otherwise-free additive constant) |

The schedule itself is real in all three cases. `market_games` and `model_games`
ride in `season.js` and the page prints the split under the board.

**SOURCE ORDER: nflverse FIRST, ESPN AS FALLBACK.** nflverse is one CSV on
`raw.githubusercontent.com` carrying the whole season with spreads *and*
moneylines; ESPN needs 18 requests and **answered HTTP 403 to a bare `urllib`
request** — no `Accept` headers is a bot fingerprint, which is why
`BROWSER_HEADERS` exists and why `get()` prints the response body on a refusal.
A 403 is a REFUSAL, not a missing page, and the first cut of this file printed
"a 404 usually means that week is not published yet" *on a 403* — a confident
wrong diagnosis in the one place you read when something breaks.

## OWNERSHIP IS THE WEAKEST INPUT HERE, AND IT IS INVENTED

`ownership_model` is `exp(OWN_K * (p - 0.5))`, normalised, with `OWN_K = 13` chosen
so the top favourite lands near 30% — a figure taken from the source article, fitted
to **nothing**. So with nothing pasted, projected ownership is a **monotone function
of win probability** and carries no information the win probabilities did not already
carry. The leverage half is correct arithmetic over invented input, which is worse
than it sounds: it is the half the whole third pillar rests on.

**AND THE FIELD'S BURNED TEAMS ARE MODELLED NOWHERE AT ALL.** The board projects the
field's week 11 ownership as though all 32 teams were available to every rival. They
are not — a rival who spent Baltimore in week 2 cannot take Baltimore again — and
this is the largest single error in the leverage half. The alive count is the same
shape of error one size down: pools shrink every week and `S.pool` is a static input,
so the leverage denominator is wrong from week 2 onward.

**AND ESPN PUBLISHES REAL OWNERSHIP, WHICH IS WHAT `pull_field.py` NOW READS.**
Every proposition's `possibleOutcomes[].choiceCounters[]` carries `count` and
`percentage` — measured picks over ESPN's whole survivor game, roughly **55,000
entries**, available BEFORE lock. That is the softmax's replacement, not its
calibration.

**IT IS ESPN-WIDE AND THE PAGE SAYS SO IN THOSE WORDS.** Those counters are taken
over every entry in the game; this pool is **25 people**. Real measured picks are
a far better prior than a curve fitted to nothing, and they are still a proxy for
what twenty-five people you know will do — so the footer states the scope and the
paste box overrides it. Precedence is **pasted > ESPN > model**, and `ownSource()`
reports which is live, because a modelled week and a measured one render
identically.

**KEY ON `scoringPeriodId`, NEVER THE ARRAY INDEX.** Measured: `propositions[0]`
came back as a **December** week carrying **28** outcomes (four teams on bye).
Index-as-week would have filed December's ownership under week 1 and every number
downstream would still have looked like a number.

**A WEEK OF ALL ZEROS IS NOT OWNERSHIP.** Future weeks come back uncounted, and a
zero table handed to the leverage model describes a field that survives with
probability zero. `ownership()` requires the playing teams to carry >0.5 of the
share between them before it trusts the table, and falls back to the model
otherwise. Same rule one layer up: `check_ownership` REFUSES to write a table
whose shares do not sum to ~1 rather than normalising it, because normalising is
what makes a wrong reading look like a right one.

**THE ALIVE COUNT IS SERVED DIRECTLY** as `entryStats.overallEntryCountStats`
{SURVIVING, ELIMINATED, TOTAL}, plus a per-week breakdown. The board adopts
`surviving` as the pool size — but never over a number you set yourself.

**RIVALS' PICKS ARE NOT IN THE GROUP VIEW.** `entries[]` carries
{challengeId, id, member, name, score} and no `picks`; picks live on the entry in
the `members` view, as `outcomesPicked[].outcomeId` resolved through
`possibleOutcomes[].id`. `clientFlags.showGroupPicks` is `true` for this pool, so
they are readable — but the view that serves them is not called until a week has
locked, so it needs one more `--discover` pass then. Until it lands, the field's
BURNED teams are still unmodelled.

**`pull_field.py` REFUSES TO GUESS.** ESPN's games platform
(Gambit — `fantasy.espn.com/games/nfl-survivor-2026/...`) is NOT the `ffl` fantasy
API draftkit talks to, and its endpoints are undocumented. So `--discover` drives a
real browser through the user's own session and RECORDS the calls the page makes:
the endpoint is observed, not assumed. Until one has been, the script writes
**nothing** and says so — a parser written against a guessed shape produces a file
that looks right and is not, which is this codebase's recurring failure mode.

**PICKS ARE HIDDEN UNTIL LOCK, AND THAT IS THE GAME.** Nothing can show you this
week's picks before the deadline. What locked weeks give is the alive count, every
surviving entry's spent teams, and what this room ACTUALLY picked — which is what
you calibrate `OWN_K` against, or replace it with outright, since a projection
conditioned on each rival's remaining teams beats any curve fitted to one number.

**RIDGE SHRINKS, AND AT 1.0 IT WAS EATING 14% OF THE LADDER.** The fit only ever
determines DIFFERENCES between ratings, so something has to pin the additive
constant; ridge does that and regularises thin data at the same time. It also
compresses, and the first cut compressed hard. Measured against known ratings
over 40 seeded seasons at the density a real September pull has — **112 lined
games**, which is what nflverse returned on 2026-09-08:

| RIDGE | mean err | max err | slope | fitted range |
|---|---|---|---|---|
| 0.05 | 0.17 | 0.49 | 0.991 | 15.5 |
| **0.1** | **0.18** | **0.51** | **0.982** | **15.4** |
| 0.5 | 0.32 | 0.87 | 0.921 | 14.5 |
| **1.0 (was)** | **0.49** | **1.39** | **0.859** | **13.6** |
| 2.0 | 0.76 | 2.23 | 0.761 | 12.1 |

*(slope of fitted against true; 1.00 is no shrinkage. True range 15.6 pts.)*

**That compression lands on the 160 games the tool is actually reasoning about**
— every unlined week is priced off these ratings — pulling all of them toward a
coin flip and flattening the future-value comparisons the optimizer runs on.
Lower ridge won at **every** density tested, including the thin end where
regularisation was supposed to be earning its keep: at 16 lined games it buys
~0.1 pts of error and costs a third of the scale.

**AND THE THIN-DATA WARNING WAS SILENT AT EXACTLY THE DENSITY THAT FAILS.** It
fired below **16** lined games — but 16 IS one week, and one week cannot fit 32
ratings: every team has appeared, and a team played once cannot be told apart
from its single opponent. Slope by lines available: **16 → 0.504**, 32 → 0.868,
48 → 0.935, 64 → 0.960, flat after. `MIN_LINES` is **48** — three weeks — and
the message says what a bad fit does rather than that one is possible.
`test_fit.py` pins all of it, including a test that FAILS if ridge 1.0 ever
stops being visibly worse, so the claim cannot quietly go stale.

**`--lookahead` IS THE ANSWER TO "REAL NUMBERS FOR WEEK 15".** A book has not
hung a line on week 15 in September, but 4for4 and others publish **lookahead
spreads** for every team in every week. Paste that table and every fixture gets a
market number instead of a model one. Two shapes are accepted (a grid, or
`TEAM,WEEK,SPREAD`), and the **sign convention is the betting one** — negative
means that team is favoured — which is stated rather than detected, and then
checked two ways:

- **Both sides of one game must be equal and opposite.** They disagree only if
  the table is misaligned or the spreads are written from the other perspective.
- **A correct table puts ZERO spreads on a bye week.** More than `ORPHAN_MAX` (8,
  slack for a ragged paste) and it refuses. This one had to be tightened after
  testing: the first cut refused at 20% of parsed cells, which on a 544-cell
  table is 108, and a one-week column shift produces about 32 — so it waved
  through exactly the misread it was written to catch.

**NOBODY HAS REAL WIN PROBABILITIES FOR WEEK 15 IN SEPTEMBER, BECAUSE NONE EXIST.**
Every product you can buy — PoolGenius included — is running this same kind of
model over this same kind of ratings. So the tool does not pretend otherwise:
`note` and `odds_games` ride inside `season.js` and the page prints them under the
board, naming how many games were priced off a real line and stating that the rest
are model output rather than a quoted price.

**THE ENDPOINT IS UNVERIFIED AND THE MODULE SAYS SO IN ITS OWN DOCSTRING.** It was
written in a sandbox with no outbound network — every domain, including the API,
`pro-football-reference`, `nfl.com` and Wikipedia, answered `EGRESS_BLOCKED` — so
the response shape is *expected*, not observed. Hence `--dump` leading the
interface, and hence every failure naming what it SAW rather than asserting a
cause. Same discipline as draftkit's `yahoo_rankings.py`, for the same reason: a
confident wrong diagnosis sends you at a session that is fine.

**IT REFUSES TO WRITE A BOARD OF THE WRONG SHAPE.** `verify()` demands **exactly**
17 games per team. Two bugs found by testing it against a deliberately broken
season, both worth keeping in mind:

- **Allowing 16 as slack swallowed a season three fixtures short** — the precise
  case the function exists to refuse. There is no slack: every team plays 17 and
  takes one bye, so 16 is a missing fixture, not tolerance.
- **A DOUBLED FIXTURE CANNOT BE SEEN IN THE COUNTS.** The second write lands on the
  same `sched[team][week]` cell and overwrites the first, so the team still totals
  17 while a real fixture has silently vanished. Only `build()` can notice, at the
  moment it overwrites, so it collects clashes and hands them to `verify()`. The
  `_clash` key is diagnostics and is stripped before `season.js` is written.

On a failure it writes **nothing** and says so: the page stays on its labelled
sample, which is the honest outcome, because a schedule three games short renders
exactly like a complete one.

## THE SHIPPED SLATE IS SAMPLE DATA AND THE PAGE NEVER STOPS SAYING SO

There is no real schedule in this repo and no published win-probability source, so
`make_sample_season.py` builds a **synthetic** one: a circle-method round robin over
the 32 real teams, priced off sample power ratings through a normal-CDF spread model
(σ 13.2 points, home field +2).

It is NFL-**shaped** — 17 games each, exactly one bye each between weeks 5 and 14,
one game per team per week, all pinned by asserts in the generator — so the
optimizer, the byes and the future-value arithmetic all exercise correctly against
it. **No game on it is a real fixture and no probability is anyone's published
forecast.** The masthead carries a standing stamp that says so, and it flips to
"your imported grid" only once real numbers are loaded. A sample that renders
identically to real data is the failure mode here; the stamp is the fix.

So **import is first-class, not an afterthought.** Paste a `TEAM, w1, w2, …` grid
(percent or decimal, `BYE` for a bye) and the sample slate is out of play entirely.
Ownership gets its own box, because it is the most pool-specific input on the page
and the modelled default is only a softmax over the week's favourites.

    python make_sample_season.py > season.json     # then swap the `const SAMPLE = …` literal

## index.html IS THE SOURCE OF TRUTH; THE ARTIFACT IS BUILT FROM IT

`index.html` is a complete document — it opens by double-click and serves from
anywhere. The Artifact host supplies its own `<!doctype><head></head><body>` shell
and **refuses a page that brings one**, so publishing means handing it the same page
with the shell taken off. `build_artifact.py` does that mechanically:

    python build_artifact.py > artifact.html

Doing it by hand is how the two copies drift, which is why there is a script for
sixteen lines of work and why it refuses to emit anything still carrying a shell tag.

## Traps already hit — do not rediscover these

**`0.0` IS A PROBABILITY, NOT A FALSY BLANK.** Byes are `null` and every check is
`== null`. `if (!p)` reads a genuine 0% cell as a bye and hands the optimizer an
empty slot — a week it thinks is free, in the one direction that flatters the plan.

**THE SHELL GUARD IN `build_artifact.py` CLOSES ON A TAG BOUNDARY.** `<head` is a
prefix of `<header`, which is the first tag the page body opens with, so a naive
substring guard refuses every correct build. Caught on the first run.

**OWNERSHIP MUST BE NORMALISED OVER THE WEEK'S WHOLE FIELD, NEVER OVER THE
FAVOURITES.** `F` has to be a real survival rate. Normalise over a subset and the
denominator is smaller than reality, which inflates every leverage multiple on the
board — silently, and in the direction that makes contrarian picks look better than
they are. Pasted ownership is re-normalised on load for the same reason: numbers
typed by hand rarely sum to 100 and are not worth trusting to.

**A TEAM THE OPTIMAL PATH NEVER WANTS AGAIN HAS A FUTURE VALUE OF EXACTLY ZERO, AND
THAT IS A RESULT.** It is the whole argument for burning them now, not a rounding
artefact to be floored away.

**`n > m` IS REACHABLE — MORE WEEKS LEFT THAN TEAMS LEFT.** Hungarian requires
`n ≤ m`. Late in a season with many teams burned the surplus weeks are reported as
unfillable and the board says you are out of teams, rather than crashing or quietly
solving a smaller problem and printing the answer as though it covered the season.

**THE OPTIMIZER PICKING THE SAME OPPONENT WEEK AFTER WEEK IS THE MODEL WORKING.** On
the sample slate the plan keeps selecting whoever plays New Orleans, because NO is
the weakest team on it and their opponent is usually the week's biggest favourite.
It reads like a bug and is the correct answer.

**RE-PRICING THE SAMPLE SLATE IS MEMOIZED ON THE RATINGS.** `grid()` caches on a key
built from the rating overrides, because it is called once per team per week per
Hungarian run and there are ~66 runs per render.

## How I work

I paste terminal output verbatim and expect diagnosis from it. Functional
explanations over prose. **Accuracy over assumption** — do not invent player names,
schedules or probabilities to fill a gap; fail loud, or label the synthetic thing as
synthetic on the screen where it is read. Explanatory UI text is unwanted.

Merge finished work to `main` without being asked: commit on the working branch,
push it, merge `--no-ff`, push `main`, say it is on `main`. Hold off only when the
change is knowingly half-finished, when I asked to review first, or when it touches
credentials or deletes data I have not signed off on.
