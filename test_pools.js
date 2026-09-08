/* Pins that two pools on one schedule stay two pools. `node test_pools.js`

   The failure this guards is the worst kind here and it is completely silent:
   the live state IS pools[pi] while you are on it, so a missing stash() leaves
   one pool wearing the other's burned teams -- a board that renders perfectly
   and recommends a team you have already used. */
const fs = require("fs"), path = require("path");
const h = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const js = h.slice(h.indexOf("<script>\nconst EMBEDDED_SAMPLE") + 8,
                   h.indexOf("/* ============================================================ presentation ==="));
const api = new Function(js + "\n return {S,POOL_KEYS,blankPool,stash,loadPool,ensurePools,BY_ABBR};")();
const { S, POOL_KEYS, blankPool, stash, loadPool, ensurePools } = api;

let fails = 0;
const ok = (name, cond, note) => {
  if (cond) console.log("  ok   " + name);
  else { fails++; console.log("  FAIL " + name + (note ? ": " + note : "")); }
};

/* A board saved before pools existed has one pool and it is WHATEVER IS ON
   SCREEN. Migrating to a default would silently discard a season of picks. */
S.pools = null; S.pi = 0;
S.pool = 25; S.used = [1, 2]; S.lam = 0.4; S.entries = 2;
ensurePools();
ok("migration keeps the board you already had",
   S.pools.length === 1 && S.pools[0].pool === 25 && S.pools[0].used.length === 2 &&
   S.pools[0].lam === 0.4,
   JSON.stringify(S.pools[0]));

/* Switching. Pool 2 must start clean and must not write through to pool 1. */
stash();
S.pools.push(blankPool("Splash")); loadPool(1);
ok("a new pool starts empty", S.used.length === 0 && S.pool === 500 && S.lam === null);

S.used = [7]; S.pool = 8000;
stash(); loadPool(0);
ok("pool 1 survives an edit made in pool 2",
   S.pool === 25 && S.used.join() === "1,2", `got pool=${S.pool} used=${S.used}`);

stash(); loadPool(1);
ok("and pool 2 survives the trip back",
   S.pool === 8000 && S.used.join() === "7", `got pool=${S.pool} used=${S.used}`);

/* Arrays are the trap: assigning the live array into the record without a copy
   means both records point at ONE array, and burning a team in either burns it
   in both. Prove they are distinct objects. */
ok("the two records do not share one used[] array",
   S.pools[0].used !== S.pools[1].used);
S.pools[1].used.push(9);
ok("...and pushing to one does not reach the other",
   S.pools[0].used.indexOf(9) < 0);

/* pi out of range is reachable: delete the last pool in one tab, load in
   another. It must clamp, not throw and not render an empty board. */
S.pi = 99; ensurePools();
ok("a stale pool index clamps rather than blanking the board",
   S.pi === S.pools.length - 1);

/* Everything per-pool must actually be in POOL_KEYS. A field added to the pool
   record but left out of the list is copied on neither leg of the switch. */
ok("every field on a pool record is carried by the switch",
   Object.keys(blankPool("x")).every(k => k === "name" || POOL_KEYS.includes(k)),
   Object.keys(blankPool("x")).filter(k => k !== "name" && !POOL_KEYS.includes(k)).join(" "));

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
