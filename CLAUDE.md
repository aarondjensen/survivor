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

**THE FIELD SIZE IS PER WEEK, NOT ONE NUMBER, AND THAT CHANGES WHAT LATER WEEKS
MEAN.** `count / percentage` recovers whatever field a week is counted against,
and on the real 2026 pull it decays monotonically: **648,391** in week 1, 70,561
in week 2, settling near **43,242** by week 18. No single game-wide entry count
can do that. The `percentage` reading is sound — every week sums to **1.000**
across the right number of teams, and within a week `count/percentage` agrees to
a fraction of a percent across teams. What varies is the DENOMINATOR: entries
that have made a pick *for that week*.

So **week 1's ownership is measured over the whole field, and week 18's over the
~43k who pre-picked that far ahead** — a self-selected minority of early
planners, not the room that will actually be alive in December. Still real
measured behaviour and still far better than a curve fitted to nothing, but the
later the week the thinner and more self-selected the sample, and the panel
prints the per-week figure so that is visible rather than assumed.

`counter_spread()` is the guard that separates those two readings: it checks
count/percentage agreement WITHIN each week and warns past 2%. Agreement inside a
week is what says `percentage` really is `count / that week's total`; if the two
fields ever start answering different questions, the shares stop meaning what the
leverage model consumes them as.

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

## YOUR OWN PICKS ARE READABLE; THE FIELD'S ARE NOT, AND THAT SPLIT IS THE POINT

`--inspect` on the real probe, 2026-09-08, settled where a pick lives. It is on
the **members** response and it is two uuid indirections deep:

    entry .picks[] .propositionId               -> WEEK, via propositions[].id
                   .outcomesPicked[] .outcomeId -> TEAM, via that proposition's
                                                   possibleOutcomes[].id

**NEITHER INDIRECTION IS GUESSABLE.** A pick names a uuid on both axes; nothing
in it says "week 3" or "KC". The propositions response is the decoder ring, and
`decode_picks` DROPS and NAMES a pick whose ids are not in it rather than filing
it under a guess — a burned team we invent is one the board stops offering you
for the whole season. The week comes from `scoringPeriodId`, never the array
index, which is the same trap the ownership parser was written against and it is
live in this data: `propositions[0]`'s outcomes lock on **2026-12-04**.

**THE GROUP VIEW CARRIES SCORES AND NO PICKS.** Its entries are
`{challengeId, id, member, name, score}` — 25 of them, `SURVIVING 25`,
`scoreByPeriod` per week. So you can see who is alive and never what they took.
The field's burned teams therefore remain the largest modelled-away term in the
leverage half, exactly as the ownership section says. `showGroupPicks` is true on
this pool, so the reveal is expected once a week locks; whether it arrives on
this endpoint or another is a MEASUREMENT, and `--inspect A --against B` is how
it gets made rather than remembered.

**A SELECTION IS NOT A DECISION UNTIL IT LOCKS, AND CONFLATING THE TWO MUTED THE
ONE QUESTION THE BOARD EXISTS TO ANSWER.** ESPN saves your pick the moment you
make it and lets you change it until kickoff, so `mine` holds a live selection as
readily as a settled one — and the first cut burned both. Burning a LIVE one takes
that team out of this week's candidate list, so the board could not recommend it
even if it were the best pick on the slate; and what it renders is the team you
have selected, marked gone, beside a call for somebody else. Asked directly —
*"that's what the optimizer is telling me to do right?"* — the honest answer was
no, it is what the optimizer was told, and nothing on the screen said so.

SETTLED is `week < FIELD.week`, or `== FIELD.week` and ESPN reports the period
locked. Both facts come off the same pull, so this is read from the platform and
not judged here. Anything else is PROVISIONAL: shown as what you have in, never
burned, and the week does not advance past it, because that week is still a
decision. The note names the two separately, since only one of them moved the
board.

**`settled` IS A FUNCTION DECLARATION AND NOT A `const`.** The field note renders
above the line that defines it and calls it, so a `const` sits in its temporal
dead zone there — which throws, and the boot catch would leave a board that looks
merely empty rather than broken. Caught by the browser test, not by reading it.

**THE BURN AND THE WEEK ADVANCE ARE ONE FACT AND MUST LAND TOGETHER.** Burning a
team takes it off the board for EVERY week including the one on screen. So a
board left sitting on a week you have already filed shows a call for THAT week
with your own submitted team missing from the candidates, and recommends
somebody else for a pick that is already in — a confident wrong answer on the
one screen you look at. The first cut gated the advance on having no saved
board, which is precisely the case that cannot produce the bug (a first load
starts at week 0 with nothing filed) while leaving the case that does. It is
`max(current, last filed)` now: forward whenever a filed week is at or past the
one on screen, never backwards, so reviewing week 6 survives the next pull.

**IT IS ADDED TO THE BOARD, NEVER SUBTRACTED FROM IT.** `FIELD.mine` marks your
submitted picks burned on the ESPN tab and does nothing else. The platform knows
what you SUBMITTED; the board is also where you plan a pick you have not
submitted yet, so a pull that un-burned a team you burned here on purpose would
quietly undo a decision. It does not merge into the other pool tabs either — it
is this pool's record and nobody else's. The week advances to the first week you
have not filed, and never backwards.

**WEEK 1 IS THE ONE WEEK THIS COSTS NOTHING.** Nobody has burned anything yet, so
the missing rivals'-picks term is exactly zero and the board is at its most
complete right now. It grows from week 2.

## SPLASH: WHAT IT SERVES, AND THE ONE THING IT DOES NOT

Two walks, and only the second one settles anything. `--discover` on the public
page reported split.io identifying the visitor as `anonymous-user-...`, so it saw
the logged-out view; no entries, no picks. **That is the shape of a page nobody is
signed in to, and reading it as "Splash does not serve picks" would have been the
confident wrong answer.**

The captcha then refused the driven window — the same Turnstile-class refusal
draftkit's `platforms/browser.py` was written for, and the same three fixes
(`--enable-automation` off, real Chrome channel, no UA spoof, persistent profile)
were ported here. It still refused, so the route that has nothing to challenge is
the one that worked: **a HAR exported by hand from the signed-in page**. Five calls:

    GET /contests/<contest>                                          170,948 B
    GET /contests/<contest>/slates                                     7,475 B
    GET /contests/<contest>/users/<user>/entries?limit=150&offset=0      375 B
    GET /slates/<slate>/picksheets?contestId=<contest>&sort=startTime          10,636 B
    GET /slates/<slate>/picksheets?contestId=<contest>&entryId=<entry>&…       12,365 B

**`picksheets` IS THE PICK SURFACE, AND IT IS ONE ENDPOINT TWICE** — without
`entryId` it is the slate, with it your own picks come back alongside. That is what
a parser keys on.

**THERE IS NO OWNERSHIP ENDPOINT AND NO ENTRANTS LIST, AND THAT IS A FINDING RATHER
THAN A GAP IN THE WALK.** The page was signed in and rendered fully, and nothing
resembling ESPN's `choiceCounters` was requested. So Splash can give **pool size and
your own picks**; the field's ownership stays modelled, or ESPN's counters stand in
as the measured proxy. Inventing a Splash ownership number would render identically
to ESPN's measured one, which is the whole failure mode this file exists to name.

**AN ENDPOINT WE LACK IDS FOR IS OMITTED, NEVER BUILT WITH A HOLE IN IT.** The user
id is in the entries path only and the picks URL does not carry it, so without
`--splash-user` that call is skipped and says so. A URL assembled around a `None`
404s, and a 404 from our own bad URL reads exactly like Splash refusing us.

**`location-token-v2` IS A CREDENTIAL AND IT IS SCOPED LIKE ONE.** Every
contests-service call carries it. It lives in `SPLASH_LOCATION_TOKEN` (env or the
gitignored `.env`), never in the repo, and `fetch()` sends it only under
`SPLASH_SCOPE` — the identical rule the ESPN cookies get under `COOKIE_SCOPE`,
because the first cut of `fetch()` attached ESPN session cookies to *whatever URL it
was handed* and pointing `--dump` at Splash would have posted them to a third party.
`--dump` now asks for whichever secret the TARGET needs, so demanding ESPN cookies
for a Splash URL can no longer refuse a session that is fine. `test_field.py` pins
both directions, and pins that `splashsports.com.evil.example` is not under the scope.

**A HAR HOLDS LIVE CREDENTIALS.** That capture carried the session's location token,
an Intercom `user_hash`, a Braze key, a Segment write key, an email address and a
wallet balance. It is read locally, only SHAPES are printed, `*.har` is gitignored —
and a HAR is never pasted anywhere, including into a chat.

**AND THE CONTEST ENDPOINTS NEED NO CREDENTIAL AT ALL.** Measured: all four
returned **HTTP 200 with no cookie and no location token**. The header is on the
browser's calls because the browser has one, not because the resource requires it.
So `SPLASH_LOCATION_TOKEN` stays supported and stays optional, and the probe says
`ABSENT` rather than refusing — a refusal in advance would have hidden the finding.

**WHAT THE `entryId` BUYS IS THE PART THAT IS NOT PUBLIC.** Anonymous,
`picksheets_mine` came back **10,765 bytes against the signed-in capture's
12,365**, and its extra keys over the slate view are only `hasAutoPicks`,
`hasBuyBacks`, `livesRemaining`, `userId`, `username` — no picks, on the response,
on `games[]`, or on a team. `canMakePicks` is `false` where the browser had `true`.
So the picks are real and they are behind the session; the public view is the
slate plus your entry's metadata.

**THE CONTEST STATES THE RULES THIS BOARD ASSUMES, SO THEY ARE CHECKED RATHER
THAN ASSUMED.** `pickReuseLimit: 0` IS "each team at most once", `entryLives: 1`,
`expectedPicksCount: 1`, `slateCount: 18`. That is the assignment problem the
solver models, stated by the contest itself — and `splash_inspect` prints a
`<-- NOT 0` beside any of them that disagrees, because a contest with two lives
or a reuse allowance is a **different game** and the board would go on rendering
perfectly while modelling something else.

**112 ENTRIES OF A 1,000 CAP, 10 PER USER, $50 IN, $43,750 UP.** The entries
number is `entries.filled` and it is what a pool tab's size field wants — and it
is a **cap-and-fill** contest, so it moves until the deadline. Read again on the
morning of the draft rather than typed once.

**THE TEAM IDS ARE SPLASH'S OWN UUIDs AND THE JOIN IS ON `alias`.** 32 teams,
32 joining our board, 0 unmatched. `splash_inspect` reports that count every run,
because an unmatched code joins to nothing, that team silently drops out, and
every remaining number still looks like a number — the Michael Carter rule, one
platform over.

## THE CONTEST BECOMES A TAB, AND IT WRITES ITS OWN FILE

`python pull_field.py --platform splash <url>` writes **`splash.js`**, and the
board seeds a pool tab from it — named and sized from the contest rather than
typed. Pool tabs existed for a week before this did, which is the shelf without
the stock: *"I don't see the Splash Sports pool in the website"* is exactly what
a mechanism with nothing driving it looks like.

**ITS OWN FILE, NOT `field.js`.** Two pullers writing one file means whichever
ran last wins and the other pool silently vanishes — and `field.js` is ESPN's
ownership, which every tab reads. Same convention as `season.js`: absent, the
`<script>` 404s and not one number moves.

**IT REFUSES A CONTEST THAT IS NOT THIS GAME.** The solver models one team a
week, each at most once, one life, and the contest STATES all three
(`pickReuseLimit 0`, `entryLives 1`, `expectedPicksCount 1`, `slateCount 18`).
Checked, not assumed: a contest with two lives would render on this board
perfectly and be a different game. `--force` overrides and says so.

**`entries.filled` IS THE SIZE AND IT MOVES.** 112 of a 1,000 cap today. A
cap-and-fill contest keeps filling until the deadline and every leverage number
is share-of-pool, so this is re-pulled on the morning of the draft rather than
trusted from August.

**SEEDING IS ONCE PER SOURCE, EVER.** `S.seeded` records the ids already offered
a tab, so a tab you DELETE stays deleted while the pull that created it goes on
succeeding — otherwise removal is impossible and the delete button lies. The key
is `src` (an id: `espn`, `splash:<contestId>`), never the name, so renaming a tab
cannot make it look like a different contest and two Splash contests cannot
collapse into one. `src` and `name` are identity and stay out of `POOL_KEYS`;
everything else on a record is carried by the switch.

**AND ITS OWNERSHIP IS `null`, DELIBERATELY.** Splash publishes none, so the tab
falls through to ESPN's measured counters as a proxy — stated on the page, never
silently.

## ONE SCHEDULE, SEVERAL POOLS

A 25-man ESPN pool and a large-field Splash contest are the same eighteen weeks and
two completely different games: the alive count is the leverage denominator, and
burned teams are per ENTRY, so a team gone in one is untouched in the other. Pool
tabs are that, and nothing more.

**PER-POOL is `pool`, `entries`, `lam`, `used`, `pins`, `own`** (`POOL_KEYS`).
**SHARED is `week`, `doubles`, `grid`, `ratings`** — those are the schedule and the
model, and duplicating them per pool would let two tabs disagree about what a team's
win probability is.

**THE LIVE STATE *IS* `pools[pi]` WHILE YOU ARE ON IT.** `stash()` writes the live
values back before anything reads the list; `loadPool()` reads them out. Two copies
of one fact is how a pool ends up wearing the other pool's burned teams — a board
that renders perfectly and recommends a team you already used. `test_pools.js` pins
the round trip, that the records do not share one `used[]` array, and that every
field on a pool record is in `POOL_KEYS`, since one left out is copied on neither leg.

**MIGRATION BUILDS POOL ONE FROM WHAT IS ON SCREEN, NOT FROM A DEFAULT.** A board
saved before pools existed has one pool and it is the season you have been keeping;
`ensurePools()` stashes the live values into it. A default there would silently
discard a season of picks. A stale `pi` clamps rather than blanking the board.

**ESPN'S COUNTERS APPLY TO EVERY TAB AND THE PAGE SAYS SO.** They are ESPN-wide
already, no other platform publishes counts, and a measured proxy beats a modelled
one. Pasted ownership is per-pool, because pasting numbers is a claim about a
specific room.

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
