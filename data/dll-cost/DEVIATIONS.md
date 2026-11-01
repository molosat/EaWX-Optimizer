# Deviations from the pre-registration

## 1. Fail fast after a late campaign start (during block 3, 2 hours 20 minutes after the study started)

**What happened.** Blocks 1–3 were the first blocks of the study. Three of the first five runs (`full 1`,
`lean 1`, `full 2`) failed at the fast-forward step: `advance.py` hit its 30-minute limit.
Each of those three had a late start. The probe's `start-campaign` call ran past its
60-second limit, which the probe will not raise, and the driver then waited for the galaxy
itself (`"start": {"late": true}` in `runs.jsonl`). The two runs that started normally
(`lean 2`, `full 3`) went through. None of the 30 runs in the 1080p study had a late start.

The stall screenshots show the galaxy still running (`full 1` had reached cycle 31 when it
failed), so the game was not stuck; the helper never read its clock. The likely cause is
that a timed-out start never opens the probe's session gate, so every Lua call is refused.
That is unconfirmed: the gate state of a late-start game was not read before the change.

**Change.** `submod_ab.py` now makes one Lua call right after a late start. If the probe
refuses it, the run fails at once with that refusal, instead of after 30 minutes of blind
clicking. The record gets `"start": {"late": true, "gate": "closed"}`. A late start that
answers Lua carries on as before. It takes effect from block 4; block 3's second run
was already under way on the old code.

**Effect on the analysis.** None on the measurement. A failed run was already an exclusion
in the pre-registration ("the driver marks it failed"), and this applies the same way to both
arms. It only stops a failed run from using 30 minutes of the night, so more blocks fit
before morning. Every run is still listed, failed or not.

Why the starts were slower in this study than in the 1080p study is not known.
