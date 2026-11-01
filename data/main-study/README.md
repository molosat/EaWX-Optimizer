# TR lag-fix submod: main study at 1920×1080

This study follows `PREREGISTRATION.md` (commit `fa70049`) with no deviations.

- **Runs:** 30 (10 per arm), about 6 hours 16 minutes, in the
  order of `order.txt`. The launcher started after 462 idle minutes.
- **Exclusions:** none. Every run collected its 120 game seconds at a 1920×1080
  client area and passed the script-health check.
- **Frames lost at the window's end:** none. `frames_missing` is 0 in all 30 runs,
  as the plan expected, so this study needs no `sensitivity.py`.
- **Interruptions:** none seen. The cursor was at its parked point at the end of every window.
- **Background load:** other processes used 14.7–24.0% of all CPU time.
- **Registry after the study:** the queued command meant to put the window back to
  the usual desktop resolution failed (Git Bash rewrote `reg add`'s `/v` switch
  as a path). This happened after the last run and does not touch the data; the window was left at
  1920×1080 for the space-battle work that follows.

Files:

- `runs.jsonl`: one record per run.
- `blocks.log`: the launcher's log.
- `analysis.txt`: the output of `analyze.py runs.jsonl`.
- `frames/`: each run's frame log, gzipped.

## Primary result

The primary endpoint is mean frame time, with each run one sample. The p-values
are Holm-corrected across the three contrasts.

| arm | mean frame time (ms) | ≈ fps |
|---|---|---|
| plain TR | 29.42 ± 2.04 | 34 |
| default layer | 18.28 ± 0.99 | 55 |
| candidate (default + native-groups + hero-cadence) | 12.39 ± 0.62 | 81 |

| contrast | difference (ms) | 95% CI | Holm p |
|---|---|---|---|
| candidate − plain | −17.03 | [−19.12, −14.95] | 7.6e-9 |
| default − plain | −11.15 | [−13.31, −8.98] | 5.1e-8 |
| candidate − default | −5.89 | [−6.99, −4.79] | 1.6e-8 |

All three null hypotheses are rejected at family-wise α = 0.05. The ≈ fps column
is 1000 divided by the mean frame time, for readability only.

## Secondary endpoints (supportive, unadjusted)

| endpoint | plain | default | candidate | candidate − plain |
|---|---|---|---|---|
| p95 (ms) | 73.4 | 55.4 | 42.3 | −31.1 [−35.0, −27.3] |
| p99 (ms) | 121.5 | 107.2 | 71.9 | −49.6 [−57.7, −41.4] |
| frames over 100 ms (%) | 1.85 | 1.17 | 0.39 | −1.46 [−1.78, −1.15] |
| game seconds per real second | 0.69 | 0.76 | 0.82 | +0.14 [+0.11, +0.16] |

The default layer mostly helps the typical frame: its p99 gain is
−14.3 ms [−23.1, −5.5], while the candidate's is −49.6 ms. The longest single
frame in any run was 1.30–2.34 s in plain TR, 0.33–0.56 s in the default layer and
0.24–0.30 s in the candidate.

## AI behaviour

`analysis.txt` lists the planets each faction owned at the end of each window, as
mean and range per arm.

- Chiss, Corellia, Killik Hives and Yevetha hold the same count in every run of
  all three arms.
- The contested factions differ by about one planet or less, with overlapping
  ranges. Zsinj, for example: 16.4 (13–18) plain, 16.1 (14–19) default,
  17.1 (14–21) candidate. Hutt Cartels: 8.7, 8.6 and 7.8, ranges 7–11, 7–10, 6–10.
- This coarse check shows no large change in who wins but cannot prove
  equivalence.

## Limits

As stated in the plan: one machine, one campaign, one faction, game time about 400–560 s,
an unfocused window, battles auto-resolved, and the camera fixed at the minimap's
centre view.
