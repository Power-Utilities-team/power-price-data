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

const OWNER = "Power-Utilities-team";
const REPO = "power-price-data";
const WORKFLOW = "refresh.yml";
const BRANCH = "main";

const RAW = `https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}`;
// REPO_URL is gone (2026-08-17, Fred: "remove any links that would show my github profile"). The
// page used to carry four download links, three browse links and a run-log link, every one of them
// a github.com URL containing the account name, from which the profile is one click away. Nothing
// on the page now names GitHub at all: downloads are proxied by this Worker, over its own hostname,
// and the browse and repository links are simply gone.
//
// What this does NOT hide, and cannot from here: the live workbook fetches its own data from
// raw.githubusercontent.com, so those URLs are visible in its connection settings to anyone who
// opens it and looks. That is the workbook's design, not this page's.

// The ONLY files this Worker will serve, by exact name. An allowlist rather than a path check,
// because a path check on a proxy is how a proxy becomes a way to read the rest of a repository.
// Three of them, Fred's pick 2026-08-17: the snapshot deck and the CSV browse card were dropped as
// clutter, keeping the two anyone actually opens plus the deck that goes with them.
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
const DOWNLOADS = {
  "HourlyPowerData.xlsx": {
    label: "Excel workbook (live)", type: XLSX,
    note: "Refreshes itself when you open it.",
  },
  "HourlyPowerData.pptx": {
    label: "PowerPoint (linked)", type: PPTX,
    note: "Charts link to the workbook — keep the two together.",
  },
  "HourlyPowerData_frozen.xlsx": {
    label: "Excel (self-contained)", type: XLSX,
    note: "No connections; opens anywhere.",
  },
};

// Matches the workflow's cron: "23 7 2,10,18,26 * *" — 07:23 UTC on the 2nd, 10th, 18th
// and 26th of every month.
//
// ⚠ This was wrong from 2026-08-01 to 2026-08-03 and nobody noticed, which is the whole
// argument for keeping it in one obvious place. The schedule moved from the 3rd to the
// 2nd and this constant stayed on the 3rd, so the page confidently advertised a run that
// did not exist. If you change the workflow cron, change it HERE too — this file cannot
// see the workflow, and a wrong answer here is worse than no answer, because the reader
// has no way to tell it is wrong.
const CRON = { days: [2, 10, 18, 26], hour: 7, minute: 23 };
const COOLDOWN_MIN = 30;

const NAVY = "#2E3E80";

/* ------------------------------------------------------------------ helpers */

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function nextRun(now = new Date()) {
  const t = now.getTime();
  // Try each scheduled day in this month, then in the next — the first that is still in
  // the future wins. Two months is always enough, because the run dates repeat every
  // month, so the answer can never be further away than the 2nd of next month.
  //
  // Date.UTC normalises an overflowing month index for us (month 12 rolls into January
  // of the next year), so the year boundary needs no special case.
  for (const m of [now.getUTCMonth(), now.getUTCMonth() + 1]) {
    for (const d of CRON.days) {
      const cand = Date.UTC(now.getUTCFullYear(), m, d, CRON.hour, CRON.minute, 0);
      if (cand > t) return new Date(cand);
    }
  }
  return null;   // unreachable
}

function human(ms) {
  const d = Math.floor(ms / 86400000);
  const h = Math.floor((ms % 86400000) / 3600000);
  if (d > 0) return `${d} day${d === 1 ? "" : "s"}${h ? `, ${h}h` : ""}`;
  const m = Math.floor((ms % 3600000) / 60000);
  return h > 0 ? `${h}h ${m}m` : `${m} minute${m === 1 ? "" : "s"}`;
}

// Two ways to the same file, authenticated first (fixed 2026-08-17, Fred saw the page saying
// "Could not read the status record").
//
// The cause was NOT the repo or the file: both were fine, and the fetch below returned the row
// correctly on a retry seconds later. It was HTTP 429 from raw.githubusercontent.com. A Worker's
// outbound requests leave from Cloudflare's shared egress addresses, and GitHub rate-limits
// unauthenticated raw traffic per address, so this page was being throttled by strangers' usage
// rather than by anything Fred does. A short cacheTtl made it worse by refetching every minute.
//
// The API route carries GH_TOKEN, which this Worker already holds for the workflow dispatch, and
// an authenticated limit is tied to the token rather than the address. Raw stays as the fallback
// for the case where the secret is absent.
async function getStatus(env) {
  const parse = (text) => {
    const [head, row] = text.trim().split("\n");
    if (!row) return null;
    const keys = head.split(",");
    const vals = row.split(",");
    return Object.fromEntries(keys.map((k, i) => [k.trim(), (vals[i] || "").trim()]));
  };

  if (env && env.GH_TOKEN) {
    try {
      const r = await fetch(
        `https://api.github.com/repos/${OWNER}/${REPO}/contents/published/charts/status.csv?ref=${BRANCH}`,
        {
          cf: { cacheTtl: 300 },
          headers: {
            "User-Agent": "power-price-status-page",
            Accept: "application/vnd.github.raw",
            Authorization: `Bearer ${env.GH_TOKEN}`,
          },
        },
      );
      if (r.ok) {
        const got = parse(await r.text());
        if (got) return got;
      }
    } catch (e) {
      // fall through to raw
    }
  }

  const r = await fetch(`${RAW}/published/charts/status.csv`, {
    cf: { cacheTtl: 300 },
    headers: { "User-Agent": "power-price-status-page" },
  });
  if (!r.ok) return null;
  return parse(await r.text());
}

/* The health record, published beside status.csv since 2026-08-23.
 *
 * status.csv can only say HOW OLD the data is. That was enough to notice the August outage
 * — the page correctly read stale from the 20th — and useless for doing anything about it,
 * because the reason (ENTSO-E answering 504 for one German series) lived in a run log. This
 * file carries the reason, and a run that published from the fallback store says so too.
 *
 * Absent is not an error: a repo that has never failed has no record, which reads as fine.
 */
async function getHealth() {
  try {
    const r = await fetch(`${RAW}/published/charts/health.json`, {
      cf: { cacheTtl: 300 },
      headers: { "User-Agent": "power-price-status-page" },
    });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  }
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

function page({ status, run, health, msg, err, hasToken, tokenWorks }) {
  const now = new Date();

  let gen = null;
  let ageDays = null;
  if (status?.generated_utc) {
    gen = new Date(status.generated_utc.replace(" ", "T") + "Z");
    if (!isNaN(gen)) ageDays = (now - gen) / 86400000;
  }

  const limit = Number(status?.expected_refresh_days || 10);
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
  } else if (health?.state === "failed") {
    // A FAILURE IS NEWS ON THE DAY IT HAPPENS, not ten days later (found by a drill,
    // 2026-08-23). The first version of this only named the cause inside the `stale`
    // branch, so a run that failed this morning left the page reading "Data is current"
    // and silent — the reader would not learn anything until the age tolerance expired,
    // which is the whole delay this was written to remove. Age and health are independent:
    // the data can be fine AND the pipeline broken, and that is the interesting hour.
    tone = stale ? "bad" : "warn";
    headline = stale
      ? `Data is ${Math.floor(ageDays)} days old`
      : "The last refresh failed";
    detail = health.reason
      ? `Cause recorded by the last run: ${esc(health.reason)}.`
      : "The last run did not complete; see the repository's Actions log.";
    detail += stale
      ? ` Nothing has published for longer than the ${limit}-day tolerance.`
      : " The figures on this page are still current. A repair run retries the missing"
        + " series within hours, and the next scheduled run re-pulls the whole year.";
  } else if (stale) {
    tone = "bad";
    headline = `Data is ${Math.floor(ageDays)} days old`;
    detail = `The scheduled refresh has not run for longer than the ${limit}-day tolerance.`;
  } else if (health?.state === "ok-on-stored-data" && health.reason) {
    // A run CAN succeed having leaned on the fallback store for one series. Everything on
    // the page is otherwise fresh, so this is a note rather than an alarm — but a number
    // that is quietly older than it looks is exactly what the bound exists to declare.
    tone = "warn";
    headline = "Published, with one series from stored data";
    detail = `${esc(health.reason)}. Every other series is current; the next full re-pull replaces it.`;
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

  // No "view log" link any more: run.html_url is a github.com Actions URL and so carries the
  // account name. The conclusion is the part a reader can act on, and that stays.
  const runLine = run
    ? `Last run <strong>${esc(run.status === "completed" ? run.conclusion : run.status)}</strong>`
    : "";

  const files = Object.entries(DOWNLOADS).map(([f, d]) => [f, d.label, d.note]);

  // Recovery instructions, shown only when something is actually wrong (Fred, 2026-08-17).
  //
  // He asked for a way to supply a replacement ENTSO-E key THROUGH this page. That was declined and
  // this is the agreed alternative. Two reasons the form would have been worse than the fault:
  // this page is public and unauthenticated, so anyone could point the pipeline at their own
  // ENTSO-E account or simply break it; and writing an Actions secret needs a far broader token
  // than the Actions:write one here, so the page would end up holding a credential that can rewrite
  // repository secrets. A page that TELLS you what to do needs no credential and no trust.
  //
  // The trigger is deliberately conservative: a failed run, or data past its tolerance. Either can
  // have other causes, so the wording says "most likely" rather than diagnosing. It names no
  // GitHub URL, per the same day's ask.
  const runFailed = run && run.status === "completed" && run.conclusion !== "success";
  const needsHelp = runFailed || stale;
  const recover = needsHelp ? `
<div class="card" style="border-left:4px solid #b3261e">
  <h2>If the refresh keeps failing</h2>
  <p>The most likely cause is the <strong>data-source key</strong>. The pipeline reads prices from
  the ENTSO-E Transparency Platform with a key that belongs to whoever registered for one, and a key
  stops working if that account is closed or the key is withdrawn. Nothing else here needs replacing,
  and no file anyone has downloaded is affected.</p>
  <p class="muted">Whoever looks after this needs repository access. They do not need the person who
  set it up.</p>
  <ol>
    <li>Register at the ENTSO-E Transparency Platform and request an API key. Use a
        <strong>team mailbox</strong> rather than a personal address, so the next handover needs
        nothing.</li>
    <li>In the repository, open <strong>Settings → Secrets and variables → Actions</strong> and set
        <code>ENTSOE_API_KEY</code> to the new key.</li>
    <li>Come back here and press <strong>Start a refresh</strong>. A run takes about 20 minutes.</li>
  </ol>
  <p class="muted">The repository's own <code>GITHUB.md</code> carries the same steps in full, plus
  what to do if the refresh button itself has stopped working.</p>
</div>` : "";

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
${recover}
<div class="card">
  <h2>Next scheduled update</h2>
  <p><strong>${esc(nrTxt)}</strong> — in ${esc(human(nr - now))}</p>
  <p class="muted">Runs automatically on the 2nd, 10th, 18th and 26th of every month. You do not need to do anything.</p>
</div>

<div class="card">
  <h2>Download the latest files</h2>
  ${files.map(([f, label, d]) => `
    <div class="file">
      <span><a href="/file/${encodeURIComponent(f)}">${esc(label)}</a>
        <div class="d">${esc(d)}</div></span>
    </div>`).join("")}
  <div class="note"><strong>When do I need to download?</strong> Only when the <em>chart itself</em>
  is wrong — a missing year, or a technology that should not be there. Day-to-day the numbers update
  by themselves: the workbook pulls them from here every time you open it. A refresh writes values
  into cells, so it can never add a new year or change what a chart plots.</div>
</div>

<div class="card">
  <h2>Refresh now</h2>
  <p class="muted">Fetches the latest ENTSO-E data and rebuilds everything. Takes about 20 minutes.
  You rarely need this — the scheduled runs cover it, and no chart gains a new data point in between.</p>
  ${!hasToken
      ? `<p class="muted"><em>Not yet enabled — the access token has not been configured.</em></p>`
      : !tokenWorks
      ? `<p class="muted"><em>Temporarily unavailable — the access token cannot currently read this
           repository, so a refresh would fail. The scheduled runs are unaffected. Whoever looks
           after this needs to issue a new fine-grained token (Actions: write, this repository) and
           set it as the Worker's <code>GH_TOKEN</code>. The most common cause is the repository
           having moved to a different owner, which leaves an old token scoped to the previous
           one.</em></p>`
      : `<form method="POST" action="/trigger" onsubmit="this.q.disabled=true;this.q.textContent='Starting…'">
           <button id="q" name="q" type="submit">Start a refresh</button>
         </form>`}
</div>

<p class="muted" style="margin-top:2rem">
  Status read live from <code>published/charts/status.csv</code>.
  Nothing on this page is stored or tracked.</p>

</div></body></html>`;
}

/* ------------------------------------------------------------------ routing */

// Serve one of the allowlisted deliverables from this Worker's own hostname, so the reader never
// sees a GitHub URL. Authenticated API first: the contents endpoint with the raw media type handles
// files well past 1MB, and an authenticated limit is tied to the token rather than to Cloudflare's
// shared egress addresses, which is what produced the 429s that broke the status line. Raw is the
// fallback for a missing secret.
async function serveFile(env, name) {
  const meta = DOWNLOADS[name];
  if (!meta) return new Response("Not found", { status: 404 });

  const headers = {
    "content-type": meta.type,
    // A colleague clicking the link should get a file, not a browser trying to render a zip.
    "content-disposition": `attachment; filename="${name}"`,
    "cache-control": "no-store",
    "x-robots-tag": "noindex, nofollow",
  };

  if (env.GH_TOKEN) {
    const r = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/contents/deliverables/${encodeURIComponent(name)}?ref=${BRANCH}`,
      { headers: { "User-Agent": "power-price-status-page", Accept: "application/vnd.github.raw",
                   Authorization: `Bearer ${env.GH_TOKEN}` } },
    );
    if (r.ok) return new Response(r.body, { headers });
  }

  const r = await fetch(`${RAW}/deliverables/${encodeURIComponent(name)}`,
                        { headers: { "User-Agent": "power-price-status-page" } });
  if (!r.ok) {
    return new Response("That file could not be fetched just now. Try again in a minute.",
                        { status: 502, headers: { "content-type": "text/plain; charset=utf-8" } });
  }
  return new Response(r.body, { headers });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/file/")) {
      if (request.method !== "GET" && request.method !== "HEAD") {
        return new Response("Method not allowed", { status: 405 });
      }
      // decodeURIComponent on the segment, and the allowlist does the rest. No path is ever built
      // from what arrives here beyond an exact key match, so "../" and friends have nowhere to go.
      let name;
      try {
        name = decodeURIComponent(url.pathname.slice("/file/".length));
      } catch (e) {
        return new Response("Not found", { status: 404 });
      }
      return serveFile(env, name);
    }

    if (request.method === "POST" && url.pathname === "/trigger") {
      if (!env.GH_TOKEN) {
        return render(env, { err: "Refresh is not enabled: no access token configured." });
      }
      // Cross-origin POSTs are rejected: only this page may trigger a run.
      //
      // KNOWN AND ACCEPTED, Fred's call 2026-08-17 ("leave it"), so do not "fix" this unasked.
      // The check passes when the header is ABSENT, which a browser always sends and a scripted
      // caller need not, so anyone who knows this URL can fire the workflow. What that costs is
      // Actions minutes on Power-Utilities-team/power-price-data and a refresh nobody asked for, bounded by
      // the cooldown and the already-running check below. What it does not cost is data: this
      // endpoint returns the same public page either way and the Worker holds nothing private.
      // The offered fix was a strict Origin plus a same-site form token; raise it again only if the
      // cost changes, not as tidying.
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
  const [status, run, health] = await Promise.all([getStatus(env), latestRun(env), getHealth()]);
  // A token can be PRESENT and not work. That is exactly what happened on 2026-08-17 when the repo
  // moved to an organisation: the fine-grained PAT was scoped to the old owner, so it stopped
  // covering the repo, and the Refresh button still rendered as though it would work. The page could
  // read its status the whole time, because that falls back to unauthenticated raw, so nothing
  // looked wrong. Distinguish the two states rather than leaving a button that fails on click.
  return new Response(
    page({ status, run, health, hasToken: Boolean(env.GH_TOKEN),
           tokenWorks: Boolean(env.GH_TOKEN) && run !== null, ...extra }),
    { headers: { "content-type": "text/html;charset=utf-8", "cache-control": "no-store" } },
  );
}
