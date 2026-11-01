"""Parse, print and prove identities in perception equations."""
from dataclasses import dataclass, field
from fractions import Fraction
import html
import json
import re


@dataclass(frozen=True)
class Node:
    kind: str
    value: object
    args: tuple = ()
    params: tuple = ()
    # Source text of a lookup or function reference, printed back verbatim so the
    # engine sees the same parameter bindings; not part of equality.
    text: str = field(default='', compare=False)


NUMBER = r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
ENUM = r'[A-Za-z_]\w*\[\s*[A-Za-z_]\w*(?:\s*\|\s*[A-Za-z_]\w*)*\s*\]'
TOKEN = re.compile(r'\s*(?:(' + NUMBER + r')|(' + ENUM + r'|[A-Za-z_][\w.]*)|'
                   r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')|'
                   r'(>=|<=|==|!=|[+*/(){}=,<>#-]))')
COMPARISONS = {'>', '<', '>=', '<=', '==', '!='}
PRECEDENCE = {**dict.fromkeys(COMPARISONS, 1), '+': 2, '-': 2, '*': 3, '/': 3, '#': 4}


class Parser:
    """A small precedence parser; unknown syntax is an error."""
    def __init__(self, text):
        self.text = text
        self.tokens, self.spans = [], []
        pos = 0
        while pos < len(text):
            if not text[pos:].strip():
                break
            match = TOKEN.match(text, pos)
            if not match:
                raise ValueError(f'bad equation syntax at {text[pos:pos+50]!r}')
            self.tokens.append(next(x for x in match.groups() if x is not None))
            self.spans.append((match.end() - len(self.tokens[-1]), match.end()))
            pos = match.end()
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, expected=None):
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            raise ValueError(f'expected {expected or "token"}, got {token!r}')
        self.pos += 1
        return token

    def expression(self, minimum=1):
        token = self.take()
        if token == '-':
            left = Node('neg', '-', (self.expression(5),))
        elif token == '(':
            left = self.expression()
            self.take(')')
        elif re.fullmatch(NUMBER, token):
            left = Node('number', Fraction(token))
        elif token == 'clamp' and self.peek() == '(':
            self.take('(')
            argument = self.expression()
            self.take(',')
            lower = self.expression()
            self.take(',')
            upper = self.expression()
            self.take(')')
            left = Node('call', token, (argument, lower, upper))
        elif re.fullmatch(r'[A-Za-z_][\w.]*', token):
            first = self.spans[self.pos - 1][0]
            params = []
            if self.peek() == '{':
                self.take('{')
                while self.peek() != '}':
                    name = self.take()
                    if not re.fullmatch(r'[A-Za-z_]\w*', name):
                        raise ValueError('invalid parameter name')
                    self.take('=')
                    sign = -1 if self.peek() == '-' else 1
                    if sign == -1:
                        self.take('-')
                    value = self.take()
                    if re.fullmatch(NUMBER, value):
                        value = ('number', sign * Fraction(value))
                    elif value.startswith(('"', "'")) and sign == 1:
                        # TR strings use literal names; also accept escaped quotes.
                        if value.startswith('"'):
                            value = ('string', json.loads(value))
                        else:
                            value = ('string', value[1:-1].replace("\\'", "'"))
                    elif re.fullmatch(ENUM, value) and sign == 1:
                        value = ('enum', re.sub(r'\s+', '', value))
                    else:
                        raise ValueError('parameter must be quoted text or a number')
                    params.append((name, value))
                    if self.peek() != ',':
                        break
                    self.take(',')
                self.take('}')
            source = ' '.join(self.text[first:self.spans[self.pos - 1][1]].split())
            left = Node('function' if token.startswith('Function_') else 'lookup',
                        token, params=tuple(sorted(params, key=lambda pair: pair[0])), text=source)
        else:
            raise ValueError(f'unexpected token {token!r}')
        while self.peek() in PRECEDENCE and PRECEDENCE[self.peek()] >= minimum:
            op = self.take()
            right = self.expression(PRECEDENCE[op] + 1)
            left = Node('binary', op, (left, right))
        return left


def parse(text):
    parser = Parser(text)
    result = parser.expression()
    if parser.peek() is not None:
        raise ValueError(f'unconsumed token {parser.peek()!r}')
    return result


def fraction_text(value):
    """Print exact finite decimals, or an exact arithmetic fraction."""
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        twos += 1
        denominator //= 2
    while denominator % 5 == 0:
        fives += 1
        denominator //= 5
    if denominator != 1:
        return f'({value.numerator} / {value.denominator})'
    places = max(twos, fives)
    scaled = value.numerator * 2 ** (places - twos) * 5 ** (places - fives)
    digits = str(abs(scaled)).zfill(places + 1)
    result = digits if places == 0 else digits[:-places] + '.' + digits[-places:]
    return ('-' if scaled < 0 else '') + result


def render(node):
    if node.kind == 'number':
        return fraction_text(node.value)
    if node.kind in ('lookup', 'function'):
        if node.text:
            return node.text
        pairs = []
        for key, (kind, value) in node.params:
            pairs.append(key + ' = ' + (json.dumps(value) if kind == 'string'
                                       else value if kind == 'enum' else fraction_text(value)))
        return node.value + (' {' + ', '.join(pairs) + '}' if pairs else '')
    if node.kind == 'neg':
        return '(-' + render(node.args[0]) + ')'
    if node.kind == 'call':
        return node.value + '(' + ', '.join(render(child) for child in node.args) + ')'
    # The engine rejects deep nesting (depth 27 failed in game, 19 loaded), so a
    # left-nested chain at one precedence level prints flat, as TR writes sums
    # (a - b + c is (a - b) + c, left-associative).
    level = next((ops for ops in (('+', '-'), ('*', '/')) if node.value in ops), None)
    parts = []
    while level and node.kind == 'binary' and node.value in level:
        parts.append(' ' + node.value + ' ' + render(node.args[1]))
        node = node.args[0]
    if not parts:
        return '(' + render(node.args[0]) + ' ' + node.value + ' ' + render(node.args[1]) + ')'
    return '(' + render(node) + ''.join(reversed(parts)) + ')'


MAX_DEPTH = 12


def paren_depth(text):
    depth = deepest = 0
    for char in text:
        depth += (char == '(') - (char == ')')
        deepest = max(deepest, depth)
    return deepest


def walk(node):
    yield node
    for child in node.args:
        yield from walk(child)


def lookup_count(node):
    return sum(item.kind == 'lookup' for item in walk(node))


def add(left, right, scale=Fraction(1)):
    result = dict(left)
    for key, value in right.items():
        result[key] = result.get(key, Fraction(0)) + scale * value
        if not result[key]:
            del result[key]
    return result


def multiply(left, right):
    result = {}
    for a, x in left.items():
        for b, y in right.items():
            # A multiset retains powers: x*x is never silently treated as x.
            key = tuple(sorted(a + b, key=repr))
            result[key] = result.get(key, Fraction(0)) + x * y
    return {key: value for key, value in result.items() if value}


def expand(node):
    """Return an exact sparse polynomial, including multilinear expressions."""
    if node.kind == 'number':
        return {(): node.value} if node.value else {}
    if node.kind in ('lookup', 'function', 'call') or node.value in COMPARISONS or node.value == '#':
        return {(node,): Fraction(1)}
    if node.kind == 'neg':
        return {key: -value for key, value in expand(node.args[0]).items()}
    left, right = map(expand, node.args)
    if node.value in ('+', '-'):
        return add(left, right, Fraction(1 if node.value == '+' else -1))
    if node.value == '*':
        return multiply(left, right)
    if node.value == '/':
        if set(right) != {()}:
            raise ValueError('polynomial division requires a nonzero constant')
        return {key: value / right[()] for key, value in left.items()}
    raise ValueError(f'cannot expand {node!r}')


def equivalent(original, rewritten):
    """Compare both sides of a comparison, without boolean assumptions."""
    if isinstance(original, str):
        original = parse(original)
    if isinstance(rewritten, str):
        rewritten = parse(rewritten)
    if original.kind == 'binary' and original.value in COMPARISONS:
        return (rewritten.kind == 'binary' and rewritten.value == original.value
                and all(expand(a) == expand(b)
                        for a, b in zip(original.args, rewritten.args)))
    return expand(original) == expand(rewritten)


def comment_mask(text):
    return re.sub(r'<!--.*?-->', lambda m: ' ' * len(m[0]), text, flags=re.S)


def xml_equations(text):
    """Return (name, expression, body span) without reserializing XML."""
    masked = comment_mask(text)
    root = re.fullmatch(r'\s*(?:<\?xml[^?]*\?>\s*)?<Equations\s*>(.*)</Equations>\s*',
                        masked, re.S)
    if not root:
        raise ValueError('expected an Equations XML root')
    pattern = re.compile(r'\s*<([A-Za-z_]\w*)\s*>(.*?)</\1\s*>', re.S)
    pos, end = root.span(1)
    result = []
    names = set()
    while masked[pos:end].strip():
        match = pattern.match(masked, pos, end)
        if not match:
            raise ValueError(f'unexpected equation XML at offset {pos}')
        name = match[1]
        if name in names:
            raise ValueError(f'duplicate equation {name}')
        names.add(name)
        body = html.unescape(match[2])
        try:
            node = parse(body)
        except ValueError as exc:
            raise ValueError(f'{name}: {exc}') from exc
        result.append((name, node, match.span(2)))
        pos = match.end()
    return result
