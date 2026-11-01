"""Factor repeated terms out of sums so each evaluates once (exact, cost-weighted Horner).

The engine evaluates every node, and a repeated Function_ call costs its whole
lookup tree again. Ground_Priority_Defense_Score, scored for every friendly
planet in every free-store target search, calls Is_Connected_To_Enemy four
times; E*(2 + S*(...)) evaluates it once.
"""
import equations as eq

MIN_GAIN = 20


def costs(definitions):
    """Expanded lookups per equation name (casefolded); unknown references cost 1.
    Costs only steer which factor comes out first; the proof checks the result."""
    canonical = {name.casefold(): name for name in definitions}
    memo = {}

    def total(name):
        key = name.casefold()
        if key not in canonical:
            return 1
        if key not in memo:
            memo[key] = 1  # a cycle costs 1 instead of recursing forever
            memo[key] = sum(atom_cost(n) for n in eq.walk(definitions[canonical[key]])
                            if n.kind in ('lookup', 'function'))
        return memo[key]

    def atom_cost(node):
        if node.kind == 'function':
            return total(node.value.removeprefix('Function_').removesuffix('.Evaluate'))
        if node.kind == 'lookup':
            return 1
        return sum(atom_cost(n) for n in eq.walk(node) if n is not node and n.kind in ('lookup', 'function')) or 1

    return atom_cost


def weighted(node, atom_cost):
    return sum(atom_cost(n) for n in eq.walk(node) if n.kind in ('lookup', 'function'))


def _product(atoms, coefficient):
    node = None
    for atom in atoms:
        node = atom if node is None else eq.Node('binary', '*', (node, atom))
    if node is None:
        return eq.Node('number', coefficient)
    if coefficient != 1:
        node = eq.Node('binary', '*', (eq.Node('number', coefficient), node))
    return node


def horner(polynomial, atom_cost):
    """Pull out the atom whose repeats cost most, recursively. Ties break by
    printed text, so the output does not depend on hash order."""
    if not polynomial:
        return eq.Node('number', eq.Fraction(0))
    counts = {}
    for monomial in polynomial:
        for atom in set(monomial):
            counts[atom] = counts.get(atom, 0) + 1
    best, gain = None, 0
    for atom in sorted(counts, key=eq.render):
        candidate = (counts[atom] - 1) * atom_cost(atom)
        if candidate > gain:
            best, gain = atom, candidate
    if best is None:
        terms = [_product(m, c) for m, c in sorted(polynomial.items(), key=lambda item: repr(item[0]))]
        node = terms[0]
        for term in terms[1:]:
            node = eq.Node('binary', '+', (node, term))
        return node
    inside, rest = {}, {}
    for monomial, coefficient in polynomial.items():
        if best in monomial:
            remaining = list(monomial)
            remaining.remove(best)
            inside[tuple(remaining)] = coefficient
        else:
            rest[monomial] = coefficient
    factored = eq.Node('binary', '*', (best, horner(inside, atom_cost)))
    return factored if not rest else eq.Node('binary', '+', (factored, horner(rest, atom_cost)))


def rewrite(node, atom_cost):
    """The factored form, or None when it is not exact-safe or saves under MIN_GAIN."""
    if node.kind == 'binary' and node.value in eq.COMPARISONS:
        return None
    # Merging repeated random terms would change how many draws are made.
    if any(n.value == '#' for n in eq.walk(node) if n.kind == 'binary'):
        return None
    try:
        polynomial = eq.expand(node)
    except ValueError:
        return None
    factored = horner(polynomial, atom_cost)
    if eq.expand(factored) != polynomial:
        raise ValueError('common-factor rewrite failed its exact proof')
    if weighted(node, atom_cost) - weighted(factored, atom_cost) < MIN_GAIN:
        return None
    return factored
