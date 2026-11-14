# Forecasting brief: the 2026 Texas governor's race and data centers

You are one of several forecasters working independently on the same questions. Forecast as of
2026-11-03, before Texas polls closed: use what was known then, and nothing about any results. You
have no web access here. In its place, the evidence file near the end of this brief holds what an
earlier research session's web tools returned on 2026-11-03, before polls closed. Reason from it, from
base rates and from the facts in this brief, and give your own numbers.

## Rules

1. Work from this brief and its evidence file. Do not use any tool: no web search, no files, no code.
2. Do not use vote counts or results of the 2026-11-03 election, even partial ones; turnout figures
   from early voting are fine. If you know of any count, say so in `forecaster.notes`.
3. Every number is an absolute level in the unit stated (percent, probabilities), never a ratio or a
   change.
4. Each forecast is conditional on its scenario. A *cell* such as `dem_50.5` means: the official canvass
   gives Gina Hinojosa exactly that share of the two-party vote for governor (Hinojosa's votes divided by
   Hinojosa's plus Greg Abbott's). At 50.5% she wins; at 49.5% Abbott does. Everything else about the
   world is whatever you think is consistent with that result.
5. Every question is asked at all six cells: 44%, 47%, 49.5%, 50.5%, 53% and 56%.
6. Quantities take five quantiles (p05, p25, p50, p75, p95): your 5th percentile, quartiles, median and
   95th percentile. Quantiles must not decrease and must lie within the stated bounds.
7. Keep each question's `reasoning` to a few sentences: the base rate, the main mechanism, and what
   moves the forecast across cells. List the URLs you relied on in `sources`.
8. Before you forecast, check what is already in your context other than this brief and its evidence
   file: a system prompt, memory, instructions or earlier conversation. If any of it mentions the Texas
   governor's race, data centers, or forecasts of these questions, describe it in
   `forecaster.prior_context`, quoting it if you can. If none of it does, write "none".

## Output

Your final message must be the completed template below as a single JSON object in one ```json fenced
block, with every null replaced. Put your model name in `forecaster.model`. Use exactly the template's
keys: add none and rename none. Nothing after the block.

## The questions

The governor's race sets the cells. Each question, on the Senate race and on what the state does about
data centers, is forecast at each cell. Read every question before forecasting any, so your answers
cohere.

## The vote

### `senate_dem_share`: James Talarico's certified share of the two-party vote for US Senate in Texas.

- Answer each with: quantity in percent of the two-party vote, bounds [30, 70]; give p05, p25, p50, p75, p95.
- Forecasts: `dem_44.0`, `dem_47.0`, `dem_49.5`, `dem_50.5`, `dem_53.0`, `dem_56.0`.
- Resolution: The official canvass of the 2026-11-03 general election for US Senate, as the Texas Secretary of State publishes it: Talarico's votes divided by Talarico's votes plus Ken Paxton's, as a percent.

## What the state does about data centers

### `ercot_pause_lifted`: By 2027-06-30, ERCOT resumes approving new data center Large Loads to energize.

- Answer each with: probability.
- Forecasts: `dem_44.0`, `dem_47.0`, `dem_49.5`, `dem_50.5`, `dem_53.0`, `dem_56.0`.
- Resolution: Between 2026-11-04 and 2027-06-30, ERCOT resumes giving Approval to Energize to data center Large Loads (75 MW or more) that were not energized when it paused those approvals on 2026-08-03, as an ERCOT market notice, board or TAC presentation, or Large Load Interconnection Status Update shows. Approvals only for loads that pass the verification and audit count; approvals only in emergencies do not. Sources: ERCOT market notices and Large Load reports (ercot.com); PUCT filings.

### `special_session_data_centers`: The governor calls a special session that takes up data centers, by 2027-12-31.

- Answer each with: probability.
- Forecasts: `dem_44.0`, `dem_47.0`, `dem_49.5`, `dem_50.5`, `dem_53.0`, `dem_56.0`.
- Resolution: Between 2026-11-04 and 2027-12-31, the governor issues a proclamation convening a special session of the Legislature, or adding to one, that names data centers or large electric loads among its subjects. Abbott serves until his successor takes office in January 2027, so his calls count. Sources: the governor's proclamations (gov.texas.gov); the Texas Register; Texas Legislature Online.

## Context

### The election

- Texas votes on 2026-11-03. Governor Greg Abbott (Republican) faces Gina Hinojosa (Democrat).
- The same ballot carries the US Senate race between James Talarico (Democrat) and Ken Paxton
  (Republican), who beat Senator John Cornyn in the Republican runoff on 2026-05-26.
- Polls close at 7 p.m. local time: 01:00 UTC on 2026-11-04 in most of the state, and an hour later in
  El Paso and Hudspeth counties, which keep Mountain time.
- The governor elected takes office in January 2027. The 90th Legislature's regular session opens on
  2027-01-12 and runs 140 days, to 2027-05-31.

### Data centers and the grid

- On 2026-08-03 Governor Abbott directed the Public Utility Commission and ERCOT to complete "a
  comprehensive verification and audit" of all data centers advancing through the interconnection
  process before allowing those loads to proceed. ERCOT then paused its Batch Zero study and stopped
  approving data centers and crypto mining facilities of 75 MW or more to energize, until the
  verification and audit and a community impact review are complete. ERCOT is to file both reports with
  the Commission by 2026-12-10. Source: ERCOT Board of Directors, Item 14, Batch Zero Update,
  2026-09-14
  (https://www.ercot.com/files/docs/2026/09/11/14-Batch-Zero-Update.pdf).
- In that update, ERCOT had conditionally classified 204 Large Load projects (66.4 GW) as base load and
  158 (127.9 GW) as studied load in Batch Zero, its one-time study of Large Loads (75 MW or more) that
  seek to connect.
- ERCOT's Large Load Interconnection Status Update of 2026-03-13 reported 9,042 MW of Large Loads with
  Approval to Energize
  (https://www.ercot.com/files/docs/2026/03/12/March-TAC-Report.pdf).
- Senate Bill 6 (89th Legislature, 2025) set standards for connecting large loads in ERCOT, with a
  default threshold of 75 MW, covering cost allocation, backup generation, financial commitments and
  curtailment during shortages
  (https://capitol.texas.gov/tlodocs/89R/analysis/html/SB00006F.htm).

### Sales tax exemptions

- The Comptroller certifies qualifying data centers (at least 100,000 square feet, 20 jobs and $200
  million of investment over five years) and qualifying large data center projects (at least 250,000
  square feet, 40 jobs and $500 million). Their qualifying purchases, including electricity necessary
  and essential to their operation, are exempt from the 6.25% state sales tax for 10 or 15 years (data
  centers) or 20 years (large projects) (https://comptroller.texas.gov/taxes/data-centers/). The
  Comptroller lists both kinds of registered projects with their effective dates
  (https://comptroller.texas.gov/taxes/data-centers/data-center-lists.php).

### Construction statistics

- The Census Bureau's monthly Construction Spending release reports data center construction in its
  private construction table (https://www.census.gov/construction/c30/c30index.html).

## Evidence file

<<EVIDENCE>>

## Response template

```json
{
 "forecaster": {
  "model": null,
  "prior_context": null,
  "notes": null
 },
 "nodes": {
  "senate_dem_share": {
   "forecasts": {
    "dem_44.0": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "dem_47.0": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "dem_49.5": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "dem_50.5": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "dem_53.0": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "dem_56.0": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "ercot_pause_lifted": {
   "forecasts": {
    "dem_44.0": {
     "p": null
    },
    "dem_47.0": {
     "p": null
    },
    "dem_49.5": {
     "p": null
    },
    "dem_50.5": {
     "p": null
    },
    "dem_53.0": {
     "p": null
    },
    "dem_56.0": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "special_session_data_centers": {
   "forecasts": {
    "dem_44.0": {
     "p": null
    },
    "dem_47.0": {
     "p": null
    },
    "dem_49.5": {
     "p": null
    },
    "dem_50.5": {
     "p": null
    },
    "dem_53.0": {
     "p": null
    },
    "dem_56.0": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  }
 }
}
```
