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

const STATUS_CSV =
  "generated_utc,coverage_end,last_complete_year,expected_refresh_days\n" +
  "2026-08-10 09:17:15,2026-08-10 07:00,2025,10\n";

// Everything the Worker reaches for, stubbed. The deliverable body is a marker rather than a real
// xlsx: this suite is about routing and headers, not about zip contents.
const calls = [];
globalThis.fetch = async (u, opts = {}) => {
  const url = String(u);
  calls.push(url);
  if (url.includes("/contents/published/charts/status.csv")) {
    return new Response(STATUS_CSV, { status: 200 });
  }
  if (url.includes("/contents/deliverables/")) {
    return new Response("DELIVERABLE-BYTES", { status: 200 });
  }
  if (url.includes("/actions/workflows/") && url.includes("/runs")) {
    return new Response(JSON.stringify({ workflow_runs: [{
      status: "completed", conclusion: "success", updated_at: "2026-08-10T09:40:00Z",
      html_url: "https://github.com/fredhill123/power-price-data/actions/runs/1",
    }] }), { status: 200, headers: { "content-type": "application/json" } });
  }
  if (url.startsWith("https://raw.githubusercontent.com")) {
    return new Response(url.endsWith("status.csv") ? STATUS_CSV : "RAW-BYTES", { status: 200 });
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

console.log(fails.length ? `FAILED: ${fails.join(", ")}` : "page_test: all assertions passed");
process.exit(fails.length ? 1 : 0);
