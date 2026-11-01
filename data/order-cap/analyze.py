"""Exploratory analysis of the order-cap A/B (README.md): candidate against candidate + order-cap 16.

python -I -B analyze.py <runs.jsonl>

Each healthy run is one sample. Contrasts are Welch differences of run means (cap16 - cand)
with unadjusted 95% intervals, using the main study's helpers. Also prints every run,
the battles each game auto-resolved, the cap's own counters, and planets per owner by arm.
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'main_study', Path(__file__).resolve().parent.parent / 'main-study' / 'analyze.py')
main_study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main_study)
welch, t_quantile_975 = main_study.welch, main_study.t_quantile_975

ENDPOINTS = ('mean', 'p95', 'p99', 'over100_pct', 'max', 'sim', 'held_s', 'battles')
CAP = ('Calls', 'SkipService', 'SkipAdded', 'Exempt')


def main(path):
    recs = [json.loads(line) for line in open(path) if line.strip()]
    arms = {}
    print('Every run, in order:')
    for r in recs:
        if r.get('failed') or (r.get('health') or {}).get('problems'):
            print(f"  {r['label']:>6} {r['index']}  EXCLUDED: failed at step {r.get('step')}")
            continue
        s, cpu, view = r['stats'], r.get('cpu') or {}, r.get('view') or {}
        moved = view.get('parked') is not None and view.get('cursor_end') != view.get('parked')
        diag = (r.get('health') or {}).get('diag') or {}
        a = arms.setdefault(r['label'], {k: [] for k in ENDPOINTS} | {'owners': [], 'cap': []})
        for k in ('mean', 'p95', 'p99', 'max', 'sim'):
            a[k].append(s[k])
        a['over100_pct'].append(100 * s['over100'] / s['frames'])
        a['held_s'].append(r['held_s'])
        a['battles'].append((r.get('clicks') or {}).get('prompt', 0))
        a['owners'].append(dict(p.split('=') for p in (r.get('owners') or '').split()))
        if diag:
            a['cap'].append({k: diag.get('AlamoDiagCap' + k, 0) for k in CAP})
        print(f"  {r['label']:>6} {r['index']}  mean {s['mean']:6.2f}  p99 {s['p99']:6.2f}  over100 {s['over100']:3}"
              f"  max {s['max']:6.1f}  battles {a['battles'][-1]}  held {r['held_s']:4.0f} s"
              f"  other CPU {cpu.get('other_pct', float('nan')):4.1f}%  cursor moved {moved}")
    print('\nRun means by arm (95% interval):')
    for label, a in arms.items():
        n = len(a['mean'])
        cells = []
        for k in ENDPOINTS:
            m = sum(a[k]) / n
            sd = math.sqrt(sum((v - m) ** 2 for v in a[k]) / (n - 1))
            cells.append(f"{k} {m:.2f} +- {t_quantile_975(n - 1) * sd / math.sqrt(n):.2f}")
        print(f"  {label:>6} n={n}  " + '  '.join(cells))
    print('\ncap16 - cand (Welch, unadjusted 95% intervals):')
    for k in ENDPOINTS:
        d, h, t, df, p = welch(arms['cap16'][k], arms['cand'][k])
        print(f"  {k:>11}: {d:+.2f} [{d - h:.2f}, {d + h:.2f}]  p = {p:.2f}")
    print('\nCap counters per game (whole game, not just the window):')
    for c in arms['cap16']['cap']:
        held = c['SkipService'] + c['SkipAdded']
        print(f"  calls {c['Calls']:.0f}  held back {held:.0f} ({100 * held / (held + c['Calls']):.0f}% of attempts:"
              f" {c['SkipService']:.0f} service, {c['SkipAdded']:.0f} added)  exempt {c['Exempt']:.0f}")
    print('\nPlanets per owner at window end, mean (min-max) per arm:')
    factions = sorted({f for a in arms.values() for o in a['owners'] for f in o})
    print('  ' + 'faction'.ljust(20) + ''.join(label.rjust(14) for label in arms))
    for f in factions:
        cells = []
        for a in arms.values():
            v = [int(o.get(f, 0)) for o in a['owners']]
            cells.append(f"{sum(v) / len(v):.1f} ({min(v)}-{max(v)})".rjust(14))
        print('  ' + f.ljust(20) + ''.join(cells))


if __name__ == '__main__':
    main(sys.argv[1])
