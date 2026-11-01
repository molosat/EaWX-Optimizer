"""Rank equation XML files by direct and recursively expanded lookup counts."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import equations as eq


def load(folder):
    equations = {}
    for path in sorted(Path(folder).rglob('*')):
        if not path.is_file() or path.suffix.lower() != '.xml':
            continue
        try:
            for name, node, _ in eq.xml_equations(path.read_bytes().decode('latin1')):
                if name in equations:
                    raise ValueError(f'duplicate equation {name}')
                equations[name] = node
        except ValueError as exc:
            raise ValueError(f'{path}: {exc}') from exc
    return equations


def statistics(equations):
    """Memoize DAG totals; cycles and missing references fail explicitly.

    Script_*.Evaluate is an opaque lookup (one cache scan), not a Function_
    reference to inline. lookup_count includes it exactly once.
    """
    memo, active = {}, []
    canonical = {}
    for name in equations:
        folded = name.casefold()
        if folded in canonical:
            raise ValueError(f'case-ambiguous equation names: {canonical[folded]}, {name}')
        canonical[folded] = name

    def expanded(name):
        name = canonical.get(name.casefold(), name)
        if name in memo:
            return memo[name]
        if name in active:
            raise ValueError('equation reference cycle: ' + ' -> '.join(active + [name]))
        if name not in equations:
            raise ValueError(f'missing Function_ equation: {name}')
        active.append(name)
        result = 0
        for node in eq.walk(equations[name]):
            if node.kind == 'lookup':
                # Script_ calls are opaque cache lookups, just like Variable_.
                result += 1
            elif node.kind == 'function':
                target = node.value.removeprefix('Function_').removesuffix('.Evaluate')
                result += expanded(target)
        active.pop()
        memo[name] = result
        return result

    rows = [(name, eq.lookup_count(node), expanded(name)) for name, node in equations.items()]
    return sorted(rows, key=lambda row: (-row[2], row[0]))


def tree(equations, name, depth=3, indent=0, out=None):
    """Lines showing each Function_ reference under name with its expanded count."""
    out = [] if out is None else out
    totals = {row[0]: row[2] for row in statistics(equations)}
    canonical = {n.casefold(): n for n in equations}
    def visit(name, level):
        name = canonical.get(name.casefold(), name)
        calls = [node.value.removeprefix('Function_').removesuffix('.Evaluate')
                 for node in eq.walk(equations[name]) if node.kind == 'function']
        out.append(f"{'  ' * level}{totals[name]:6d}  {name} (own {eq.lookup_count(equations[name])}, "
                   f"{len(calls)} calls)")
        if level < depth:
            for call in sorted(set(calls), key=lambda c: -totals[canonical.get(c.casefold(), c)]):
                n = calls.count(call)
                if n > 1:
                    out.append(f"{'  ' * (level + 1)}x{n}")
                visit(call, level + 1)
    visit(name, indent)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--tree', metavar='EQUATION', help='show what one equation calls')
    parser.add_argument('--depth', type=int, default=3)
    args = parser.parse_args()
    try:
        if args.tree:
            print('\n'.join(tree(load(args.folder), args.tree, args.depth)))
            return
        rows = statistics(load(args.folder))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'error: {exc}\n')
    print('expanded\town\tequation')
    for name, own, expanded in rows:
        print(f'{expanded}\t{own}\t{name}')


if __name__ == '__main__':
    main()
