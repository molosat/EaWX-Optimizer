# What the timing DLL costs: study plan

Written and committed before any run. The commit that adds this file, `order.txt` and
`analyze.py` fixes the plan; any later change is a separate commit that says why.

## Question

The galactic lag-fix post (`docs/post/post.src.html`) times every frame with this repo's
`d3d9.dll`. How much of each measured frame is the DLL's own work? The differences between
the post's versions are fair either way, because every game ran the same DLL build, but its
absolute frame times and fps include that cost.

An outside frame timer (PresentMon) needs admin rights this machine's session doesn't have,
so a game without the DLL can't be timed. Instead the cost is split into two parts, each
measured directly, and the rest is named as unmeasured.

## Arms

Both arms run the same DLL build, `build/Release` at the commit that adds the `zone_dll`
column (the DLL's own time per frame, below), with the command pipe on, as in every study.

| label | settings (`alamo_profiler.ini`, `[alamo_profiler]`) |
|---|---|
| `full` | the defaults, as the galactic studies ran: `FramesCsv=1`, `GpuTiming=1`, `DrawTiming=1`, `MemoryEvery=60` |
| `lean` | `FramesCsv=1`, `GpuTiming=0`, `DrawTiming=0`, `MemoryEvery=0` |

`full − lean` is the cost of the optional measurements: GPU timestamp queries, two clock reads
per draw call, and the memory sampler thread.

`zone_dll`, recorded in both arms, is the render thread's time per frame inside the DLL's
own per-frame code: the work around `Present` (thread check, back-buffer size, command pipe,
GPU frame end), the frame bookkeeping after it (stats, GPU result polling, memory-sample
requests, CSV writes) and the GPU frame start. In `lean` this is the always-on part.

## Scenario

The galactic study's scenario at 1920×1080 (`data/main-study/`):
`FullLarge_Era_1_Empire`, Empire, normal, a fresh campaign per run, fast-forward to 400 game
seconds, then a 120-game-second window at speed 1. Driver the test driver (submod_ab.py, not published)
with `SUBMOD_AB_CLIENT=1920x1080`, through `run_blocks.py`.

The game runs TR with the post's Full-fix layer (`full-fix-layer` + TR, as the
`candidate` arm of the 1080p study). Its run-to-run spread was 0.86 ms against plain TR's
2.85 ms, so the interval is about three times narrower; and at about 12 ms a frame it is
where a fixed DLL cost is the largest share of the post's numbers.

Before the first run the FoC profile's `WindowWidth`/`WindowHeight` are set to 1920×1080,
and restored to the usual desktop resolution after the last.

## Runs and order

15 blocks of two, 30 runs, alternating which arm goes first (`order.txt`), so drift over the
night falls on both arms. `run_blocks.py` starts in the evening, after 20 idle
minutes. With 15 runs per arm and the 1080p study's spread, the 95% interval on `full − lean`
is about ±0.65 ms.

## Endpoints and analysis (`analyze.py`)

Each run is one sample, its value computed over the window's frames.

- **Primary:** mean frame time, `full − lean`, Welch 95% interval and p.
- **Secondary:** mean `zone_dll` per arm with 95% intervals; hooked calls per frame
  (draws, state and shader sets, clears, scenes) per arm.
- **Cost of the DLL as the studies ran it**, estimate: `(full − lean) + lean zone_dll`.
  **Upper bound:** the upper end of the `full − lean` interval plus the upper end of the
  `lean zone_dll` interval. Both are also given as a share of the `full` arm's mean frame time.
- **Not measured:** the per-call hooks, each a counter increment and one extra indirect
  call. The write-up names this part and gives the hooked-call count per frame, without
  putting a number on its cost.

## Exclusions

As in the galactic studies: a run is excluded if the driver marks it failed (no main menu,
the fast-forward never reached 400 s, too few game seconds collected, wrong client size)
or its script-health check reports a problem. Every run, excluded or not, is listed.

## What this study does not answer

The cost on other machines, at other resolutions or in plain TR's heavier frames; the
reduced public build, which drops the command pipe and will cost the same or less than
`lean`; and the per-call hook cost above.
