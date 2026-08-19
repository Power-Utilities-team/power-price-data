# Auto-refresh (GitHub Actions) — operations & handover

This repo keeps the ENTSO-E power-price CSVs fresh automatically, so the Excel
workbook (set to *refresh-on-open*) is always current — a non-technical user
just opens the file. Nobody has to run anything.

## How it works
- `.github/workflows/refresh.yml` runs on a schedule (monthly, **2nd @ 07:23 UTC**)
  and on demand. It fetches ENTSO-E, rebuilds the summaries, and publishes CSVs
  to `published/` (served at stable raw URLs).
- The workbook's Power Query connections point at those URLs and refresh on open.

### The four jobs, and why they are in that order
`fetch` → `build` → `validate` → `publish`. Only the **last** one writes to the
repository, and that is the whole point: everything that can reject a build runs
first, so a bad package or a shrunken feed never reaches `main`.

| job | runner | what it does |
|---|---|---|
| `fetch` | ubuntu ×5 | one country each, in parallel; caches `data/raw` between runs |
| `build` | ubuntu | assembles, summarises, exports, rebuilds the workbook and decks. **Commits nothing** — it uploads everything as the `publish-payload` artifact |
| `validate` | windows | Microsoft's own Open XML SDK on all four deliverables. Free and unlimited on a public repo, and it catches the schema faults our hand-written checks do not |
| `publish` | ubuntu | asserts coverage has not shrunk, then commits and pushes |

Until 2026-07-31 the build job committed and `validate` ran afterwards, so an
invalid workbook landed in `deliverables/` and only then turned the run red.

### The coverage gate
`publish` runs `_tools/check_coverage.py` before it commits. Every other check asks
whether the data is *valid*; this asks whether it is the data we already had, **plus
more**. It compares each published feed against the previous commit on row count and
on populated cells per column, and fails the run on a large drop.

It exists because on 2026-07-31 a cold cache made the incremental fetch publish a
31-day "year" in place of 212 days. It shipped because the run was fast and green and
every validator passed — correctly, since a 31-day series is perfectly valid data. It
is just the wrong data.

**If it trips**, do not loosen the tolerance. Either the fetch lost data (re-run with
`full_refetch=true`), or the shrink is deliberate — a clipping fix, a chart
restructure — in which case commit that change yourself and push, since the gate only
runs in CI. `_tools/coverage_eyeball.py` draws the coverage so you can see which.

The same script also asserts that the month which has just closed actually **arrived** in
the monthly exhibits. That is a different failure from a shrink and the shrink check
cannot see it: if the month never appears, last month's feed ended in June and this
month's also ends in June, so nothing got smaller. It happens when coverage has not yet
passed the month's final hour at run time — the run then succeeds and silently omits the
month for a further month. This is why the schedule sits on the 2nd rather than the 1st;
see the reasoning block above the `cron:` line.

## Run it manually (anyone with repo access)
GitHub → **Actions** tab → *Refresh ENTSO-E power-price data* → **Run workflow**.
Takes ~10–15 min (it only re-fetches the current year; 2019–2025 history is
frozen in `data/processed/master_fixed.parquet`). When it finishes,
`published/*.csv` is updated; open the workbook and it pulls the new data.

## Once a year (fold the completed year into the frozen history)
In January, after a year finishes, re-freeze so it stops being re-fetched:
```
cd _tools && python fetch.py && python build_hourly.py --full
```
then commit the updated `data/processed/master_fixed.parquet` +
`capacity_fixed.parquet`. (Optional — skipping it just means the just-ended year
keeps being re-fetched live, which still works, only slightly slower.)

## The API key
Stored as the encrypted repo **Secret** `ENTSOE_API_KEY` (Settings → Secrets and
variables → Actions). It is never in the code. Get a free key at
https://transparency.entsoe.eu/ (register → request API access).

## Handover to a colleague / your company
1. **Give them access** — add them as a collaborator (Settings → Collaborators),
   or **transfer** the repo into your company's GitHub Organization
   (Settings → General → Transfer ownership).
2. **Swap the API key** — the successor creates their own ENTSO-E key and updates
   the `ENTSOE_API_KEY` Secret. (Do this if the original key owner leaves.)
3. **If the repo path changed** (e.g. personal → org), update the CSV URLs in the
   workbook once: Data → Queries & Connections → edit each query's source URL to
   the new `raw.githubusercontent.com/<owner>/<repo>/main/published/<name>.csv`.
   Keeping the repo in a stable org avoids this entirely.
4. **Re-issue the status page's Refresh token** — the one other account-specific
   piece (see the next section). The pipeline, schedule and docs otherwise travel
   with the repo.

## Moving to an organisation, and handing the whole thing over (planned 2026-08-17)

Two asks the same day: get the repo off Fred's personal account, and make the pipeline something a
successor could take on if he left the team. **They pull in the same direction, and the second one
is the stronger reason.** An organisation hands over by adding an owner and removing yourself: no
transfer, no URL change, no re-minted anything for the successor.

### The correction that came out of it

An earlier suggestion here was to make the repo PRIVATE and point the workbook's data connections at
the Cloudflare Worker, since the Worker holds a token. **For handover that is the wrong way round**
and it is withdrawn. The Worker lives in Fred's personal Cloudflare account and answers on
`power-price-data.fredhill.workers.dev`. Pointing the workbook at it would make the pipeline depend
on the one asset that is hardest to hand on, and would bake his name into the workbook's own URLs.

So: **public repo under a neutral org, workbook pointing at the org's raw URLs, and the status page
stays a convenience rather than a dependency.** Anyone can rebuild the page; nobody can rebuild a
workbook whose connections point at a Worker they cannot administer.

### Leaving for good: the three things that must be true

Sharper version of the ask (Fred, 2026-08-17): it must not matter if he leaves permanently, with the
team holding **no access to his accounts and no ability to ask him anything**. The test is
falsifiable, so use it: *given only the repo URL, can a colleague keep the data refreshing?*

Most of the pipeline already passes. Three things do not.

1. **The org needs a second owner who is not Fred.** An organisation he creates and solely owns is
   still a personal dependency wearing a different name. Either a colleague is made an org owner, or
   the repo lives in the employer's own GitHub org. Until that is true, nothing else on this list
   matters.
2. **The ENTSO-E API key: Fred decided 2026-08-17 to LEAVE IT AS HIS.** Do not reopen this as a
   security question, because it was examined and it is not one. That key reads public European
   market data, anyone can register for one free in minutes, and it is not reusable anywhere else,
   so a stolen copy grants nothing that was not already public. The only harm available is a
   throttled or suspended account, which breaks the refresh and attributes traffic to him. His
   judgement was that this is an ownership tie rather than a risk, and an acceptable one, given the
   recovery block now tells a successor how to replace the key without him. The paragraph below
   records the argument he weighed, not an outstanding action.
   **The residual single point of failure** It is the one credential the
   scheduled refresh cannot run without, and it belongs to whoever registered at the ENTSO-E
   Transparency Platform. If that is Fred's personal registration and the account goes, every future
   run fails. The fix is cheap and should happen before any of the GitHub work: register the key
   under a **team mailbox**, then replace the `ENTSOE_API_KEY` Actions secret with it. The re-key
   procedure is already written below, under the heading that anticipated exactly this.
3. **The status page must not become load-bearing.** It runs on Fred's personal Cloudflare account.
   Treat it as a convenience: a successor can redeploy it from `_tools/refresh-page/` under their own
   account, and if nobody ever does, the pipeline is unaffected. This is why the workbook must read
   GitHub and not the Worker.

What already passes the test, and needs nothing: the scheduled refresh runs on Actions with free
minutes for a public repo; failure alerts open a **GitHub issue** rather than emailing a person,
which was a deliberate 2026-08-03 choice; and the eight root docs are in the repo and written for a
non-technical reader.

What is left after those three: only the manual Refresh button, which needs a PAT. If nobody mints
one, the button says so on the page and the schedule carries on regardless.

### What each asset costs to hand over

| Asset | Owner today | Handover |
|---|---|---|
| Repo, published data, Actions | `fredhill123`, personal | Under an org: add the successor as an owner, remove yourself. Nothing else moves |
| `GH_TOKEN` (Refresh button, status line, downloads) | a fine-grained PAT on Fred's account | Successor mints their own and runs `wrangler secret put GH_TOKEN`. Rotation runbook is below |
| The status-page Worker | **Fred's personal Cloudflare account** | The weak link. A successor redeploys it under their own account from `_tools/refresh-page/`, which changes the page's hostname. Nothing in the pipeline breaks when they do |
| Workbook and deck | ordinary files | Fine, as long as their URLs name the ORG and not a person |
| The four docs a successor reads | in the repo | Already written for a non-technical reader |

### DONE 2026-08-17. The repo now lives at `Power-Utilities-team/power-price-data`

Transferred through the API during a GitHub partial outage, which took three attempts and landed
asynchronously. Then `_tools/retarget_owner.py Power-Utilities-team --apply`, 16 changes across 11
files, and the Worker redeployed. Verified after: the page reads "Data is current", the last-run line
says success, all three downloads return a real file, and the old raw URLs still redirect, so nothing
anyone bookmarked 404s.

⚠ **CORRECTION: the fine-grained PAT did NOT stop working.** This section warned twice that it would,
because it was scoped to the old owner. That was wrong, and the reason is worth keeping: a
fine-grained PAT stores its repository selection by repo **ID**, and a transfer does not change the
ID, so the token followed the repo. No new token was needed and nothing degraded.

What briefly looked like the predicted failure was the outage. The first check after the redeploy
showed an empty last-run line, because the Actions API was returning 503, and it recovered on its own.

**Verified after the outage lifted enough to allow it:** `ENTSOE_API_KEY` is present on the
transferred repo, created 2026-07-17 and untouched, so the secret travelled. The workflow is
`state=active`, Actions are enabled, Issues are enabled so the notify job can still open one, and the
three most recent runs all succeeded (all pre-transfer).

⚠ **One thing inspection cannot settle, and it is the push.** The transferred repo's
`default_workflow_permissions` reads **`read`**, while the publish job pushes commits with
`GITHUB_TOKEN`, which needs write. It most likely does not matter, because the workflow declares its
own `permissions: contents: write` at the top level and `issues: write` on the notify job, and a
workflow-level block grants those scopes even where the repo default is restricted. Not established:
the ORG-level setting, which needs org admin rights the local `gh` token does not have, and what the
default was before the transfer, so it is unknown whether this changed.

**The check, after the first scheduled run following 2026-08-17** (Fred chose to wait for the real
scheduled path rather than trigger one):

    gh api "/repos/Power-Utilities-team/power-price-data/actions/workflows/refresh.yml/runs?per_page=1" \
      --jq '.workflow_runs[0] | "\(.created_at) \(.status)/\(.conclusion)"'

A `success` on a run dated after the transfer proves the whole chain, secret and push included. A
failure at the publish step means the read-only default did govern: fix it with
`gh api -X PUT /repos/Power-Utilities-team/power-price-data/actions/permissions/workflow -f default_workflow_permissions=write`
and re-run. The failure is not silent either way: the notify job opens an issue, and the page's own
status line goes stale and brings up the recovery block.

### The sequence, kept for next time and for a later move into the employer's own org

1. Create the org, free: **github.com/organizations/plan**. Pick a name with no person in it, since
   it becomes the public URL and the successor inherits it.
2. Org → **People** → set your own membership visibility to **private**.
3. Org → Settings → **Personal access tokens** → allow fine-grained tokens, or the new PAT cannot
   be approved for the org's repos.
4. Repo → Settings → Danger Zone → **Transfer ownership** → to the org.
5. Mint a NEW fine-grained PAT with the **org** as resource owner, Actions: write, that repo only.
   Then `cd "Power Price Data/_tools/refresh-page" && npx wrangler secret put GH_TOKEN`.
6. Run the script prepared for this, which handles all **16 references across 11 files** including
   `OWNER` in `worker.js`. Dry run first, and it prints every line it would change:

       ~/.claude/pyenv/bin/python3 "Power Price Data/_tools/retarget_owner.py" <new-owner>
       ~/.claude/pyenv/bin/python3 "Power Price Data/_tools/retarget_owner.py" <new-owner> --apply

   It rewrites only `<old>/power-price-data` and the Worker's constant, never the bare username,
   which also appears in `fredhill123/flat-hunt` and the vault's own git remote. It re-scans rather
   than trusting a file list, and says so when it finds a reference the list did not predict.
7. **The workbook's own Power Query connections still hold the old URL**, inside the xlsx. GitHub
   redirects transferred repo URLs, and raw generally follows, but a live model should not depend on
   a redirect: update `BASE` in the workbook. It is Fred's hand-edited file, so he changes it or
   explicitly asks for it to be rewritten.
8. Verify: the page's status line reads a date rather than "Could not read the status record", all
   three downloads return a real file, and the workbook refreshes.

### The page tells a successor what to do (2026-08-17)

Fred asked for a replacement ENTSO-E key to be suppliable **through** the public page, which would
also have regenerated the workbook. Two corrections came out of that, and the second one is the
reason it was built differently:

- **There is no key in the workbook.** Its Power Query connections read the already-published CSVs.
  Nothing it does ever calls the Transparency Platform, so swapping the key needs no new workbook and
  breaks nothing anyone has downloaded.
- **A form on that page would be worse than the fault it fixes.** The page is public and
  unauthenticated, so anyone could point the pipeline at their own ENTSO-E account or break it at
  will. And writing an Actions secret needs a far broader token than the Actions:write one the Worker
  holds, so the page would end up holding a credential that can rewrite repository secrets.

**What it does instead:** when the last run has failed, or the data is past its tolerance, the page
shows a recovery block. It names the likely cause, says the key belongs to whoever registered for
one, and gives three steps: register at the Transparency Platform with a **team mailbox**, set
`ENTSOE_API_KEY` in Settings → Secrets and variables → Actions, then press Start a refresh. It names
no GitHub URL and collects nothing. `page_test.mjs` asserts both halves: the block appears on a
failed run, and it contains no input field.

A healthy page says none of this, which is checked too.

### What the org does NOT fix

The public commit history keeps `Fred Hill <fred.hill@rothschildandco.com>` on every commit he made, because
a transfer does not rewrite commits. If that matters, the separate fix is a
`@users.noreply.github.com` address for future commits, and a history rewrite for the old ones,
which on a public repo is its own decision.

## The status page names GitHub nowhere (2026-08-17)

Fred's ask: "remove any links that would show my github profile". The page used to carry four
download links, three browse links and a run-log link, all `github.com/<account>/...`, from which
the profile is one click away. Now:

- **Downloads are proxied.** `GET /file/<name>` on the Worker streams the file from its own
  hostname, authenticated through `GH_TOKEN` (the contents endpoint with the raw media type, which
  handles files past 1MB), falling back to raw if the secret is absent. An **allowlist of exact
  filenames**, not a path check, because a path check on a proxy is how a proxy becomes a way to
  read the rest of the repo.
- **Three files, not four.** Live Excel, linked PowerPoint, self-contained Excel. The snapshot deck
  and the whole "Look through the data" CSV card were dropped as clutter, Fred's pick.
- **Gone:** the Repository link, both browse links, and "view log". The run's conclusion still
  shows, since that is the actionable part.
- `GH_TOKEN` now also fixes the status line: it used to be read unauthenticated from raw, which
  Cloudflare's shared egress addresses get rate-limited on, and the page intermittently said
  "Could not read the status record". That is what Fred saw on 2026-08-17.
- Guarded by `node "Power Price Data/_tools/refresh-page/page_test.mjs"`, 24 assertions. The
  load-bearing one: the rendered HTML contains no `github.com`, `githubusercontent`, or account
  name, and every link on the page is same-origin.

What this does NOT hide: the live workbook fetches its own data from `raw.githubusercontent.com`,
so those URLs are visible in its connection settings to anyone who opens it and looks. That is the
workbook's design, not the page's.

## The status page's Refresh button token (GH_TOKEN) — what it is and how to rotate it

The public status page's Refresh button is the only self-service recovery lever a
non-technical successor has. It works through a Cloudflare Worker
(`power-price-data`, source in `_tools/refresh-page/`) that dispatches the GitHub
Actions workflow. The Worker authenticates with `GH_TOKEN`: a **fine-grained GitHub
PAT, Actions:write on this one repo only**, stored as an encrypted Worker secret.
Current token expires **15 July 2027** (read off the GitHub settings page
2026-08-03). Nothing warns when it lapses — the page silently degrades to
"Refresh is not enabled: no access token configured".

Rotation, in full (the token value never goes through chat, email or a file —
it exists only in the GitHub page that mints it and the terminal prompt that
stores it):

1. Sign in to GitHub as the repo owner →
   https://github.com/settings/personal-access-tokens → **Generate new token**.
2. Fine-grained. Resource owner: the account/org holding the repo. Repository
   access: **Only select repositories** → `power-price-data`. Permissions:
   **Actions: Read and write** — nothing else. Expiry: the maximum on offer
   (366 days), and diary the date; GitHub exposes it nowhere else. Also update the
   `EXPIRY` constant in `~/.claude/tools/check-status.py` (`check_github_token`) —
   that is the session-start warning that fires 45 days out, independent of email.
3. Copy the token from that page (this is the only time GitHub shows it).
4. In a terminal: `cd "Power Price Data/_tools/refresh-page" && wrangler secret put GH_TOKEN`
   — paste the token at the interactive prompt. It uploads encrypted; no deploy
   is needed and the Worker picks it up immediately.
5. Verify: open the status page, confirm the Refresh button renders (not the
   "no access token configured" fallback), press it, and check a run appears
   under the repo's Actions tab.
6. Revoke the old token on the same GitHub settings page if it has not expired.

## Change the refresh cadence
Edit the `cron:` line in `.github/workflows/refresh.yml` (uses standard cron, UTC).

## If a run fails
Open the failed run under **Actions** to see logs. Most failures are transient
ENTSO-E 503s — just re-run. The workflow already does a second fetch pass to fill
any gaps; a re-run fills the rest.
