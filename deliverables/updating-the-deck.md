# Updating the Hourly Power Data deck

### A 2-minute guide — no technical skills needed

---

**The idea in one line:** the Excel file fetches the latest numbers from the internet by itself, and the PowerPoint simply mirrors the Excel file. You never edit data — you only press *refresh*.

The underlying data is refreshed automatically on the **2nd, 10th, 18th and 26th of every month**. So whenever you open the workbook, it pulls the most recent published data on its own — you don't touch anything online.

---

## Updating the deck — 4 steps (~2 minutes)

**1. Keep both files together.**
`HourlyPowerData.xlsx` and `HourlyPowerData.pptx` must sit in the **same team folder** (the agreed shared drive location). The PowerPoint finds the Excel by that exact location — so don't move or rename either file.

**2. Open the Excel workbook.**
It refreshes itself the moment it opens (it's set up that way). You'll see the charts redraw with the latest figures.
> If you ever want to force it: **Data ▸ Refresh All**.

Then **Save** and close it.

**3. Open the PowerPoint.**
It will ask whether to **update links** — click **Yes / Update**.
> If it doesn't ask: **File ▸ Info ▸ Edit Links to Files ▸ Update Now**.

The charts pull the latest versions from the Excel file.

**4. Save the PowerPoint.**
Done — the deck is current.

---

## Three things to know

- **Where "the latest data" comes from.** An automated job refreshes the source data on the 2nd, 10th, 18th and 26th of every month. Opening Excel gives you the data as of that most recent refresh. You never go online yourself.

- **Two slides are meant to stay fixed.** The two "Spain duck curve" comparison slides (quarterly, and July — each showing 2019 vs 2025) are deliberate historical snapshots. They do **not** change on refresh, and that's intentional.

- **Never type over the numbers.** If a chart ever looks wrong, the fix is always to **refresh again** — Excel first, then update the PowerPoint links — not to edit any cells by hand.

---

## If something looks off

| Symptom | Fix |
|---|---|
| A chart is blank or shows an error | Close both files, re-open the **Excel** file first (let it finish refreshing), save, then re-open the PowerPoint and update links. |
| PowerPoint says it *can't find* the linked file | The two files aren't in the same folder, or one was renamed. Put them back together with their original names. |
| Charts didn't change after refresh | Check your internet connection, then **Data ▸ Refresh All** in Excel and watch it re-pull. |
| A whole chart is missing | That chart's data connection may not be set up yet — flag it to the desk owner (a one-time fix). |

---

*Any questions, or if a step looks different on your machine, note down exactly what you see on screen and send it over — the setup can be adjusted.*
