"""Synthetic perception-language and factoring regressions."""
from fractions import Fraction
import unittest

import equations as eq
import eqstats
import make_submod as make


def self_lookup(name):
    return f'Variable_Self.IsFaction {{Parameter_Faction = "{name}"}}'


def connected(name):
    return f'Variable_Target.IsConnectedTo {{Parameter_Faction = "{name}", Parameter_Attenuator = 0.0}}'


def fixture():
    """Eight invented factions, with an extra self-edge and a missing edge."""
    names = list('ABCDEFGH')
    rows = []
    for name in names:
        enemies = set(names) - {name}
        if name == 'B':
            enemies.add(name)
        if name == 'F':
            enemies.remove('C')
        rows.append('(' + ' + '.join(connected(n) for n in sorted(enemies))
                    + ') * ' + self_lookup(name))
    enemy = '(' + ' + '.join(rows) + ') > 0.0'
    own = ' + '.join(connected(n) + ' * ' + self_lookup(n) for n in names)
    return ('<?xml version="1.0"?>\r\n<Equations>\r\n<!-- outside -->\r\n'
            '<Is_Connected_To_Enemy>\r\n<!-- inside -->\r\n' + enemy
            + '\r\n</Is_Connected_To_Enemy>\r\n<Is_Connected_To_Me>' + own
            + '</Is_Connected_To_Me>\r\n<Unchanged>Variable_Target.Other</Unchanged>\r\n'
            '</Equations>\r\n').encode()


class ParserTests(unittest.TestCase):
    def test_round_trip(self):
        for comparison in ('>', '<', '>=', '<=', '==', '!='):
            text = ('-Variable_Target.Test {Z = -1.25e2, A = "two words"} * '
                    '(2 + Function_Other.Evaluate / 3) ' + comparison + ' .5')
            node = eq.parse(text)
            self.assertEqual(eq.parse(eq.render(node)), node)
        node = eq.parse('Lookup {B=0.0,A="x"}')
        self.assertEqual(node, eq.parse("Lookup {A='x',B=0e10}"))
        repeated = eq.parse('Lookup {A="first",A="second"}')
        self.assertEqual(repeated, eq.parse(eq.render(repeated)))
        self.assertNotEqual(repeated, eq.parse('Lookup {A="second",A="first"}'))

    def test_chains_print_flat(self):
        # The engine rejected 27 levels of nesting; a long sum must stay shallow.
        text = ' + '.join(f'L{i}' for i in range(40)) + ' - (A * B * C) + D'
        node = eq.parse(text)
        printed = eq.render(node)
        self.assertEqual(eq.parse(printed), node)
        self.assertLessEqual(eq.paren_depth(printed), 2)
        corrections = eq.parse(' - '.join(f'(S * L{i})' for i in range(30)))
        self.assertLessEqual(eq.paren_depth(eq.render(corrections)), 2)
        for text in ('A - (B - C) - D / (E / F)', 'A / B * C - D + E', 'A - (B + C)', '(A > B) + C'):
            node = eq.parse(text)
            self.assertEqual(eq.parse(eq.render(node)), node, text)

    def test_exact_expansion(self):
        self.assertTrue(eq.equivalent('(X + Y) * (X - Y) / 3', 'X*X/3 - Y*Y/3'))
        self.assertFalse(eq.equivalent('X*X', 'X'))
        self.assertEqual(eq.expand(eq.parse('.1 + .2')), {(): Fraction(3, 10)})
        self.assertTrue(eq.equivalent('(A+B)*C > 0', 'A*C+B*C > 0.0'))
        self.assertFalse(eq.equivalent('A > 0', 'A >= 0'))
        self.assertFalse(eq.equivalent('A > 0', 'A > 1'))
        self.assertFalse(eq.equivalent('A > 0', '2*A > 0'))

    def test_opaque_atoms_and_nonconstant_division(self):
        node = eq.parse('(X > 0) + Function_Test.Evaluate')
        self.assertEqual(len(eq.expand(node)), 2)
        self.assertEqual(eq.lookup_count(node), 1)
        with self.assertRaises(ValueError):
            eq.expand(eq.parse('1 / X'))
        with self.assertRaises(ValueError):
            eq.expand(eq.parse('1 / 0'))

    def test_statistics_language_extensions(self):
        text = ('clamp(X {Category = SyntheticType[One | Two]}, 0, 4)'
                ' + (1 # 3) + Function_Test.Evaluate')
        node = eq.parse(text)
        self.assertEqual(eq.parse(eq.render(node)), node)
        self.assertEqual(eq.lookup_count(node), 1)
        self.assertEqual(len(eq.expand(node)), 3)

    def test_bad_syntax(self):
        for text in ('X junk', 'X {A=no_quotes}', 'X @ Y', '(X', ''):
            with self.subTest(text=text), self.assertRaises(ValueError):
                eq.parse(text)

    def test_factoring_with_two_quirk_rows(self):
        source = fixture()
        output, reports = make.edit_equations(source)
        before = {n: node for n, node, _ in eq.xml_equations(source.decode())}
        after = {n: node for n, node, _ in eq.xml_equations(output.decode())}
        for name in before:
            self.assertTrue(eq.equivalent(before[name], after[name]))
        self.assertLess(eq.lookup_count(after['Is_Connected_To_Enemy']),
                        eq.lookup_count(before['Is_Connected_To_Enemy']))
        self.assertIn(b'<!-- inside -->', output)
        self.assertIn(b'<!-- outside -->', output)
        # Outside the two body spans every byte is untouched.
        def skeleton(data):
            text = data.decode()
            spans = [(a, b, 'BODY') for n, _, (a, b) in eq.xml_equations(text)
                     if n in ('Is_Connected_To_Enemy', 'Is_Connected_To_Me')]
            return make.replace_spans(text, spans)
        self.assertEqual(skeleton(source), skeleton(output))
        self.assertEqual(len(reports), 1)
        # Is_Connected_To_Me is left byte for byte; lookups keep their source text.
        body = lambda data, name: next(data.decode()[a:b] for n, _, (a, b) in eq.xml_equations(data.decode()) if n == name)
        self.assertEqual(body(source, 'Is_Connected_To_Me'), body(output, 'Is_Connected_To_Me'))
        new = body(output, 'Is_Connected_To_Enemy')
        old = ' '.join(body(source, 'Is_Connected_To_Enemy').split())
        for node in eq.walk(after['Is_Connected_To_Enemy']):
            if node.kind == 'lookup':
                self.assertIn(node.text, old)
        self.assertNotIn('- 0)', new)

    def test_missing_equation_and_unexpected_structure(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            make.edit_equations(b'<Equations><Other>X</Other></Equations>')
        original = eq.parse('X > 0')
        with self.assertRaises(ValueError):
            make.factor_enemy(original)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            eq.xml_equations('<Equations><A>X</A><A>Y</A></Equations>')


class StatisticsTests(unittest.TestCase):
    def test_recursive_counts_include_repeated_references(self):
        nodes = {name: eq.parse(text) for name, text in {
            'Leaf': 'X+Y', 'Middle': 'Function_Leaf.Evaluate + Z',
            'Root': 'Function_Middle.Evaluate + Function_Leaf.Evaluate * Function_Leaf.Evaluate',
        }.items()}
        self.assertEqual(eqstats.statistics(nodes), [('Root', 0, 7), ('Middle', 1, 3), ('Leaf', 2, 2)])

    def test_cycles_and_missing_references(self):
        for nodes in ({'A': eq.parse('Function_A.Evaluate')},
                      {'A': eq.parse('Function_B.Evaluate'), 'B': eq.parse('Function_A.Evaluate')},
                      {'A': eq.parse('Function_Missing.Evaluate')}):
            with self.assertRaises(ValueError):
                eqstats.statistics(nodes)

    def test_case_insensitive_reference_resolution(self):
        self.assertEqual(eqstats.statistics({'Leaf': eq.parse('X'),
                         'Root': eq.parse('Function_LEAF.Evaluate')}),
                         [('Leaf', 1, 1), ('Root', 0, 1)])


if __name__ == '__main__':
    unittest.main()
