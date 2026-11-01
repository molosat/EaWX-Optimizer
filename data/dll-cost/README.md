# What the timing DLL costs: results

Plan: [`PREREGISTRATION.md`](PREREGISTRATION.md). Deviation: [`DEVIATIONS.md`](DEVIATIONS.md).
Unedited analysis output: [`analysis.txt`](analysis.txt). Run log: `blocks.log`, `runs.jsonl`.
Ran for about 7 hours 23 minutes, 15 blocks, 30 runs. The window was set to
1920×1080 before the first run and restored to the usual desktop resolution after the last.

## Result

The cost of the DLL, as every study ran it, can't be told apart from zero. Its upper bound
is 1.4 ms per frame.

| | n | mean frame time | `zone_dll` (DLL's own time per frame) |
|---|---|---|---|
| `full` (study settings) | 13 | 18.03 ± 1.19 ms | 0.181 ± 0.010 ms |
| `lean` (no GPU/draw timing, no memory sampler) | 13 | 18.73 ± 1.64 ms | 0.171 ± 0.013 ms |

- **Primary, `full − lean`:** −0.69 ms (95% interval −2.62 to +1.24), Welch t −0.74,
  df 21.9, p 0.47. The optional measurements have no detectable cost.
- **Estimated cost, `(full − lean) + lean zone_dll`:** −0.52 ms. That is not a negative cost,
  only a difference smaller than the noise.
- **Upper bound, from the upper ends of both intervals:** 1.42 ms, 7.9% of the `full` arm's
  18.03 ms frame.
- **The always-on code:** `zone_dll` is the cleanest number here. The DLL's own per-frame
  work is about 0.17–0.18 ms, about 1% of a frame, in both arms. The optional
  measurements add about 0.01 ms to it.
- **Not measured:** the per-call hooks. Each is a counter increment plus one extra indirect
  call, and there are about 2,650 hooked calls per frame in both arms.

## Every run

| block | run | result |
|---|---|---|
| 1 | full 1, lean 1 | both failed: late start, then the fast-forward hit its 30-minute limit |
| 2 | lean 2 | 20.50 ms |
| 2 | full 2 | failed: late start, then the fast-forward hit its 30-minute limit |
| 3 | full 3, lean 3 | 21.37, 23.55 ms |
| 4 | lean 4, full 4 | 21.40, 21.33 ms |
| 5 | full 5, lean 5 | 19.99, 21.13 ms |
| 6 | lean 6, full 6 | 19.05, 20.24 ms |
| 7 | full 7, lean 7 | 17.77, 22.34 ms |
| 8 | lean 8 | failed: the fast-forward hit its 30-minute limit after a normal start |
| 8 | full 8 | 16.91 ms |
| 9 | full 9, lean 9 | 17.51, 16.24 ms |
| 10 | lean 10, full 10 | 16.50, 15.85 ms |
| 11 | full 11, lean 11 | 17.00, 16.63 ms |
| 12 | lean 12, full 12 | 16.17, 16.85 ms |
| 13 | full 13, lean 13 | 16.24, 16.52 ms |
| 14 | lean 14, full 14 | 15.97, 16.97 ms |
| 15 | full 15, lean 15 | 16.42, 17.46 ms |

Every run that finished passed the script-health check. The four failures are pre-registered
exclusions. No late start happened after the deviation's fix went in, so the fix never
triggered. `lean 8` failed for some other reason, which wasn't investigated.

## Caveat: the machine was busier than in the 1080p study

The pre-registration expected an interval of about ±0.65 ms. The real one is three times wider,
for two reasons:

- **Background load.** Other processes used 24–38% of the CPU during the windows, against
  15–20% in the 1080p study's runs of the same layer. Blocks 1–7 were the busiest: 29–38%,
  frames of 18–24 ms and every late start. Blocks 8–15 settled at 24–29% and 16–17.5 ms.
  Another project's scripts were running on the machine during the study.
- **A slower baseline.** The same Full-fix layer averaged 12.39 ms in the 1080p study, against
  16–17 ms here even in the quiet blocks. So absolute frame times from this night aren't
  comparable with the post's numbers. Only the within-night comparison between arms is.

Alternating the order within each block put the drift on both arms. As an exploratory check,
not pre-registered, the 12 blocks with both runs healthy give a paired `full − lean` of
−0.45 ms (−1.51 to +0.61), which agrees with the primary result.
