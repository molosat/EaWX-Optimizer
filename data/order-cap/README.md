# Order cap: fewer free-store orders per frame

Follow-up to an earlier test, which found the largest galactic stalls
are AI free-store script frames. In those frames, hundreds of fleet orders clear planet
icons, and the next frame pays for each clear with a galaxy-wide path rebuild.

The opt-in submod component `order-cap` (`submod/README.md`) limits each free store to N
target searches and orders per frame. A safe unit over the cap waits for its next service
under TR's own rules; an unsafe unit always moves.

This is an exploratory A/B with no pre-registered plan. Read its intervals as descriptive.

## Method

- **Census first:** one fresh game on the candidate layer with the cap set to 100,000, so
  nothing was held back, to see how calls spread over frames. It counted 4,323 calls in
  about 550 game seconds, and 77 frames (14% of calls) went above 16 calls per store. So
  16 was chosen as the default.
- **A/B:** 8 fresh games in ABBA order:
  - **cand:** the main study's candidate layer.
  - **cap16:** the same layer plus `order-cap` with N = 16. Only `GalacticFreeStore.lua`
    differs.
- **Settings:** the game ran at a different window size from the 1920×1080 study,
  so its absolute frame times are not comparable. It used the test driver,
  campaign (large era 1, as the Empire),
  auto-resolved battles and parked cursor. Each game ran to game time 400 and was then
  measured for 120 game seconds. Held stretches (battle prompts, result screens) are cut
  from the window.
- **Exclusion:** one cap16 game (2) timed out while advancing to game time 400 and has no
  window. Why it stalled was not recorded *(verify)*. That leaves 3 cap16 games and 4 cand
  games.
- **Run checks:** no cursor moved in any window. Other processes used 17-31% CPU, and the
  highest (31%) was a cand game.

Files:

- `census-runs.jsonl`, `census-1_frames.csv`: the census.
- `ab-runs.jsonl`, `ab-<arm>-<n>_frames.csv`: the A/B records and window slices.
- `analyze.py`, `analysis.txt`: the analysis and its output.

## Results

cap16 minus cand, Welch, unadjusted 95% intervals:

| endpoint | cand (n=4) | cap16 (n=3) | difference |
|---|---|---|---|
| mean frame (ms) | 15.07 | 13.61 | -1.46 [-4.08, +1.16] |
| p95 (ms) | 46.75 | 44.60 | -2.15 [-8.32, +4.03] |
| p99 (ms) | 79.72 | 74.05 | -5.67 [-20.62, +9.28] |
| frames over 100 ms (%) | 0.50 | 0.45 | -0.04 [-0.33, +0.24] |
| longest frame (ms) | 300.1 | 277.5 | -22.6 [-70.5, +25.3] |
| sim rate | 0.82 | 0.79 | -0.03 [-0.10, +0.03] |
| battles the player had to resolve | 1.75 | 7.00 | +5.25 [+3.14, +7.36] |
| time held by battle screens (s) | 47 | 178 | +131 [+79, +183] |

What the cap held back, over each whole game:

| game | calls let through | held back | share of attempts | unsafe exemptions |
|---|---|---|---|---|
| cap16 1 | 4,106 | 869 (560 service, 309 newly added) | 17% | 2 |
| cap16 3 | 4,032 | 1,047 (633 service, 414 newly added) | 21% | 10 |
| cap16 4 | 4,194 | 872 (596 service, 276 newly added) | 17% | 6 |

At the end of the window the player's Empire held 26.3 planets on average under cap16
(26-27), against 28.8 under cand (28-29). Other owners differ by at most about one planet.

## What this says

- **No clear frame-time gain.** Every frame-time difference points the cap's way, but every
  interval includes zero. The census already showed why the room is small: the candidate's
  stagger keeps most store frames under 16 calls, and only 7 frames in a game reached 33.
- **A clear behaviour change.** The AI attacked the player about four times as often, and
  the player ended with about 2.5 fewer planets. With only 3 and 4 games this is not a
  measured effect size, but the battle counts do not overlap: cand games had 1-2 battles,
  cap16 games 6-8.
  - Why holding back safe moves makes the AI more aggressive is unknown *(verify)*. One
    guess: units that would have been sent to the rear stay near the front and join attacks.
- **Verdict:** order-cap at 16 does not pay for its behaviour change. It stays opt-in and off.
  A higher cap would hold back less, and so gain even less.

## Limits

- Exploratory, 3 against 4 games, one campaign and faction, one 120-second window each.
- One cap16 game was lost, so the design is no longer balanced ABBA.
- The cap16 games spent more time on battle screens, which is cut from the window. The
  windows still cover the same game time (120 s).
- Battles were auto-resolved, as in the study.
