"""Pre-registered analysis of the TR main study (PREREGISTRATION.md).

python -I -B analyze.py <runs.jsonl>

Each healthy run is one sample. Contrasts are Welch differences of run means with 95%
intervals; the three primary contrasts on mean frame time are Holm-corrected at 0.05.
Secondary endpoints get unadjusted intervals. Also prints every run, the CPU share of
other processes, the cursor check, and planets per owner by arm.
"""
import json
import math
import sys

ENDPOINTS = ('mean', 'p95', 'p99', 'over100_pct', 'sim')
CONTRASTS = (('candidate', 'plain'), ('default', 'plain'), ('candidate', 'default'))


def betacf(a, b, x):
    """Continued fraction for the regularized incomplete beta (Numerical Recipes)."""
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > 1e-300 else 1e-300)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + aa / c if abs(1 + aa / c) > 1e-300 else 1e-300
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + aa / c if abs(1 + aa / c) > 1e-300 else 1e-300
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14:
            break
    return h


def betai(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbeta) * betacf(a, b, x) / a
    return 1 - math.exp(lbeta) * betacf(b, a, 1 - x) / b


def t_two_sided_p(t, df):
    return betai(df / 2, 0.5, df / (df + t * t))


def t_quantile_975(df):
    lo, hi = 0.0, 100.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_two_sided_p(mid, df) > 0.05:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def welch(a, b):
    """a - b: difference, 95% half-width, t, df, two-sided p."""
    na, nb = len(a), len(b)
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((v - ma) ** 2 for v in a) / (na - 1) / na
    vb = sum((v - mb) ** 2 for v in b) / (nb - 1) / nb
    se = math.sqrt(va + vb)
    df = (va + vb) ** 2 / (va ** 2 / (na - 1) + vb ** 2 / (nb - 1))
    t = (ma - mb) / se
    return ma - mb, t_quantile_975(df) * se, t, df, t_two_sided_p(abs(t), df)


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adjusted, running = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        adjusted[i] = running
    return adjusted


def main(path):
    recs = [json.loads(line) for line in open(path) if line.strip()]
    arms, excluded = {}, []
    print('Every run, in order:')
    for r in recs:
        bad = r.get('failed') or (r.get('health') or {}).get('problems')
        cpu, view = r.get('cpu') or {}, r.get('view') or {}
        moved = view.get('parked') is not None and view.get('cursor_end') != view.get('parked')
        s = r.get('stats') or {}
        print(f"  {r['label']:>9} {r['index']:>2}  mean {s.get('mean', float('nan')):6.2f}  p95 {s.get('p95', float('nan')):6.2f}"
              f"  held {r.get('held_s', 0):5.0f} s  clicks {sum((r.get('clicks') or {}).values()):2}"
              f"  other CPU {cpu.get('other_pct', float('nan')):5.1f}%  cursor moved {moved}"
              + ('  EXCLUDED' if bad else ''))
        if bad:
            excluded.append(r)
            continue
        a = arms.setdefault(r['label'], {k: [] for k in ENDPOINTS} | {'owners': []})
        for k in ('mean', 'p95', 'p99', 'sim'):
            a[k].append(s[k])
        a['over100_pct'].append(100 * s['over100'] / s['frames'])
        a['owners'].append(dict(p.split('=') for p in (r.get('owners') or '').split()))
    print(f'\nExcluded runs: {len(excluded)}')
    print('\nRun means by arm (95% interval):')
    for label, a in arms.items():
        n = len(a['mean'])
        cells = []
        for k in ENDPOINTS:
            m = sum(a[k]) / n
            sd = math.sqrt(sum((v - m) ** 2 for v in a[k]) / (n - 1))
            cells.append(f"{k} {m:.2f} +- {t_quantile_975(n - 1) * sd / math.sqrt(n):.2f}")
        print(f"  {label:>9} n={n}  " + '  '.join(cells))
    print('\nPrimary: mean frame time, Welch, Holm over the three contrasts (alpha 0.05):')
    rows = [welch(arms[x]['mean'], arms[y]['mean']) for x, y in CONTRASTS]
    for (x, y), (d, h, t, df, p), adj in zip(CONTRASTS, rows, holm([r[4] for r in rows])):
        print(f"  {x} - {y}: {d:+.2f} ms, 95% CI [{d - h:.2f}, {d + h:.2f}], t = {t:.2f}, df = {df:.1f},"
              f" p = {p:.2e}, Holm p = {adj:.2e}, {'reject' if adj < 0.05 else 'do not reject'} H0")
    print('\nSecondary endpoints (unadjusted 95% intervals, supportive):')
    for k in ENDPOINTS[1:]:
        for x, y in CONTRASTS:
            d, h, *_ = welch(arms[x][k], arms[y][k])
            print(f"  {k:>11}  {x} - {y}: {d:+.2f} [{d - h:.2f}, {d + h:.2f}]")
    print('\nPlanets per owner at window end, mean (min-max) per arm:')
    factions = sorted({f for a in arms.values() for o in a['owners'] for f in o})
    print('  ' + 'faction'.ljust(20) + ''.join(label.rjust(18) for label in arms))
    for f in factions:
        cells = []
        for a in arms.values():
            v = [int(o.get(f, 0)) for o in a['owners']]
            cells.append(f"{sum(v) / len(v):.1f} ({min(v)}-{max(v)})".rjust(18))
        print('  ' + f.ljust(20) + ''.join(cells))


if __name__ == '__main__':
    main(sys.argv[1])
