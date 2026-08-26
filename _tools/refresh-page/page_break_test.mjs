/* page_break_test.mjs — drive the public page through the states nobody has ever seen it in.
 *
 * page_test.mjs asserts the page is RIGHT when everything works. This one asserts it does
 * not fall over when things do not, which is a different question and was never asked. On
 * 2026-08-26 the answer was no in three places, each found by injection rather than reading:
 *
 *   * POST /trigger with `Origin: null` returned HTTP 500 from the live Worker.
 *     `new URL("null")` throws, and that is what a sandboxed iframe or a file:// page sends.
 *   * The 30-minute cooldown counted a FAILED run as a refresh, so the moment someone most
 *     wants to retry was the moment they were refused.
 *   * The quoted duration took the last successful run of this workflow, and repair.yml
 *     dispatches this same workflow: the first repair would have had the page promising two
 *     minutes for a job that takes closer to an hour.
 *
 * Everything is stubbed, so this needs no network and no token.
 *
 *     node _tools/refresh-page/page_break_test.mjs
 */
import { pathToFileURL, fileURLToPath } from "node:url";
import path from "node:path";
const WORKER = process.env.WORKER_JS
  || path.join(path.dirname(fileURLToPath(import.meta.url)), "worker.js");
const out = [];
function rec(name, verdict, detail) { out.push({name, verdict, detail});
  console.log(`  ${verdict.padEnd(4)}  ${name}${detail ? "   " + detail : ""}`); }

let HEALTH = null, STATUS = null, RUNS = null, RUNS_STATUS = 200, RAW_STATUS = 200,
    DISPATCH_STATUS = 204, HEALTH_BODY = null;
const stamp = (d) => d.toISOString().slice(0, 19).replace("T", " ");
const YD = new Date(Date.now() - 24 * 3600 * 1000);
const STATUS_CSV = "generated_utc,coverage_end,last_complete_year,expected_refresh_days\n" +
  `${stamp(YD)},${stamp(YD)},${YD.getUTCFullYear() - 1},10\n`;

globalThis.fetch = async (u, opts = {}) => {
  const url = String(u);
  if (url.endsWith("/published/charts/health.json"))
    return HEALTH_BODY !== null ? new Response(HEALTH_BODY, {status: 200})
      : HEALTH === null ? new Response("nf", {status: 404})
      : new Response(JSON.stringify(HEALTH), {status: 200});
  if (url.includes("/contents/published/charts/status.csv"))
    return new Response(STATUS ?? STATUS_CSV, {status: STATUS === "MISSING" ? 404 : 200});
  if (url.includes("/contents/deliverables/")) return new Response("BYTES", {status: 200});
  if (url.includes("/dispatches"))
    return new Response(DISPATCH_STATUS === 204 ? null : "x", {status: DISPATCH_STATUS});
  if (url.includes("/actions/workflows/") && url.includes("/runs"))
    return RUNS_STATUS !== 200 ? new Response("boom", {status: RUNS_STATUS})
      : new Response(JSON.stringify({workflow_runs: RUNS ?? [{
          status: "completed", conclusion: "success",
          run_started_at: new Date(Date.now()-3600e3).toISOString(),
          updated_at: new Date(Date.now()-3000e3).toISOString()}]}),
        {status: 200, headers: {"content-type": "application/json"}});
  if (url.startsWith("https://raw.githubusercontent.com"))
    return new Response(url.endsWith("status.csv") ? (STATUS ?? STATUS_CSV) : "RAW",
      {status: RAW_STATUS});
  return new Response("nope", {status: 404});
};

const worker = (await import(pathToFileURL(WORKER).href)).default;
const env = {GH_TOKEN: "tok"};
const HOST = "https://power-price-data.fredhill.workers.dev";
const G = (p, init) => new Request(HOST + p, init);
const reset = () => { HEALTH=null; STATUS=null; RUNS=null; RUNS_STATUS=200; RAW_STATUS=200;
                      DISPATCH_STATUS=204; HEALTH_BODY=null; };
const try_ = async (fn) => { try { return {r: await fn()}; } catch (e) { return {e}; } };

console.log("=== ADVERSARIAL: public page ===");

// --- 1. Origin: null (sandboxed iframe, some redirects, privacy modes) ---
reset();
{ const {r, e} = await try_(() => worker.fetch(
    G("/trigger", {method:"POST", headers:{Origin:"null"}}), env));
  rec("POST /trigger with Origin: null",
      e ? "BAD" : (r.status < 500 ? "ok" : "BAD"),
      e ? `THREW ${e.constructor.name}: ${e.message}` : `status ${r.status}`); }

reset();
{ const {r, e} = await try_(() => worker.fetch(
    G("/trigger", {method:"POST", headers:{Origin:"chrome-extension://abc"}}), env));
  rec("POST /trigger with a non-http Origin",
      e ? "BAD" : (r.status < 500 ? "ok" : "BAD"),
      e ? `THREW ${e.constructor.name}` : `status ${r.status}`); }

// --- 2. Retry immediately after a FAILURE ---
reset();
RUNS = [{status:"completed", conclusion:"failure",
         run_started_at:new Date(Date.now()-300e3).toISOString(),
         updated_at:new Date(Date.now()-120e3).toISOString()}];
{ const r = await worker.fetch(G("/trigger",{method:"POST"}), env);
  const h = await r.text();
  const blocked = /Please wait/.test(h);
  rec("a user may retry straight after a FAILED run", blocked ? "BAD" : "ok",
      blocked ? "blocked by the 30-min cooldown, which counts a failure as a refresh" : ""); }

// --- 3. Duration quoted after a short REPAIR run (repair.yml dispatches refresh.yml) ---
reset();
RUNS = [{status:"completed", conclusion:"success",          // the repair, 2 min
         display_title:"Repair (only the series that failed)",
         run_started_at:new Date(Date.now()-600e3).toISOString(),
         updated_at:new Date(Date.now()-480e3).toISOString()},
        {status:"completed", conclusion:"success",          // the real run, 45 min
         display_title:"Refresh",
         run_started_at:new Date(Date.now()-7200e3).toISOString(),
         updated_at:new Date(Date.now()-4500e3).toISOString()}];
{ const r = await worker.fetch(G("/"), env); const h = await r.text();
  const m = h.match(/about (\d+) minutes?, going by the last one/);
  rec("a short repair run is not quoted as the duration of a refresh",
      m && +m[1] === 45 ? "ok" : "BAD",
      m ? `page says "about ${m[1]} minutes"` : "no figure at all"); }

// --- 4. failed vs cancelled: the page must not confuse the two ---
reset();
HEALTH = {state:"failed", at:new Date().toISOString(),
          reason:"generation: nothing stored", series:["generation"], fatal:[], stale:[]};
{ const r = await worker.fetch(G("/"), env); const h = await r.text();
  rec("a real failure is reported as one", /refresh failed/i.test(h) ? "ok" : "BAD"); }
reset();
HEALTH = {state:"cancelled", at:new Date().toISOString(),
          reason:"the run was stopped before it finished", series:[], fatal:[], stale:[]};
{ const r = await worker.fetch(G("/"), env); const h = await r.text();
  rec("a CANCELLED run is not reported as a failure",
      /stopped before it finished/.test(h) && !/refresh failed/i.test(h) ? "ok" : "BAD",
      "cancelling run 32959091445 made the live page announce a failure, 2026-08-26"); }

// --- 4b. status.csv is parsed as a CSV, quoted commas included ---
reset();
STATUS = "generated_utc,health_tabs,expected_refresh_days\n" +
         `${stamp(YD)},"Fig5_Capture, CaptureMonthly, D_NetloadDuck",10\n`;
{ const r = await worker.fetch(G("/"), env); const h = await r.text();
  rec("a quoted, comma-bearing column does not shift the fields after it",
      /Last refreshed/.test(h) && !/Could not read/.test(h) ? "ok" : "BAD"); }

// --- 5. GitHub API down / rate-limited ---
for (const code of [500, 403, 401]) {
  reset(); RUNS_STATUS = code;
  const {r, e} = await try_(() => worker.fetch(G("/"), env));
  rec(`page renders when the runs API returns ${code}`,
      e ? "BAD" : (r.status === 200 ? "ok" : "BAD"),
      e ? `THREW ${e.message}` : `status ${r.status}`);
}

// --- 6. status.csv missing entirely ---
reset(); STATUS = "MISSING"; RAW_STATUS = 404;
{ const {r, e} = await try_(() => worker.fetch(G("/"), env));
  rec("page renders when status.csv is missing", e ? "BAD" : (r.status===200?"ok":"BAD"),
      e ? `THREW ${e.message}` : `status ${r.status}`); }

// --- 7. malformed health.json ---
reset(); HEALTH_BODY = "{ this is not json";
{ const {r, e} = await try_(() => worker.fetch(G("/"), env));
  rec("page renders when health.json is malformed", e ? "BAD" : (r.status===200?"ok":"BAD"),
      e ? `THREW ${e.message}` : `status ${r.status}`); }

// --- 8. status.csv header only, no data row ---
reset(); STATUS = "generated_utc,coverage_end\n";
{ const {r, e} = await try_(() => worker.fetch(G("/"), env));
  rec("page renders when status.csv has no data row", e ? "BAD" : (r.status===200?"ok":"BAD"),
      e ? `THREW ${e.message}` : `status ${r.status}`); }

// --- 9. file routes ---
reset();
// 302 for the traversal is correct: new URL() normalises "../" away, so the path is
// no longer under /file/ and falls through to the redirect. Nothing is served.
for (const [p, want] of [["/file/HourlyPowerData.xlsx", 200], ["/file/../../etc/passwd", 302],
                         ["/file/%2e%2e%2fsecret", 404], ["/file/%E0%A4%A", 404],
                         ["/file/", 404], ["/file/nope.xlsx", 404]]) {
  const {r, e} = await try_(() => worker.fetch(G(p), env));
  rec(`GET ${p}`, e ? "BAD" : (r.status === want ? "ok" : "BAD"),
      e ? `THREW ${e.message}` : `status ${r.status} (wanted ${want})`);
}

// --- 10. deliverable unreachable on both paths ---
reset(); RAW_STATUS = 500;
globalThis.fetch = (orig => async (u, o) => {
  const url = String(u);
  if (url.includes("/contents/deliverables/")) return new Response("no", {status: 500});
  return orig(u, o);
})(globalThis.fetch);
{ const r = await worker.fetch(G("/file/HourlyPowerData.xlsx"), env);
  rec("deliverable unreachable gives a readable 502", r.status === 502 ? "ok" : "BAD",
      `status ${r.status}`); }

// --- 11. method / path guards ---
reset();
{ const r = await worker.fetch(G("/", {method:"POST"}), env);
  rec("POST / (not /trigger) does not dispatch", r.status === 200 ? "ok" : "BAD", `status ${r.status}`); }
{ const r = await worker.fetch(G("/trigger"), env);          // GET
  rec("GET /trigger does not dispatch", r.status === 302 ? "ok" : "BAD", `status ${r.status}`); }
{ const r = await worker.fetch(G("/file/HourlyPowerData.xlsx", {method:"DELETE"}), env);
  rec("DELETE /file/ is refused", r.status === 405 ? "ok" : "BAD", `status ${r.status}`); }

// --- 12. no token at all ---
reset();
{ const {r, e} = await try_(() => worker.fetch(G("/"), {}));
  rec("page renders with NO token configured", e ? "BAD" : (r.status===200?"ok":"BAD"),
      e ? `THREW ${e.message}` : `status ${r.status}`); }
{ const {r, e} = await try_(() => worker.fetch(G("/file/HourlyPowerData.xlsx"), {}));
  rec("download works with NO token configured", e ? "BAD" : (r.status===200?"ok":"BAD"),
      e ? `THREW ${e.message}` : `status ${r.status}`); }

// --- 13. dispatch refused by GitHub ---
reset(); DISPATCH_STATUS = 422;
RUNS = [{status:"completed", conclusion:"success",
         run_started_at:new Date(Date.now()-7200e3).toISOString(),
         updated_at:new Date(Date.now()-5400e3).toISOString()}];
{ const r = await worker.fetch(G("/trigger",{method:"POST"}), env); const h = await r.text();
  rec("a refused dispatch is reported, not swallowed", /HTTP 422/.test(h) ? "ok" : "BAD"); }

const bad = out.filter((o) => o.verdict === "BAD");
console.log(`\nPAGE UNDER FAULT: ${bad.length ? "FAIL " + bad.map((b) => b.name).join(", ")
  : `PASS — ${out.length} fault(s) survived`}`);
process.exit(bad.length ? 1 : 0);
