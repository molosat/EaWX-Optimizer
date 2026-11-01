"""Pre-registered analysis of the timing DLL's cost (PREREGISTRATION.md).

python -I -B analyze.py <study dir>

Reads <study dir>/runs.jsonl and each run's window slice <label>-<index>_frames.csv. Each
healthy run is one sample, excluded by the galactic study's rule (failed, or a script-health
problem). Primary: mean frame time, full - lean, Welch 95% interval. Secondary: zone_dll
(the DLL's own per-frame time) by arm, and the hooked calls per frame. The cost estimate
and its upper bound are computed as the plan fixes them.
"""
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / 'main-study'))
from analyze import welch, t_quantile_975  # noqa: E402  (the galactic study's Welch)

ARMS = ('full', 'lean')
HOOKED = ('draws', 'set_texture', 'set_render_state', 'set_shader', 'set_stream',
          'set_const', 'set_rt', 'clears', 'scenes')


def mean(xs):
    return sum(xs) / len(xs)


def interval(xs):
    """Mean and 95% half-width of the mean."""
    m = mean(xs)
    sd = math.sqrt(sum((v - m) ** 2 for v in xs) / (len(xs) - 1))
    return m, t_quantile_975(len(xs) - 1) * sd / math.sqrt(len(xs))


def slice_means(study, r):
    rows = list(csv.DictReader(open(study / f"{r['label']}-{r['index']}_frames.csv", encoding='utf-8')))
    return (mean([float(x['zone_dll']) for x in rows]),
            mean([sum(int(x[k]) for k in HOOKED) for x in rows]))


def main(study):
    study = Path(study)
    recs = [json.loads(line) for line in open(study / 'runs.jsonl', encoding='utf-8') if line.strip()]
    arms = {a: {'mean': [], 'dll': [], 'calls': []} for a in ARMS}
    print('Every run, in order:')
    excluded = 0
    for r in recs:
        bad = r.get('failed') or (r.get('health') or {}).get('problems')
        s, cpu = r.get('stats') or {}, r.get('cpu') or {}
        line = (f"  {r['label']:>4} {r['index']:>2}  settings {','.join(r.get('settings') or []) or '-':40}"
                f"  mean {s.get('mean', float('nan')):6.2f}  other CPU {cpu.get('other_pct', float('nan')):5.1f}%")
        if bad:
            excluded += 1
            print(line + f"  EXCLUDED: {r.get('error') or r.get('hang') or (r.get('health') or {}).get('problems')}")
            continue
        dll, calls = slice_means(study, r)
        a = arms[r['label']]
        a['mean'].append(s['mean']); a['dll'].append(dll); a['calls'].append(calls)
        print(line + f"  zone_dll {dll:.4f}  hooked calls/frame {calls:.0f}")
    print(f'\nExcluded runs: {excluded}')
    for label in ARMS:
        a = arms[label]
        m, h = interval(a['mean']); dm, dh = interval(a['dll'])
        print(f"  {label}: n {len(a['mean'])}  frame {m:.2f} +- {h:.2f} ms  zone_dll {dm:.4f} +- {dh:.4f} ms"
              f"  hooked calls/frame {mean(a['calls']):.0f}")
    d, h, t, df, p = welch(arms['full']['mean'], arms['lean']['mean'])
    print(f'\nPrimary: full - lean mean frame time {d:+.2f} ms (95% {d - h:+.2f} to {d + h:+.2f}),'
          f' t {t:.2f}, df {df:.1f}, p {p:.3g}')
    dm, dh = interval(arms['lean']['dll'])
    estimate, bound = d + dm, (d + h) + (dm + dh)
    full_mean = mean(arms['full']['mean'])
    print(f'Cost of the DLL as the studies ran it, estimate: (full - lean) + lean zone_dll = {estimate:+.2f} ms'
          f' ({100 * estimate / full_mean:.1f}% of the full arm\'s {full_mean:.2f} ms frame)')
    print(f'Upper bound: upper ends of both intervals = {bound:.2f} ms ({100 * bound / full_mean:.1f}%)')
    print('Not measured: the per-call hooks (a counter increment and an extra indirect call each);'
          ' the hooked-call counts above show how many there are per frame.')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else HERE)
