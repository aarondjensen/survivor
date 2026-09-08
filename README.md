# Survivor

An NFL survivor pool optimizer. Pick one team a week, each team only once, and be
the last one standing — so the question at any given week is never "who wins this
Sunday" but "which team can I afford to spend."

**Live:** https://claude.ai/code/artifact/e20117d2-eaca-4216-a0f0-57886fc8b496

Or clone to `C:\dev\survivor` and open `index.html`. One file, no server, no
build, no dependencies.

## What it does

Solves the whole remaining season at once as an exact assignment problem — one team
per week, each at most once, maximising the chance of getting through all of them —
and then prices this week's decision three ways:

- **Path** — your chance of running the table if you take this team now and play the
  rest optimally. Spending a team here is priced by what it costs in November.
- **FV burn** — how much of the season path you surrender by using them up. A team
  the plan never wants again costs nothing; spend them.
- **Lev** — how much of the pool you own if you survive: `E[1 / surviving share]`
  given your team wins, over the field's whole distribution. This is where
  projected ownership bites — a team half the room is holding carries the room
  with it when it wins, so surviving on it gains you very little.

`Score = Path × Lev^λ`, where `λ` scales with pool size — a fifty-person pool leans
on survival, a twenty-thousand-entry contest leans on differentiation. It is a
slider, and it is a judgement rather than a fitted constant.

Click a cell to pin a team to a week, a team name to burn it, a candidate row to
lock it in and advance. Pool settings, burns and pins persist. CSV export.

## Getting real numbers in

```
python pull_season.py --dump                    # what does the source return? writes nothing
python pull_season.py                           # writes season.js next to index.html
python pull_season.py --lookahead 4for4.csv     # ... with real spreads for EVERY week
```

The page picks `season.js` up automatically and the masthead stamp turns green.

The **schedule** is real. A game with a posted **moneyline** is priced off it
de-vigged — an actual traded price. A game with a posted **spread** goes through
a normal curve. Everything else is model output from ratings fitted to the lines
that do exist, and the page prints that split under the board.

In September a book has only hung lines on the next week or two. **`--lookahead`
closes that gap**: paste a lookahead-spread table (4for4 publishes one for every
team in every week) and the whole season gets market numbers instead of modelled
ones. It refuses a table whose spreads land on bye weeks, which is what a
column-offset paste looks like.

If the pull fails verification it writes nothing and you stay on the sample.

## The numbers on it are a sample until you import your own

The shipped slate is **synthetic** — a round-robin over the 32 real teams priced off
sample power ratings — and the masthead says so until real numbers are loaded. It is
NFL-shaped so byes and future value behave correctly, but no game on it is a real
fixture and no probability is anyone's forecast.

Paste your own grid (`TEAM, w1, w2, …`, percent or decimal, `BYE` for byes) and your
pool's own projected ownership in the panel at the foot of the page.

**Ownership is the weakest input in the tool.** With nothing pasted it is a softmax
over win probability — a constant fitted to nothing — so it carries no information
the win probabilities did not already carry, and the leverage half is then correct
arithmetic over invented input. `pull_field.py` is the fix: it reads your ESPN pool
for who is still alive and which teams they have already spent.

**Adding a pool is a pull, not typing.** `python pull_field.py --platform splash <contest url>`
writes `splash.js` and a tab appears, named and sized from the contest — its own file,
because two pullers writing one would mean whichever ran last wins.

**Several pools, one schedule.** Pool tabs above the setup bar: each carries its own
size, entries, leverage weight, burned teams and pasted ownership; the schedule, the
grid and the ratings are shared. A 25-man ESPN pool and a large-field Splash contest
are the same eighteen weeks and genuinely different games.

Splash was walked signed-in and **publishes no ownership and no entrants list** — its
`picksheets` endpoint gives the slate and your own picks, so it supplies pool size and
what you have spent, and the field's ownership stays ESPN's measured counters or the
model.

## Files

| | |
|---|---|
| `index.html` | the whole tool, and the source of truth |
| `pull_season.py` | pulls the real schedule + market spreads, writes `season.js` |
| `pull_field.py` | reads your ESPN pool: who is alive, and ESPN's real pick counters. `--platform splash` walks the Splash endpoints too |
| `build_artifact.py` | emits the shell-less fragment for publishing as an Artifact |
| `make_sample_season.py` | regenerates the synthetic sample slate |
| `test_fit.py` | pins the measured claims about the ratings fit |
| `test_field.py` | pins the id parsing, and that each credential reaches one host |
| `test_leverage.js` | pins the leverage model (`node test_leverage.js`) |
| `test_pools.js` | pins that two pools stay two pools (`node test_pools.js`) |
| `CLAUDE.md` | why it is built this way, and the traps already hit |

Method follows the three pillars in Rick Gehman's *The Lone Survivor*
(RickRunGood, September 2026).
