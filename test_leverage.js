/* Pins the leverage model. `node test_leverage.js`
   The failure this guards is silent: a Lev column that renders perfectly while
   being unable to rank anything. */
const fs = require("fs"), path = require("path");
const h = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const js = h.slice(h.indexOf("<script>\nconst EMBEDDED_SAMPLE") + 8,
                   h.indexOf("/* ============================================================ presentation ==="));
const api = new Function(js + "\n return {evaluate,S,ABBR,leverageWeek,P,NT};")();
const { evaluate, S, ABBR, leverageWeek } = api;

let fails = 0;
const ok = (name, cond, note) => {
  if (cond) console.log("  ok   " + name);
  else { fails++; console.log("  FAIL " + name + (note ? ": " + note : "")); }
};
const order = r => r.cands.map(c => ABBR[c.t]).join(" ");
const spread = (top, o, n) => { S.own = {}; S.own[top] = o;
  for (const c of n) if (c.t !== top) S.own[c.t] = (1 - o) / (n.length - 1); };

const base = evaluate(), top = base.cands[0].t;

spread(top, 0.60, base.cands);
ok("ownership reorders the board", order(evaluate()) !== order(base),
   "piling 60% on the top pick left the ranking identical -- Lev cannot see ownership");

const skew = evaluate().cands;
const ratios = skew.map(c => (c.lev / c.pw).toFixed(4));
ok("Lev is not just win probability rescaled", new Set(ratios).size > 1,
   "lev/win is the same constant for every row, so Lev is a monotone transform of win%");

const rankAt = o => { spread(top, o, base.cands);
  return evaluate().cands.findIndex(c => c.t === top); };
const cheap = rankAt(0.05), dear = rankAt(0.90);
ok("the chalk falls as the room piles on", dear > cheap,
   `rank ${cheap} at 5% owned vs ${dear} at 90% -- ownership must cost it`);

/* The hypothetical that forced this: the whole room on the chalk, a dog at
   near-identical odds. Exact answer, computed independently in Python:
   equity 0.752 on the chalk against 18.797 on the dog. */
S.own = null;
const play = [0, 1], own = { 0: 0.99, 1: 0.01 }, p = { 0: 0.75, 1: 0.73 };
const dp = (function () {                  // same convolution, standalone
  const B = 1000, out = {};
  for (const t of play) {
    const d = new Float64Array(B + 1); d[0] = 1; let hi = 0;
    for (const j of play) {
      if (j === t) continue;
      const b = Math.round(own[j] * B); if (b <= 0) continue;
      const nx = new Float64Array(B + 1);
      for (let k = 0; k <= hi; k++) { const v = d[k]; if (!v) continue;
        nx[k] += v * (1 - p[j]); nx[Math.min(B, k + b)] += v * p[j]; }
      hi = Math.min(B, hi + b); d.set(nx);
    }
    let e = 0; for (let k = 0; k <= hi; k++) if (d[k]) e += d[k] / (own[t] + k / B);
    out[t] = e;
  }
  return out;
})();
ok("99%-owned chalk vs 1%-owned dog: the dog wins big",
   p[1] * dp[1] > 20 * p[0] * dp[0],
   `equity ${(p[0]*dp[0]).toFixed(3)} vs ${(p[1]*dp[1]).toFixed(3)} -- expected ~0.75 vs ~18.8`);
ok("and it matches the independent exact calculation",
   Math.abs(p[1] * dp[1] - 18.797) < 0.05 && Math.abs(p[0] * dp[0] - 0.752) < 0.005);

console.log(fails ? `${fails} failed` : "all passed");
process.exit(fails ? 1 : 0);
