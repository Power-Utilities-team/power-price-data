/**
 * Power Price Data — public status & refresh page.
 *
 * A Cloudflare Worker, deliberately NOT a Pages deploy: Fred's `fredhill` Pages project is
 * gated by Cloudflare Access on `fredhill.pages.dev` and `*.fredhill.pages.dev`, and this
 * page has to be public. Workers are a separate product on a separate hostname
 * (`*.workers.dev`), so nothing here can widen or weaken that gate.
 *
 * What it does
 *   GET  /          status page: when the data was last refreshed, whether that is healthy,
 *                   when the next scheduled run is due, download links, data browser.
 *   POST /trigger   dispatches the GitHub Actions workflow.
 *
 * Why the trigger is POST-only
 *   A GET that changes state gets fired by accident: Teams, Slack, Outlook and WhatsApp all
 *   fetch links to build previews, as do scanners and browser prefetch. Paste a GET trigger
 *   into a chat and it starts a 20-minute job, then again on every re-share. POST is not
 *   followed by link unfurlers.
 *
 * Rate limiting is stateless: before dispatching we ask GitHub whether a run is already in
 * progress or finished recently, and refuse if so. No KV, nothing to expire, and it also
 * stops two people double-triggering.
 *
 * The token (GH_TOKEN) is a Worker secret — fine-grained, Actions:write on this one repo,
 * nothing else. It is never sent to the browser.
 */

const OWNER = "fredhill123";
const REPO = "power-price-data";
const WORKFLOW = "refresh.yml";
const BRANCH = "main";

const RAW = `https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}`;
const REPO_URL = `https://github.com/${OWNER}/${REPO}`;

// Matches the workflow's TWO cron lines: "23 7 * * 1" (every Monday) and "23 7 2 * *"
// (the 2nd of each month, which is the one that lands the just-closed month). Both fire
// at 07:23 UTC, so only the date varies and nextRun() takes whichever comes sooner.
//
// ⚠ This was wrong from 2026-08-01 to 2026-08-03 and nobody noticed, which is the whole
// argument for deriving it rather than restating it. The schedule moved from the 3rd to
// the 2nd and this constant stayed on the 3rd, so the page confidently advertised a run
// that did not exist. If you change the workflow cron, change it HERE too — this file
// cannot see the workflow, and a wrong answer here is worse than no answer, because the
// reader has no way to tell it is wrong.
const CRON = { weekday: 1, monthday: 2, hour: 7, minute: 23 };
const COOLDOWN_MIN = 30;

const NAVY = "#2E3E80";

/* ------------------------------------------------------------------ helpers */

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function nextRun(now = new Date()) {
  const t = now.getTime();

  // Next occurrence of the monthly line: the 2nd, this month or next.
  const mk = (y, m) => Date.UTC(y, m, CRON.monthday, CRON.hour, CRON.minute, 0);
  let monthly = mk(now.getUTCFullYear(), now.getUTCMonth());
  if (monthly <= t) monthly = mk(now.getUTCFullYear(), now.getUTCMonth() + 1);

  // Next occurrence of the weekly line: the coming Monday, or today if it is Monday and
  // 07:23 has not passed yet. Stepping in whole UTC days keeps this correct across the
  // month and year boundaries a naive date-add would trip on.
  let weekly = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(),
                        CRON.hour, CRON.minute, 0);
  while (weekly <= t || new Date(weekly).getUTCDay() !== CRON.weekday) {
    weekly += 86400000;
  }

  return new Date(Math.min(weekly, monthly));
}

function human(ms) {
  const d = Math.floor(ms / 86400000);
  const h = Math.floor((ms % 86400000) / 3600000);
  if (d > 0) return `${d} day${d === 1 ? "" : "s"}${h ? `, ${h}h` : ""}`;
  const m = Math.floor((ms % 3600000) / 60000);
  return h > 0 ? `${h}h ${m}m` : `${m} minute${m === 1 ? "" : "s"}`;
}

async function getStatus() {
  const r = await fetch(`${RAW}/published/charts/status.csv`, {
    cf: { cacheTtl: 60 },
    headers: { "User-Agent": "power-price-status-page" },
  });
  if (!r.ok) return null;
  const text = await r.text();
  const [head, row] = text.trim().split("\n");
  if (!row) return null;
  const keys = head.split(",");
  const vals = row.split(",");
  return Object.fromEntries(keys.map((k, i) => [k.trim(), (vals[i] || "").trim()]));
}

async function latestRun(env) {
  if (!env.GH_TOKEN) return null;
  const r = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=1`,
    {
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "power-price-status-page",
      },
    },
  );
  if (!r.ok) return null;
  const j = await r.json();
  return (j.workflow_runs && j.workflow_runs[0]) || null;
}

/* --------------------------------------------------------------------- page */

function page({ status, run, msg, err, hasToken }) {
  const now = new Date();

  let gen = null;
  let ageDays = null;
  if (status?.generated_utc) {
    gen = new Date(status.generated_utc.replace(" ", "T") + "Z");
    if (!isNaN(gen)) ageDays = (now - gen) / 86400000;
  }

  const limit = Number(status?.expected_refresh_days || 14);
  const chartsYear = Number(status?.charts_built_for_year || 0);
  const rolloverDue = chartsYear && now.getUTCFullYear() - 1 > chartsYear;
  const stale = ageDays != null && ageDays > limit;

  let tone = "ok";
  let headline = "Data is current";
  let detail = "";

  if (!status) {
    tone = "bad";
    headline = "Could not read the status record";
    detail = "GitHub may be unreachable. The data itself is unaffected.";
  } else if (stale) {
    tone = "bad";
    headline = `Data is ${Math.floor(ageDays)} days old`;
    detail = `The scheduled refresh has not run for longer than the ${limit}-day tolerance.`;
  } else if (rolloverDue) {
    tone = "warn";
    headline = `Charts still built for ${chartsYear}`;
    detail =
      `${now.getUTCFullYear() - 1} is complete but the charts do not show it yet. ` +
      `Download the newest workbook and deck below — refreshing an old file cannot add a year.`;
  } else if (ageDays != null) {
    detail = `Refreshed ${ageDays < 1 ? "today" : human(now - gen) + " ago"}.`;
  }

  const nr = nextRun(now);
  const nrTxt = nr.toUTCString().replace(":00 GMT", " UTC").replace(/^\w{3}, /, "");

  const runLine = run
    ? `Last run <strong>${esc(run.status === "completed" ? run.conclusion : run.status)}</strong>` +
      ` &middot; <a href="${esc(run.html_url)}" target="_blank" rel="noopener">view log</a>`
    : "";

  const files = [
    ["HourlyPowerData.xlsx", "Excel workbook (live)", "Refreshes itself from GitHub when you open it."],
    ["HourlyPowerData.pptx", "PowerPoint (linked)", "Charts link to the workbook — keep the two together."],
    ["HourlyPowerData_frozen.xlsx", "Excel (self-contained)", "No connections; opens anywhere."],
    ["HourlyPowerData_snapshot.pptx", "PowerPoint (self-contained)", "All images, nothing to update."],
  ];

  return `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Power Price Data — status</title>
<style>
  :root { --navy:${NAVY}; --ink:#1c1c1c; --mut:#6a6a6a; --line:#e3e3e6; --bg:#fff; --card:#fafafb; }
  @media (prefers-color-scheme: dark) {
    :root { --ink:#e9e9ec; --mut:#a0a0a8; --line:#33333a; --bg:#151518; --card:#1d1d22; }
  }
  * { box-sizing:border-box }
  body { margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--ink);
         font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }
  .wrap { max-width:720px; margin:0 auto }
  h1 { font-size:1.35rem; margin:0 0 .25rem; color:var(--navy) }
  @media (prefers-color-scheme: dark) { h1 { color:#8fa4e8 } }
  .sub { color:var(--mut); margin:0 0 1.75rem; font-size:.9rem }
  .card { border:1px solid var(--line); border-radius:10px; padding:1.1rem 1.25rem;
          margin-bottom:1rem; background:var(--card) }
  .status { border-left:4px solid var(--sc) }
  .ok   { --sc:#1a7f4b } .warn { --sc:#b06f00 } .bad { --sc:#b3261e }
  .big { font-size:1.1rem; font-weight:600; margin:0 0 .3rem }
  .ok .big{color:#1a7f4b} .warn .big{color:#b06f00} .bad .big{color:#b3261e}
  @media (prefers-color-scheme: dark) {
    .ok .big{color:#5dd39e} .warn .big{color:#e0a34a} .bad .big{color:#f2857c}
  }
  p { margin:.3rem 0 }
  .muted { color:var(--mut); font-size:.88rem }
  h2 { font-size:.78rem; text-transform:uppercase; letter-spacing:.07em;
       color:var(--mut); margin:0 0 .7rem; font-weight:600 }
  a { color:var(--navy) } @media (prefers-color-scheme: dark){ a{color:#8fa4e8} }
  .file { display:flex; justify-content:space-between; align-items:baseline; gap:1rem;
          padding:.55rem 0; border-bottom:1px solid var(--line) }
  .file:last-child { border-bottom:0 }
  .file .d { font-size:.82rem; color:var(--mut) }
  button { font:inherit; font-weight:600; padding:.65rem 1.15rem; border-radius:7px;
           border:1px solid var(--navy); background:var(--navy); color:#fff; cursor:pointer }
  button:disabled { opacity:.5; cursor:not-allowed }
  .note { background:#fff8e6; border:1px solid #f0dca8; color:#5c4700;
          padding:.7rem .9rem; border-radius:7px; font-size:.86rem; margin-top:.8rem }
  @media (prefers-color-scheme: dark){ .note{background:#2e2612;border-color:#5a4a1e;color:#e8d5a3} }
  .msg { padding:.7rem .9rem; border-radius:7px; font-size:.9rem; margin-bottom:1rem }
  .msg.good { background:#e7f5ed; color:#14512f } .msg.err { background:#fdecea; color:#7a1c16 }
  @media (prefers-color-scheme: dark){
    .msg.good{background:#12301f;color:#87ddb0} .msg.err{background:#381815;color:#f2a49c} }
  code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.85em }
</style></head><body><div class="wrap">

<h1>Power Price Data</h1>
<p class="sub">European hourly power prices — Germany, Spain, Portugal, France, Italy.
Data from the ENTSO-E Transparency Platform.</p>

${msg ? `<div class="msg good">${esc(msg)}</div>` : ""}
${err ? `<div class="msg err">${esc(err)}</div>` : ""}

<div class="card status ${tone}">
  <p class="big">${esc(headline)}</p>
  ${detail ? `<p>${detail}</p>` : ""}
  ${status?.generated_utc
      ? `<p class="muted">Last refreshed <strong>${esc(status.generated_utc)} UTC</strong>${
          status.coverage_end ? ` &middot; data through ${esc(status.coverage_end)}` : ""}</p>`
      : ""}
  ${runLine ? `<p class="muted">${runLine}</p>` : ""}
</div>

<div class="card">
  <h2>Next scheduled update</h2>
  <p><strong>${esc(nrTxt)}</strong> — in ${esc(human(nr - now))}</p>
  <p class="muted">Runs automatically every week. You do not need to do anything.</p>
</div>

<div class="card">
  <h2>Download the latest files</h2>
  ${files.map(([f, label, d]) => `
    <div class="file">
      <span><a href="${REPO_URL}/raw/${BRANCH}/deliverables/${f}">${esc(label)}</a>
        <div class="d">${esc(d)}</div></span>
    </div>`).join("")}
  <div class="note"><strong>When do I need to download?</strong> Only when the <em>chart itself</em>
  is wrong — a missing year, or a technology that should not be there. Day-to-day the numbers update
  by themselves: the workbook pulls them from here every time you open it. A refresh writes values
  into cells, so it can never add a new year or change what a chart plots.</div>
</div>

<div class="card">
  <h2>Look through the data</h2>
  <p class="muted">Every chart is fed by a published CSV — open one to see exactly what it plots.</p>
  <p><a href="${REPO_URL}/tree/${BRANCH}/published/charts" target="_blank" rel="noopener">Chart data (CSV)</a>
   &middot; <a href="${REPO_URL}/tree/${BRANCH}/published" target="_blank" rel="noopener">Full published data</a>
   &middot; <a href="${REPO_URL}" target="_blank" rel="noopener">Repository</a></p>
</div>

<div class="card">
  <h2>Refresh now</h2>
  <p class="muted">Fetches the latest ENTSO-E data and rebuilds everything. Takes about 20 minutes.
  You rarely need this — the weekly run covers it, and no chart gains a new data point in between.</p>
  ${hasToken
      ? `<form method="POST" action="/trigger" onsubmit="this.q.disabled=true;this.q.textContent='Starting…'">
           <button id="q" name="q" type="submit">Start a refresh</button>
         </form>`
      : `<p class="muted"><em>Not yet enabled — the access token has not been configured.</em></p>`}
</div>

<p class="muted" style="margin-top:2rem">
  Status read live from <code>published/charts/status.csv</code>.
  Nothing on this page is stored or tracked.</p>

</div></body></html>`;
}

/* ------------------------------------------------------------------ routing */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/trigger") {
      if (!env.GH_TOKEN) {
        return render(env, { err: "Refresh is not enabled: no access token configured." });
      }
      // Cross-origin POSTs are rejected: only this page may trigger a run.
      const origin = request.headers.get("Origin");
      if (origin && new URL(origin).host !== url.host) {
        return new Response("Forbidden", { status: 403 });
      }

      const run = await latestRun(env);
      if (run && run.status !== "completed") {
        return render(env, { err: "A refresh is already running — give it about 20 minutes." });
      }
      if (run?.updated_at) {
        const mins = (Date.now() - new Date(run.updated_at).getTime()) / 60000;
        if (mins < COOLDOWN_MIN) {
          return render(env, {
            err: `A refresh finished ${Math.round(mins)} minute${Math.round(mins) === 1 ? "" : "s"} ago. ` +
                 `Please wait ${Math.ceil(COOLDOWN_MIN - mins)} more before starting another.`,
          });
        }
      }

      const r = await fetch(
        `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${env.GH_TOKEN}`,
            Accept: "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "power-price-status-page",
          },
          body: JSON.stringify({ ref: BRANCH }),
        },
      );
      return r.status === 204
        ? render(env, { msg: "Refresh started. It takes about 20 minutes — reload this page to follow it." })
        : render(env, { err: `GitHub refused the request (HTTP ${r.status}).` });
    }

    if (url.pathname !== "/" && url.pathname !== "") {
      return Response.redirect(new URL("/", url).toString(), 302);
    }
    return render(env, {});
  },
};

async function render(env, extra) {
  const [status, run] = await Promise.all([getStatus(), latestRun(env)]);
  return new Response(
    page({ status, run, hasToken: Boolean(env.GH_TOKEN), ...extra }),
    { headers: { "content-type": "text/html;charset=utf-8", "cache-control": "no-store" } },
  );
}
