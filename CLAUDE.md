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

**`Lev`'s DENOMINATOR IS THE WHOLE POINT.** It is the FIELD's survival rate this
week — every rival's ownership weighted by their team's win probability — so above
1.00 you gain pool share and below it you **lose share even when you survive**.
That is the trade the pillar is about: the 80% team a third of the pool holds is a
losing pick against the 74% team nobody has, and no amount of win probability on
its own can say so. Ownership and win probability are two different questions and
this is the only place they meet.

**`λ` IS A JUDGEMENT, NOT A MEASUREMENT, AND THE PAGE SAYS SO IN THOSE WORDS.** It
defaults to `log₁₀(entries)/4` — 0.42 at fifty entries, 1.08 at twenty thousand —
because survival dominates a small pool and differentiation dominates a huge one.
It is a slider, and it is labelled. **Nothing here is fitted to outcomes**: there
is no survivor result log to fit it on, and a constant chosen because it looked
right is worse than a knob that admits what it is.

## REAL DATA: `pull_season.py` WRITES `season.js`, AND THE PAGE PREFERS IT

    python pull_season.py --dump 3      # what does the API actually return? writes nothing
    python pull_season.py               # pull the season, fit ratings, write season.js
    python pull_season.py --ratings my_ratings.csv

`index.html` carries `<script src="season.js">` before its own script. Present, the
board runs on it and the masthead stamp turns green and names the pull; absent (the
published Artifact, a fresh clone) it 404s **silently** and the embedded sample is
used. They are never merged — a half-real slate is the worst of both.

**WHAT IS REAL AND WHAT IS MODELLED, BECAUSE THE DIFFERENCE IS THE WHOLE QUESTION.**

| | |
|---|---|
| **real** | the schedule — every fixture, home and away, byes included |
| **real** | the point spread on any game a book has actually posted a line for |
| **modelled** | every win probability, without exception |

A spread becomes a probability through a normal curve (σ 13.2); a week with no
posted line is priced off team ratings **fitted by least squares to the spreads
that do exist** (ridge λ=1, which also pins the otherwise-free additive constant).

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
