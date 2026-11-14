# Planning table

Assumed spreads, not results: no context's answer enters this table.

Margin 5 points; 16 evidence files; grid jumps assumed to vary as much as sqrt(S) times the within-cell spread (as if a grid context's six answers varied independently).

| Spread within a cell (points) | Spread of the true difference across files | Contexts a cell | Standard error | Chance equivalence shows if the arms agree | Smallest difference found 4 times in 5 |
|---|---|---|---|---|---|
| 3 | 0 | 3 | 0.61 | 1.00 | 1.8 |
| 3 | 0 | 6 | 0.43 | 1.00 | 1.3 |
| 3 | 2 | 3 | 0.79 | 1.00 | 2.3 |
| 3 | 2 | 6 | 0.66 | 1.00 | 2.0 |
| 3 | 4 | 3 | 1.17 | 0.99 | 3.5 |
| 3 | 4 | 6 | 1.09 | 1.00 | 3.2 |
| 5 | 0 | 3 | 1.02 | 1.00 | 3.0 |
| 5 | 0 | 6 | 0.72 | 1.00 | 2.1 |
| 5 | 2 | 3 | 1.13 | 0.99 | 3.4 |
| 5 | 2 | 6 | 0.88 | 1.00 | 2.6 |
| 5 | 4 | 3 | 1.43 | 0.92 | 4.2 |
| 5 | 4 | 6 | 1.23 | 0.98 | 3.7 |
| 8 | 0 | 3 | 1.63 | 0.81 | 4.8 |
| 8 | 0 | 6 | 1.15 | 0.99 | 3.4 |
| 8 | 2 | 3 | 1.70 | 0.76 | 5.1 |
| 8 | 2 | 6 | 1.26 | 0.97 | 3.7 |
| 8 | 4 | 3 | 1.91 | 0.61 | 5.7 |
| 8 | 4 | 6 | 1.53 | 0.87 | 4.5 |
| 12 | 0 | 3 | 2.44 | 0.23 | 7.3 |
| 12 | 0 | 6 | 1.73 | 0.75 | 5.1 |
| 12 | 2 | 3 | 2.49 | 0.20 | 7.4 |
| 12 | 2 | 6 | 1.80 | 0.70 | 5.3 |
| 12 | 4 | 3 | 2.64 | 0.11 | 7.8 |
| 12 | 4 | 6 | 2.00 | 0.55 | 5.9 |

The registered rule asks for a standard error of at most 1.65 points (an 80% chance that equivalence shows when the arms agree), from within-file noise alone. More contexts cannot shrink the spread of the true difference across files.

## What the sealed runs suggest

Spread across each family's six accepted sealed runs. It mixes context noise with differences in research, so it bounds the within-cell spread from above. Model forecasts, not observations.

| Family | Question | Spread of an answer at a cell | Spread of the jump |
|---|---|---|---|
| opus | `senate_dem_share` | 0.52 | 0.04 |
| opus | `ercot_pause_lifted` | 4.46 | 1.74 |
| opus | `special_session_data_centers` | 4.35 | 5.55 |
| sol | `senate_dem_share` | 0.18 | 0.03 |
| sol | `ercot_pause_lifted` | 5.36 | 2.87 |
| sol | `special_session_data_centers` | 2.38 | 2.21 |

## Talarico's share

The margin is 0.1 points. Equivalence can show only if the 90% interval's half-width, 1.75 standard errors, stays under it: a standard error below 0.057 points. With six contexts a cell and no spread across files, that needs a within-cell spread below 0.40 points. The registration treats Talarico's share as a secondary result for that reason.
