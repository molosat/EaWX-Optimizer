from fractions import Fraction
import unittest
from unittest import mock

import common_factors as cf
import equations as eq

E = 'Function_Enemy.Evaluate'
S = 'Function_Self.Evaluate'
DEFINITIONS = {name: eq.parse(' + '.join(f'Variable_Target.L{i}' for i in range(size)))
               for name, size in (('Enemy', 50), ('Self', 30))}


class CommonFactorTests(unittest.TestCase):
    def setUp(self):
        self.cost = cf.costs(DEFINITIONS)

    def test_repeated_calls_evaluate_once(self):
        original = eq.parse(f'2 * {E} + A * {S} * {E} + B * {S} * {E} + 2 * C * {S} * {E} + D')
        factored = cf.rewrite(original, self.cost)
        self.assertEqual(eq.expand(factored), eq.expand(original))
        calls = [n.value for n in eq.walk(factored) if n.kind == 'function']
        self.assertEqual(calls.count('Function_Enemy.Evaluate'), 1)
        self.assertEqual(calls.count('Function_Self.Evaluate'), 1)
        self.assertLess(cf.weighted(factored, self.cost), cf.weighted(original, self.cost) - 100)

    def test_unsafe_or_small_rewrites_are_refused(self):
        self.assertIsNone(cf.rewrite(eq.parse(f'{E} * A + {E} * B > 1'), self.cost))
        self.assertIsNone(cf.rewrite(eq.parse(f'{E} * (0 # 1) + {E} * B'), self.cost))
        self.assertIsNone(cf.rewrite(eq.parse('X * A + X * B'), self.cost))

    def test_costs_handle_unknown_names_and_cycles(self):
        cost = cf.costs({'A': eq.parse('Function_B.Evaluate + V'), 'B': eq.parse('Function_A.Evaluate')})
        self.assertGreaterEqual(cost(eq.parse('Function_A.Evaluate')), 1)
        self.assertEqual(cost(eq.parse('Function_Missing.Evaluate')), 1)

    def test_output_does_not_depend_on_hash_order(self):
        original = eq.parse(f'{E} * A + {E} * B + {S} * A + {S} * B')
        first = eq.render(cf.rewrite(original, self.cost))
        with mock.patch.object(cf, 'horner', wraps=cf.horner):
            again = eq.render(cf.rewrite(eq.parse(f'{S} * B + {E} * B + {S} * A + {E} * A'), self.cost))
        self.assertEqual(first, again)

    def test_failed_proof_raises(self):
        with mock.patch.object(cf, 'horner', return_value=eq.Node('number', Fraction(0))):
            with self.assertRaisesRegex(ValueError, 'exact proof'):
                cf.rewrite(eq.parse(f'{E} * A + {E} * B'), self.cost)


if __name__ == '__main__':
    unittest.main()
