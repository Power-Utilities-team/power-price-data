/* The public status page names GitHub nowhere, and serves exactly three files.
 *
 * Fred, 2026-08-17: "remove any links that would show my github profile", and simplify the
 * downloads. The page used to carry four download links, three browse links and a run-log link,
 * every one a github.com URL containing the account name. The load-bearing assertion here is the
 * first one: not one github reference in the rendered HTML.
 *
 *     node "Power Price Data/_tools/refresh-page/page_test.mjs"
 */
import { pathToFileURL, fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const fails = [];

function check(ok, name, extra) {
  console.log(`  ${ok ? "ok  " : "FAIL"}  ${name}${ok || extra === undefined ? "" : `   ${extra}`}`);
  if (!ok) fails.push(name);
}

// RELATIVE TO NOW, NEVER A LITERAL (fixed 2026-08-23). This was pinned to
// "2026-08-10 09:17:15" against a 10-day tolerance, so the suite was green when it was
// written and went red on 20 August for a calendar reason: the fixture aged past the
// tolerance and every assertion about the HEALTHY page started seeing the stale-and-recover
// page instead. Three checks had been failing for days with nothing wrong in the code, and
// a suite that is red for a reason nobody caused is one people learn to ignore.
const stamp = (d) => d.toISOString().slice(0, 19).replace("T", " ");
const YESTERDAY = new Date(Date.now() - 24 * 3600 * 1000);
const STATUS_CSV =
  "generated_utc,coverage_end,last_complete_year,expected_refresh_days\n" +
  `${stamp(YESTERDAY)},${stamp(YESTERDAY)},${YESTERDAY.getUTCFullYear() - 1},10\n`;

// Everything the Worker reaches for, stubbed. The deliverable body is a marker rather than a real
// xlsx: this suite is about routing and headers, not about zip contents.
const calls = [];
// The health record published beside status.csv. `null` is the ordinary case: a repo that
// has never failed has no such file, and the page must read that as fine rather than as an
// error. Reassigned below to drive the two states that DO say something.
let HEALTH = null;
let STATUS = null;                       // null = use STATUS_CSV
// The workflow-run sample the page derives its duration figure from. `null` = the default
// single completed run, which carries no run_started_at and so yields no derived figure.
let RUNS = null;
globalThis.fetch = async (u, opts = {}) => {
  const url = String(u);
  calls.push(url);
  if (url.endsWith("/published/charts/health.json")) {
    return HEALTH === null
      ? new Response("not found", { status: 404 })
      : new Response(JSON.stringify(HEALTH), { status: 200 });
  }
  if (url.includes("/contents/published/charts/status.csv")) {
    return new Response(STATUS || STATUS_CSV, { status: 200 });
  }
  if (url.includes("/contents/deliverables/")) {
    return new Response("DELIVERABLE-BYTES", { status: 200 });
  }
  if (url.includes("/contents/published/charts/")) {
    return new Response("date,value\n2026-01-01,1\n", { status: 200 });
  }
  if (url.includes("/actions/workflows/") && url.includes("/runs")) {
    return new Response(JSON.stringify({ workflow_runs: RUNS || [{
      status: "completed", conclusion: "success", updated_at: "2026-08-10T09:40:00Z",
      html_url: "https://github.com/fredhill123/power-price-data/actions/runs/1",
    }] }), { status: 200, headers: { "content-type": "application/json" } });
  }
  if (url.startsWith("https://raw.githubusercontent.com")) {
    return new Response(url.endsWith("status.csv") ? (STATUS || STATUS_CSV) : "RAW-BYTES", { status: 200 });
  }
  return new Response("nope", { status: 404 });
};

const worker = (await import(pathToFileURL(path.join(HERE, "worker.js")).href)).default;
const env = { GH_TOKEN: "stub-token" };
const get = (p) => new Request(`https://power-price-data.fredhill.workers.dev${p}`);

console.log("power-prices public page");

// 1. THE assertion: the rendered page names GitHub nowhere
const home = await worker.fetch(get("/"), env);
const html = await home.text();
check(home.status === 200, "the page renders", home.status);
for (const needle of ["github.com", "githubusercontent", "fredhill123", "/tree/", "Repository",
                      "view log"]) {
  check(!html.includes(needle), `the page does not contain "${needle}"`);
}

// 2. exactly three downloads, all pointing at this Worker
const hrefs = [...html.matchAll(/href="([^"]+)"/g)].map((m) => m[1]);
const fileLinks = hrefs.filter((h) => h.startsWith("/file/"));
check(fileLinks.length === 3, "three download links", fileLinks.length);
check(hrefs.every((h) => h.startsWith("/") || h.startsWith("#")),
      "every link on the page is same-origin", hrefs.filter((h) => !h.startsWith("/")));
check(!html.includes("HourlyPowerData_snapshot.pptx"), "the snapshot deck is gone");
check(html.includes("Excel workbook (live)") && html.includes("PowerPoint (linked)")
      && html.includes("Excel (self-contained)"), "the three Fred picked are the three offered");

// 2b. the data card: every published file the workbook reads, same-origin, no GitHub
// Added 2026-08-27. Fred asked to see the files the pipeline pulls from and asked whether a
// GitHub folder link could hide the history. It cannot, so the list lives here instead, and
// these assertions are what stop it drifting back into a /tree/ link.
const dataLinks = hrefs.filter((h) => h.startsWith("/data/"));
check(dataLinks.length === 32, "the data card lists all 32 published files", dataLinks.length);
check(dataLinks.every((h) => h.startsWith("/data/")), "every data link is same-origin");
check(html.includes("The data behind the charts"), "the data card has a heading");
check(html.includes("status.csv") && html.includes("health.json"),
      "the card names the status record and the health record");

const csv = await worker.fetch(get("/data/fig9_capacity.csv"), env);
check(csv.status === 200, "an allowlisted data file is served", csv.status);
check(csv.headers.get("content-type").startsWith("text/plain"),
      "a CSV is served as text so it can be READ in the browser, not downloaded",
      csv.headers.get("content-type"));
const hj = await worker.fetch(get("/data/health.json"), env);
check(hj.headers.get("content-type").startsWith("application/json"),
      "the health record is served as JSON", hj.headers.get("content-type"));

// The allowlist is the whole security model of this route, exactly as for /file/.
for (const bad of ["../../.github/workflows/refresh.yml", "..%2F..%2Fsecrets", "notafile.csv",
                   "status.csv.bak"]) {
  const r = await worker.fetch(get(`/data/${encodeURIComponent(bad)}`), env);
  check(r.status === 404, `/data/ refuses "${bad}"`, r.status);
}
const del = await worker.fetch(
  new Request("https://power-price-data.fredhill.workers.dev/data/status.csv", { method: "DELETE" }), env);
check(del.status === 405, "DELETE /data/ is refused", del.status);

// 3. the proxy serves an allowlisted file with file-ish headers
let r = await worker.fetch(get("/file/HourlyPowerData.xlsx"), env);
check(r.status === 200, "an allowlisted file downloads", r.status);
check((r.headers.get("content-type") || "").includes("spreadsheetml"),
      "with an xlsx content type", r.headers.get("content-type"));
check((r.headers.get("content-disposition") || "").includes('filename="HourlyPowerData.xlsx"'),
      "and a filename, so it saves rather than renders");
check((await r.text()) === "DELIVERABLE-BYTES", "the body is the file, proxied");

// 4. and refuses everything else
for (const p of ["/file/data/config.json", "/file/",
                 "/file/HourlyPowerData_snapshot.pptx", "/file/published/charts/status.csv"]) {
  r = await worker.fetch(get(p), env);
  check(r.status === 404, `404 on ${p}`, r.status);
}
// Traversal is asserted on the OUTCOME, not on a status code. `new URL()` normalises "../" away
// before any routing happens, so this request arrives as /secrets.txt and meets the catch-all
// redirect rather than the proxy. It gets no file either way, which is the property that matters.
r = await worker.fetch(get("/file/../../secrets.txt"), env);
check(r.status !== 200 || !(await r.text()).includes("BYTES"),
      "a traversal attempt is served no file", r.status);
r = await worker.fetch(new Request(
  "https://power-price-data.fredhill.workers.dev/file/HourlyPowerData.xlsx",
  { method: "POST" }), env);
check(r.status === 405, "the proxy is GET only", r.status);

// 5. it prefers the authenticated API, which is what stopped the 429s
calls.length = 0;
await worker.fetch(get("/file/HourlyPowerData_frozen.xlsx"), env);
check(calls.some((c) => c.startsWith("https://api.github.com")),
      "downloads go through the authenticated API");
check(!calls.some((c) => c.startsWith("https://raw.githubusercontent.com")),
      "and not through rate-limited raw when a token exists");

// 6. with no token it still works, via raw
calls.length = 0;
r = await worker.fetch(get("/file/HourlyPowerData.xlsx"), {});
check(r.status === 200 && (await r.text()) === "RAW-BYTES",
      "with no token it falls back to raw rather than failing");

// 7. Recovery instructions appear only when something is wrong, and never ask for a credential.
// Fred asked for a replacement ENTSO-E key to be suppliable THROUGH this page; that was declined
// (public and unauthenticated) and this block is the agreed alternative, so the assertion that it
// collects nothing is as load-bearing as the assertion that it shows up.
check(!html.includes("data-source key"),
      "a healthy page says nothing about replacing a key");

const failing = await (async () => {
  const prev = globalThis.fetch;
  globalThis.fetch = async (u, o) => {
    const url = String(u);
    if (url.includes("/actions/workflows/") && url.includes("/runs")) {
      return new Response(JSON.stringify({ workflow_runs: [{
        status: "completed", conclusion: "failure", updated_at: "2026-08-10T09:40:00Z",
        html_url: "https://github.com/x/y/actions/runs/1",
      }] }), { status: 200, headers: { "content-type": "application/json" } });
    }
    return prev(u, o);
  };
  const res = await worker.fetch(get("/"), env);
  const t = await res.text();
  globalThis.fetch = prev;
  return t;
})();

check(failing.includes("If the refresh keeps failing"),
      "a failed run brings up the recovery block");
check(failing.includes("ENTSOE_API_KEY") && failing.includes("Transparency Platform"),
      "it names the secret and where to get a key");
check(!/<input|<textarea|<form[^>]*action="\/(?!trigger)/.test(failing),
      "and it collects nothing: no field to paste a key into");
check(!failing.includes("github.com") && !failing.includes("fredhill123"),
      "still no GitHub URL or account name, even in the failure state");

// 8. A token that is PRESENT but not working is its own state, and must not render a button that
// fails on click. This is what the 2026-08-17 org transfer produced: the PAT was scoped to the old
// owner, the status line kept working via the unauthenticated raw fallback, and only the Refresh
// button was actually broken.
const noRun = await (async () => {
  const prev = globalThis.fetch;
  globalThis.fetch = async (u, o) => {
    const url = String(u);
    if (url.includes("/actions/workflows/") && url.includes("/runs")) {
      return new Response("no", { status: 404 });   // token cannot see the repo
    }
    return prev(u, o);
  };
  const t = await (await worker.fetch(get("/"), env)).text();
  globalThis.fetch = prev;
  return t;
})();
check(!noRun.includes("Start a refresh"),
      "a token that cannot read the repo hides the Refresh button");
// Whitespace-normalised: the sentence wraps across source lines in the template, so a literal
// substring match tests the indentation rather than the wording.
const flat = (s) => s.replace(/\s+/g, " ");
check(flat(noRun).includes("cannot currently read this repository"),
      "and says so, rather than failing silently on click");
check(!noRun.includes("has not been configured"),
      "and does not confuse that with no token at all");

const noToken = await (await worker.fetch(get("/"), {})).text();
check(noToken.includes("has not been configured") && !noToken.includes("Start a refresh"),
      "no token at all is still its own distinct message");

// 8. THE HEALTH RECORD (2026-08-23). status.csv can only say how OLD the data is, which is
// what the page said for thirteen days in August while the actual cause — ENTSO-E answering
// 504 for one German series — sat in a run log. These pin the difference.
{
  STATUS =
    "generated_utc,coverage_end,last_complete_year,expected_refresh_days\n" +
    "2026-08-10 09:17:15,2026-08-10 07:00,2025,10\n";   // deliberately ancient
  HEALTH = { state: "failed", reason: "generation: nothing stored",
             series: ["generation"], fatal: [], stale: [] };
  const bad = flat(await (await worker.fetch(get("/"), env)).text());
  check(/days old/.test(bad), "an old page still leads with the age");
  check(bad.includes("generation: nothing stored"),
        "and now names the cause the failing run recorded");

  // fresh data AND a failed run: the case a drill caught on 2026-08-23. The first version
  // only spoke inside the `stale` branch, so a run that failed this morning left the page
  // saying "Data is current" and nothing else, and the reader would not learn until the
  // age tolerance expired ten days later.
  STATUS = null;
  HEALTH = { state: "failed", reason: "generation: nothing stored",
             series: ["generation"], fatal: [], stale: [] };
  const sameDay = flat(await (await worker.fetch(get("/"), env)).text());
  check(sameDay.includes("The last refresh failed"),
        "a failure is reported the day it happens, not when the data ages out");
  check(sameDay.includes("generation: nothing stored"),
        "and it names the series even while the figures are current");
  check(sameDay.includes("still current"),
        "while making clear the numbers on the page are not the problem");

  STATUS = null;
  HEALTH = { state: "ok-on-stored-data",
             reason: "generation: fetch failed, published from stored data (2d old)",
             series: ["generation"], fatal: [],
             stale: [{ series: "generation", covers_to: "2026-08-21T07:00", days_old: 2 }] };
  const warn = flat(await (await worker.fetch(get("/"), env)).text());
  check(warn.includes("one series from stored data"),
        "a run that leaned on the fallback store says so on the page");
  check(warn.includes("Every other series is current"),
        "and puts it in proportion rather than reading as an outage");

  HEALTH = null;
  const fine = flat(await (await worker.fetch(get("/"), env)).text());
  check(!fine.includes("stored data") && /Data is current/.test(fine),
        "no health record at all reads as healthy, not as an error");
}

// HOW LONG A RUN TAKES, derived and never asserted (added 2026-08-26).
//
// The page said "about 20 minutes" in four places. On the morning this was written the last
// complete run took 40 minutes and the one in flight took 69, so the promise was wrong by two
// to three times, and a colleague who waits the promised twenty minutes and sees nothing new
// concludes the pipeline is broken.
//
// The point of these assertions is that the OLD wording would fail them. The suite passed
// identically before and after the fix until these existed, which made it no guard at all.
{
  // `daysAgo` is what makes these runs orderable, and the ordering is the whole point: the
  // figure must come from the LATEST success, not from a summary of many.
  const mk = (mins, daysAgo, conclusion = "success") => {
    const start = new Date(Date.now() - daysAgo * 86400000);
    return {
      status: "completed", conclusion,
      run_started_at: start.toISOString(),
      updated_at: new Date(start.getTime() + mins * 60000).toISOString(),
    };
  };

  RUNS = [mk(40, 1), mk(44, 2), mk(10, 3), mk(12, 4)];
  let flatHtml = flat(await (await worker.fetch(get("/"), env)).text());
  check(!/about 20 minutes/.test(flatHtml),
        "the page no longer promises a hardcoded 20 minutes");
  check(/about 40 minutes/.test(flatHtml),
        "it quotes what the last successful run actually took", flatHtml.slice(0, 200));

  // THE REGRESSION THAT MATTERS, and the one this file existed a whole hour without.
  //
  // The first fix here took the median of the sample, and the live page went straight from
  // promising 20 minutes to promising 11, because every quick run in the real history had
  // fetched five markets and Great Britain was added on 25 August. Averaging across a change
  // in what a run DOES describes a pipeline that is gone.
  //
  // So: a sample whose recent runs are slow and whose older runs are fast must quote the
  // SLOW figure. A median of this returns 12 and fails, which is exactly the point.
  RUNS = [mk(69, 1), mk(66, 2), mk(12, 30), mk(10, 31), mk(11, 32), mk(6, 33), mk(4, 34)];
  flatHtml = flat(await (await worker.fetch(get("/"), env)).text());
  check(/about 69 minutes/.test(flatHtml),
        "a pipeline that got slower is not averaged back down by its own history",
        flatHtml.match(/Takes[^.]*\./)?.[0]);

  // Move the sample and the quoted figure must move with it. A number that survives this is
  // hardcoded somewhere, which is the original fault.
  RUNS = [mk(70, 1), mk(60, 2), mk(80, 3)];
  flatHtml = flat(await (await worker.fetch(get("/"), env)).text());
  check(/about 70 minutes/.test(flatHtml),
        "and the figure tracks the runs rather than being pinned");

  // A cancelled run is not evidence about how long the work takes. One killed at 2 minutes
  // is the most recent run here, and must not become the quoted figure.
  RUNS = [mk(2, 0, "cancelled"), mk(3, 0.5, "failure"), mk(70, 1), mk(60, 2)];
  flatHtml = flat(await (await worker.fetch(get("/"), env)).text());
  check(/about 70 minutes/.test(flatHtml),
        "cancelled and failed runs are excluded from the figure");

  // A reader watching a slow run needs the elapsed time more than the estimate.
  RUNS = [{ status: "in_progress", conclusion: null,
            run_started_at: new Date(Date.now() - 45 * 60000).toISOString(),
            updated_at: new Date().toISOString() }, mk(70, 1), mk(60, 2), mk(80, 3)];
  // Tag-agnostic: the sentence is emphasised in the page, and asserting the markup would
  // make this a test of the styling rather than of the figure.
  const text = (s) => flat(s.replace(/<[^>]+>/g, " "));
  let plain = text(await (await worker.fetch(get("/"), env)).text());
  check(/A refresh is running now , started 4[45] minutes ago/.test(plain)
        || /A refresh is running now, started 4[45] minutes ago/.test(plain),
        "a run in flight shows how long it has actually been going", plain.slice(0, 120));

  // No sample at all must not produce a confident wrong number. An honest range beats one.
  RUNS = [];
  flatHtml = flat(await (await worker.fetch(get("/"), env)).text());
  check(/roughly 40 to 70 minutes/.test(flatHtml),
        "with nothing to go on it gives a range, not a false point estimate");

  // The trigger path quotes the same figure as the page, so the two cannot drift apart.
  RUNS = [{ status: "in_progress", conclusion: null,
            run_started_at: new Date(Date.now() - 30 * 60000).toISOString(),
            updated_at: new Date().toISOString() }, mk(70, 1), mk(60, 2), mk(80, 3)];
  const busy = flat(await (await worker.fetch(
    new Request("https://power-price-data.fredhill.workers.dev/trigger", { method: "POST" }),
    env)).text());
  check(/already running, started (29|30|31) minutes ago/.test(busy),
        "the already-running message reports real elapsed time");
  check(/A run takes about 70 minutes/.test(busy) && !/about 20 minutes/.test(busy),
        "and quotes the same derived figure as the page");

  RUNS = null;
}

// THE PAGE MUST NAME EVERY MARKET IT CARRIES (added 2026-08-26). Great Britain went into
// the data on 25 August and the page's own subtitle still listed five markets, so the
// public description of the dataset was wrong for a day. Nothing could have caught it: no
// assertion had ever asked what the page CLAIMS to contain.
{
  // SCOPED TO THE SUBTITLE, not to the whole page. The first version of this checked the
  // rendered text for each market name and PASSED when Great Britain was deleted from the
  // list, because the sentence crediting Elexon mentions it too. A guard that cannot fail
  // is not a guard, which is the same lesson the missing y-axis labels taught that morning.
  const html = await (await worker.fetch(get("/"), env)).text();
  const sub = flat((html.match(/<p class="sub">([\s\S]*?)<\/p>/) || ["", ""])[1]
                   .replace(/<[^>]+>/g, " "));
  check(sub.length > 0, "the page has a description of the dataset");
  // THE ENUMERATION, not the whole subtitle. Scoping to the subtitle was still not enough:
  // its own Elexon clause names Great Britain a second time, so deleting the market from
  // the LIST left the assertion green. Take the run of text between "power prices" and the
  // first full stop, which is the list and nothing else.
  const listed = (sub.match(/power prices[^.]*/) || [""])[0];
  for (const market of ["Germany", "Spain", "Portugal", "France", "Italy",
                        "Great Britain"]) {
    check(listed.includes(market), `the market list names ${market}`, listed);
  }
  const text = flat(html.replace(/<[^>]+>/g, " "));
  // GB is not an ENTSO-E market, and a page that credits ENTSO-E for it is wrong about its
  // own provenance.
  check(/Elexon/.test(text),
        "and credits Elexon for Great Britain, which left ENTSO-E in 2021");

  // GitHub's raw run states are not English. "Last run in_progress" reached the live page.
  RUNS = [{ status: "in_progress", conclusion: null,
            run_started_at: new Date(Date.now() - 5 * 60000).toISOString(),
            updated_at: new Date().toISOString() }];
  const running = flat((await (await worker.fetch(get("/"), env)).text())
                       .replace(/<[^>]+>/g, " "));
  check(!/in_progress/.test(running),
        "a run still going is not described as \"in_progress\"");
  check(/Last run running now/.test(running),
        "it is described in words a reader can understand", running.match(/Last run [^.]{0,20}/)?.[0]);
  RUNS = null;
}

console.log(fails.length ? `FAILED: ${fails.join(", ")}` : "page_test: all assertions passed");
process.exit(fails.length ? 1 : 0);
