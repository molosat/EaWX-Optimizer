# TR galactic lag-fix: study plan at 1920×1080

Written and committed before any run of this study. The commit that adds this file
fixes the plan. Any later change is a separate commit that says why, and the
write-up reports it as a deviation.

## Question

Does the data-only lag-fix submod make Thrawn's Revenge galactic conquest run
faster than plain TR at 1920×1080, without changing what the AI does?

## Arms

| label | Modpath | layer build |
|---|---|---|
| `plain` | TR | none |
| `default` | `core-fixes-layer` + TR | built at commit `c6a4e95` |
| `candidate` | `full-fix-layer` + TR | built at commit `c6a4e95` |

The default layer includes stagger, search-memo, sleep 10 s, factoring and
common-factors. The candidate adds native-groups and hero-cadence. Both layers
are built at commit `c6a4e95`, which includes the search-memo unit-type key and
the hero-cadence check order.

## Window and calibration

The game runs windowed with a 1920×1080 client area (`WindowWidth=1920`,
`WindowHeight=1080` in the FoC profile's registry key), anti-aliasing 4 and vsync off.

The driver's buttons (Auto-Resolve, Return to Galactic Map, Close on the objectives
window, the minimap centre and the cursor's parking point) are measured in a
calibration game before any run of this study. The driver selects these points
with `SUBMOD_AB_CLIENT=1920x1080` and fails a run whose game window does not have
that client size. The fast-forward helper (`advance.py`) uses the same points.

Before the study, one dry-run game checks the setup. It is not part of the study
and its numbers are not reported as results.

## End-of-window frames

The probe flushes its frame log every 120 frames. The driver keeps the game running
until the frame count is at least 125 past the window's end before closing it,
and records `frames_missing` per run (logged frames against the window's frame
count). This study expects `frames_missing` to be 0 in every run.

## Scenario and start state

- Campaign `FullLarge_Era_1_Empire`, played as the Empire on normal difficulty.
- Each run is a fresh game started from the main menu, with the arm's Modpath list.
- The game fast-forwards at speed 4 to game time 400 s. Held screens are dismissed
  along the way.
- A save file is not used. EaW saves keep the scripts' Lua state, so a save made
  under one arm could carry that arm's functions into another *(verify)*. Every
  healthy exploratory run used fresh starts.
- Galaxy speed is then set to 1, and the camera is reset to a fixed view before the
  window (see Driver).

## Measurement window

- The window is 120 game seconds of running galaxy at speed 1.
- The probe and the game clock are sampled every 2 real seconds.
- A stretch between samples is kept only if both samples read the game clock and
  game time advanced across it. Stretches held by a battle prompt, result screen
  or objectives window are cut out mechanically.
- Held time, dropped stretches and clicks are recorded per run.
- Frame times come from the probe's per-frame CSV (`FramesCsv=1`), sliced to the
  kept stretches.

## Driver

The test driver (`submod_ab.py`, not published) is fixed at the commit that runs the study.

- It identifies the screen that holds the galaxy from the game's open dialogs and
  clicks that screen's button: result screen → Return to Galactic Map; objectives
  window → Close; no dialog → Auto-Resolve.
- It resets the camera with a click on the minimap's centre, before the window and
  after each cleared result screen or objectives window. A prior test showed
  that this gives the same view each time, and that a parked cursor keeps the view
  still.
- It records the CPU time that other processes used during each window.

## Run order and sample size

- 10 runs per arm, 30 runs in total.
- The runs go in 10 blocks of three, one run per arm in each block. Blocks 1–6
  use the six orderings of the arms once each. Blocks 7–10 repeat four orderings,
  chosen so that each arm takes each position within a block 3 or 4 times. Drift
  over the night (heat, background jobs) falls almost evenly on all arms. The
  exact list is in `order.txt`, committed with this file.
- The study runs overnight with the machine otherwise idle.
  The test driver (`run_blocks.py`, not published) starts it in the evening, once the
  machine has had no keyboard or mouse input for 20 minutes. It runs each block as
  its own driver call, so a block that stops early does not end the study.
- Nobody uses the mouse during the study: the game edge-scrolls on the global cursor
  even while its window is in the background. The driver parks the cursor over the
  command bar, and records where the cursor is at the end of each window, so a run
  the machine's owner interrupted can be identified. Such runs are reported, not
  excluded.

## Endpoints

The experimental unit is one run. Each healthy run gives one value per endpoint.

- **Primary:** mean frame time (ms) in the window.
- **Secondary:** p95 and p99 frame time; share of frames over 100 ms; simulation
  rate (game seconds kept per real second).

## Contrasts and analysis

- **Primary contrast:** `candidate` against `plain`, on mean frame time.
- **Secondary contrasts:** `default` against `plain`, and `candidate` against
  `default`.
- Each contrast is a Welch difference of run means with a 95% interval.
- The three contrasts on the primary endpoint are Holm-corrected at family-wise
  α = 0.05.
- Secondary endpoints are reported with unadjusted 95% intervals, as supporting
  evidence only.
- Every run is reported, including failed and excluded runs, with the reason.

## Exclusions, fixed now

A run is excluded only if one of these holds:

- it failed: no main menu, the fast-forward never reached 400 s, or fewer than 120
  game seconds were collected within 6 × 120 real seconds;
- the script-health check reports a problem: a dead free-store thread, layer Lua
  not loaded, or a missing evaluator.

Excluded runs are not rerun mid-study. If more than 2 runs of an arm are excluded,
the shortfall is reported, and extra runs are added only in a separate, labelled
batch.

## AI-behaviour equivalence

The submod is meant to change cost, not decisions. For each run, the number of
planets each faction owns is recorded at the end of the window. The write-up
compares these counts across arms descriptively, per faction, as means with ranges.

Simulation rate is also compared. A layer that slowed the AI's clock would show up
there.

This is a coarse check. It can show a large behaviour change, not prove equivalence.

## Differences from the exploratory runs

- In most exploratory runs the camera had drifted to the galaxy's empty rim. The
  cause was a cursor resting at the screen's top edge, which edge-scrolled the
  unfocused game. That drift hit every arm, so comparisons between arms stand. The
  exploratory absolute frame times, however, measure a cheap view. This study fixes
  the view, so its absolute numbers are not comparable with the exploratory ones.
- Exploratory runs cleared held screens with a fixed click cycle, and many result
  screens were cleared by hand. This study names each screen from the game's open
  dialogs and clicks only the button that fits.

## Known limits

- One machine, one campaign, one faction, one stage of the game (400–600 game
  seconds).
- The window is unfocused, in the background. A focused-window subset is not run,
  because focus cannot be held unattended.
- Battles are auto-resolved, so tactical play is not measured.
