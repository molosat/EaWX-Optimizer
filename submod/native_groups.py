"""Group adjacent native lookups, with an independent linear-map proof."""
from collections import Counter
from dataclasses import dataclass, replace
import html
import re

import equations as eq


TOKEN = 'Variable_Target.Type.IsType'


@dataclass(frozen=True)
class GroupSpec:
    token: str
    parameter: str
    by_prefix: bool = False

    def names(self, node):
        matches = (node.value.endswith('.' + self.token) if self.by_prefix
                   else node.value == self.token) if node.kind == 'lookup' else False
        if (not matches or not node.params
                or any(k != self.parameter or v[0] != 'string' for k, v in node.params)):
            return None
        # Faction proof keys include the full path; different owners are independent.
        return tuple((node.value, v[1]) if self.by_prefix else v[1]
                     for _, v in node.params)

    def grouped(self, names):
        token = names[0][0] if self.by_prefix else self.token
        return eq.Node('lookup', token, params=tuple(
            (self.parameter, ('string', name[1] if self.by_prefix else name))
            for name in names))

    def identity(self, name):
        return (name[0], name[1].casefold()) if self.by_prefix else name.casefold()


TYPE_GROUPS = GroupSpec(TOKEN, 'Parameter_Type')
FACTION_GROUPS = GroupSpec('IsFaction', 'Parameter_Faction', by_prefix=True)


def type_names(node, spec=TYPE_GROUPS):
    return spec.names(node)


def constant(node):
    if any(item.kind not in ('number', 'neg', 'binary') for item in eq.walk(node)):
        return None
    try:
        polynomial = eq.expand(node)
        if not (polynomial.keys() - {()}):
            return polynomial.get((), eq.Fraction(0))
    except ValueError:
        pass
    return None


def weighted_types(node, spec=TYPE_GROUPS):
    """Accept constant products/quotients, but never products of eligible lookups."""
    names = type_names(node, spec)
    if names is not None:
        return eq.Fraction(1), names
    if node.kind == 'neg':
        found = weighted_types(node.args[0], spec)
        return (-found[0], found[1]) if found else None
    if node.kind == 'binary' and node.value in ('*', '/'):
        left, right = node.args
        coefficient = constant(right)
        found = weighted_types(left, spec)
        if found and coefficient is not None and (node.value != '/' or coefficient):
            return (found[0] * coefficient if node.value == '*' else found[0] / coefficient,
                    found[1])
        if node.value == '*':
            coefficient, found = constant(left), weighted_types(right, spec)
            if coefficient is not None and found:
                return coefficient * found[0], found[1]
    return None


def additive_terms(node, sign=1):
    if node.kind == 'binary' and node.value in ('+', '-'):
        yield from additive_terms(node.args[0], sign)
        yield from additive_terms(node.args[1], sign if node.value == '+' else -sign)
    else:
        yield sign, node


def grouped(names, spec=TYPE_GROUPS):
    return spec.grouped(names)


def rewrite(node, group_size=0, emit=None, can_join=None, spec=TYPE_GROUPS):
    if node.kind != 'binary' or node.value not in ('+', '-'):
        args = tuple(rewrite(child, group_size, emit, can_join, spec) for child in node.args)
        return replace(node, args=args) if args != node.args else node
    terms = [(sign, rewrite(term, group_size, emit, can_join, spec)) for sign, term in additive_terms(node)]
    output, run, seen = [], [], set()
    run_coefficient = None

    def flush():
        if len(run) > 1:
            lookup = grouped([name for _, _, name in run], spec)
            if emit:
                emit(run, run_coefficient, lookup)
            coefficient = eq.Node('number', run_coefficient)
            output.append((1, lookup if run_coefficient == 1 else
                           eq.Node('binary', '*', (coefficient, lookup))))
        else:
            output.extend((sign, term) for sign, term, _ in run)
        run.clear()

    for sign, term in terms:
        found = weighted_types(term, spec)
        if found is None or len(found[1]) != 1:
            flush()
            output.append((sign, term))
            if found:
                seen.update(spec.identity(name) for name in found[1])
            continue
        coefficient, (name,) = found
        coefficient *= sign
        # Case aliases are also kept separate: engine case handling need not be assumed.
        duplicate = spec.identity(name) in seen
        seen.add(spec.identity(name))
        if duplicate:
            flush()
            output.append((sign, term))
            continue
        if ((run and spec.by_prefix and name[0] != run[-1][2][0])
                or coefficient != run_coefficient or (group_size and len(run) >= group_size)
                or (run and can_join and not can_join(run[-1][1], term))):
            flush()
        run_coefficient = coefficient
        run.append((sign, term, name))
    flush()
    sign, result = output[0]
    if sign == -1:
        result = eq.Node('neg', '-', (result,))
    for sign, term in output[1:]:
        result = eq.Node('binary', '+' if sign == 1 else '-', (result, term))
    return result


def expand_groups(node, spec=TYPE_GROUPS):
    """Proof path independent of run detection and coefficient extraction."""
    names = type_names(node, spec)
    if names is not None:
        if len({spec.identity(n) for n in names}) != len(names):
            raise ValueError('native group contains repeated faction names' if spec.by_prefix
                             else 'native group contains repeated type names')
        singles = [grouped((name,), spec) for name in names]
        result = singles[0]
        for single in singles[1:]:
            result = eq.Node('binary', '+', (result, single))
        return result
    return replace(node, args=tuple(expand_groups(child, spec) for child in node.args))


def linear_map(node, spec=TYPE_GROUPS):
    """Map lookup keys to coefficients, plus exact remaining polynomial terms."""
    types, remaining = Counter(), {}
    for monomial, coefficient in eq.expand(node).items():
        names = type_names(monomial[0], spec) if len(monomial) == 1 else None
        if names is not None:
            types[names[0]] += coefficient
        else:
            remaining[monomial] = coefficient
    return {k: v for k, v in types.items() if v}, remaining


def equivalent(original, rewritten, spec=TYPE_GROUPS):
    original, rewritten = expand_groups(original, spec), expand_groups(rewritten, spec)
    if original.kind == 'binary' and original.value in eq.COMPARISONS:
        return (rewritten.kind == 'binary' and rewritten.value == original.value
                and all(linear_map(a, spec) == linear_map(b, spec)
                        for a, b in zip(original.args, rewritten.args)))
    return linear_map(original, spec) == linear_map(rewritten, spec)


def source_spans(node, body):
    """Locate AST terms in the original bytes using the existing lexer's spans.

    Walk the already parsed tree to disambiguate unary signs and parentheses;
    XML entity offsets map back to their original spelling.
    """
    masked = eq.comment_mask(body)
    decoded, offsets, ends = [], [], []
    cursor = 0
    for match in re.finditer(r'&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);', masked):
        for index in range(cursor, match.start()):
            decoded.append(masked[index])
            offsets.append(index)
            ends.append(index + 1)
        for char in html.unescape(match[0]):
            decoded.append(char)
            offsets.append(match.start())
            ends.append(match.end())
        cursor = match.end()
    for index in range(cursor, len(masked)):
        decoded.append(masked[index])
        offsets.append(index)
        ends.append(index + 1)
    parser = eq.Parser(''.join(decoded))
    tokens = parser.tokens
    spans = {}

    def top_level(start, end):
        depth = 0
        for index in range(start, end):
            token = tokens[index]
            if token in ('(', '{'):
                depth += 1
            elif token in (')', '}'):
                depth -= 1
            elif depth == 0:
                yield index

    def visit(current, start, end):
        spans[id(current)] = (offsets[parser.spans[start][0]], ends[parser.spans[end - 1][1] - 1])
        # Peel only a pair enclosing the entire term.
        while tokens[start] == '(':
            depth, closing = 0, None
            for index in range(start, end):
                depth += (tokens[index] == '(') - (tokens[index] == ')')
                if depth == 0:
                    closing = index
                    break
            if closing != end - 1:
                break
            start, end = start + 1, end - 1
        if current.kind == 'binary':
            operators = [i for i in top_level(start, end) if tokens[i] == current.value
                         and i > start and tokens[i - 1] not in eq.PRECEDENCE
                         and tokens[i - 1] not in ('(', ',')]
            if not operators:
                raise ValueError('native-groups: cannot locate binary source span')
            split = operators[-1]
            visit(current.args[0], start, split)
            visit(current.args[1], split + 1, end)
        elif current.kind == 'neg':
            visit(current.args[0], start + 1, end)
        elif current.kind == 'call':
            commas = [i for i in top_level(start + 2, end - 1) if tokens[i] == ',']
            boundaries = [start + 1, *commas, end - 1]
            for child, left, right in zip(current.args, boundaries, boundaries[1:]):
                visit(child, left + 1, right)
    visit(node, 0, len(tokens))
    return spans


def changes(source, group_size=0, spec=TYPE_GROUPS):
    changes, reports = [], []
    text = source.decode('latin1')
    for name, original, span in eq.xml_equations(text):
        # Skip span work for equations without a possible saving.
        if eq.lookup_count(rewrite(original, group_size, spec=spec)) == eq.lookup_count(original):
            continue
        body = text[span[0]:span[1]]
        masked = eq.comment_mask(body)
        spans = source_spans(original, body)
        replacements = []

        def can_join(left, right):
            between = masked[spans[id(left)][1]:spans[id(right)][0]]
            return re.fullmatch(r'\s*[+-]\s*', between) is not None

        def emit(run, coefficient, lookup):
            # Retain the operator preceding the run, including a leading subtraction.
            coefficient *= run[0][0]
            result = lookup if coefficient == 1 else eq.Node(
                'binary', '*', (eq.Node('number', coefficient), lookup))
            rendered = eq.render(result).replace('&', '&amp;').replace('<', '&lt;')
            replacements.append((spans[id(run[0][1])][0], spans[id(run[-1][1])][1], rendered))

        rewritten = rewrite(original, group_size, emit, can_join, spec)
        before, after = eq.lookup_count(original), eq.lookup_count(rewritten)
        if before == after:
            continue
        printed = masked
        for start, end, replacement in sorted(replacements, reverse=True):
            printed = printed[:start] + replacement + printed[end:]
        printed = printed.strip()
        parsed = eq.parse(html.unescape(printed))
        if not equivalent(original, rewritten, spec) or not equivalent(original, parsed, spec):
            raise ValueError(f'{name}: native-group linear-map proof failed')
        if eq.paren_depth(printed) > eq.MAX_DEPTH:
            raise ValueError(f'{name}: nesting {eq.paren_depth(printed)} exceeds {eq.MAX_DEPTH}')
        changes.append((name, printed, span))
        reports.append(f'{name}: lookups {before} -> {after}')
    return changes, reports
