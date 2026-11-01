"""Synthetic faction matrices and planet tables; no installed mod required."""
from fractions import Fraction
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import equations as eq
import eqstats
import make_submod as make
import planet_tables as planets


def lookup(variable, name):
    return f'Variable_{variable}.IsFaction {{Parameter_Faction = "{name}"}}'


def matrix(rows, tail=''):
    return ' + '.join(f'{c} * {lookup("Self", a)} * {lookup("Target", b)}'
                      for a, values in rows.items() for b, c in values.items()) + tail


def planet(name):
    return f'Variable_Target.Type.IsType {{Parameter_Type = "{name}"}}'


def xml(definitions):
    return ('<Equations>\r\n<!-- outside -->\r\n' + ''.join(
        f'<{n}>\r\n<!-- inside -->\r\n{body}\r\n</{n}>\r\n'
        for n, body in definitions.items()) + '</Equations>\r\n').encode()


class FactoringTests(unittest.TestCase):
    def prove(self, text):
        original = eq.parse(text)
        result = make.factor_factions(original)
        self.assertIsNotNone(result)
        self.assertTrue(eq.equivalent(original, result))
        self.assertTrue(eq.equivalent(original, eq.parse(eq.render(result))))
        self.assertLess(eq.lookup_count(result), eq.lookup_count(original))
        for node in eq.walk(result):
            if node.kind == 'lookup':
                self.assertIn(node.text, text)
        return result

    def test_same_token_different_variables_missing_extra_and_absent_row(self):
        names = 'ABCDEFGH'
        rows = {a: {b: 1 for b in names if b != a} for a in names[:-1]}
        rows['B']['B'] = 2  # extra, with a non-unit coefficient
        del rows['F']['C']  # missing
        text = matrix(rows, ' + 3 * ' + lookup('Self', 'H') + ' - 2')
        result = self.prove('(' + text + ') >= 7')
        # Direct grouping would still need over 50 lookups; complement wins.
        self.assertLess(eq.lookup_count(result), 50)
        self.prove('7 <= (' + text + ')')

    def test_constant_coefficients_and_linear_terms(self):
        rows = {a: {b: Fraction(2, 3) for b in 'WXYZ'} for a in 'ABCD'}
        result = self.prove(matrix(rows, ' + 0.25 * ' + lookup('Target', 'W') + ' + 9'))
        self.assertEqual(eq.lookup_count(result), 9)

    def test_direct_grouping_wins_and_no_saving_is_unchanged(self):
        rows = {'A': {'X': 2, 'Y': -3, 'Z': 4}, 'B': {'X': 7}}
        result = self.prove(matrix(rows))
        self.assertEqual(eq.lookup_count(result), 6)
        original = eq.parse(matrix({'A': {'X': 1}, 'B': {'Y': 1}}))
        self.assertIs(make.factor_factions(original), original)

    def test_three_family_column_bundle_retains_mismatched_factions(self):
        terms = []
        for a in 'ABCDEFGH':
            for b in 'ABCDEFGH':
                if a != b:
                    # Deliberate mismatch: Human(H) pairs with Target(G).
                    target = 'G' if b == 'H' else b
                    terms.append(lookup('Self', a) + '*' + lookup('Human', b)
                                 + '*' + lookup('Target', target))
        self.prove(' + '.join(terms) + ' > 0')

    def test_nonfamilies_and_nonpolynomials_do_not_fit(self):
        for text in ('X*Y', '1 / X > 0', 'X > 1 / Y',
                     lookup('Self', 'A') + '*' + lookup('Self', 'B'),
                     lookup('Self', 'A') + '*(' + lookup('Target', 'B') + ' > 0)'):
            self.assertIsNone(make.factor_factions(eq.parse(text)))
        text = matrix({'A': {'X': 1, 'Y': 1}})
        # A different non-faction parameter is a different family.
        text += ' + ' + lookup('Self', 'B') + '*Variable_Target.IsFaction {Parameter_Faction="X", Extra=1}'
        self.assertIsNone(make.factor_factions(eq.parse(text)))


EVALUATOR_SOURCE = b'require("PGBaseDefinitions")\nfunction Evaluate(flag)\n    return 0.0\nend\n'


def pinned_evaluator(tr):
    """Write a stand-in for TR's evaluator and pin the build to it."""
    path = Path(tr) / make.LUA_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(EVALUATOR_SOURCE)
    return mock.patch.object(make, 'EVALUATOR_INPUT',
                             (make.LUA_PATH, hashlib.sha256(EVALUATOR_SOURCE).hexdigest()))


class SmallFixtures(unittest.TestCase):
    # The fixtures' tables are smaller than the shipping minimum.
    def setUp(self):
        patch = mock.patch.object(planets, 'MIN_ENTRIES', 1)
        patch.start()
        self.addCleanup(patch.stop)


class PlanetTests(SmallFixtures):
    def test_small_tables_stay_equations_by_default(self):
        with mock.patch.object(planets, 'MIN_ENTRIES', 8):
            self.assertEqual(planets.find_tables({'A': eq.parse(planet('Alpha'))}), {})
    def tables(self):
        return planets.find_tables({n: eq.parse(t) for n, t in {
            'Small': '2 + 3*' + planet('Alpha') + ' - ' + planet('Beta') + ' + ' + planet('Alpha'),
            'Combined': '2*Function_SMALL.Evaluate + ' + planet('Gamma'),
            'Constant': '7', 'Other': 'Variable_Target.BaseIncome',
            'Product': planet('Alpha') + '*' + planet('Beta'),
            'BadDivision': planet('Alpha') + '/Variable_Target.BaseIncome',
        }.items()})

    def test_nonunit_coefficients_default_and_inlined_reference(self):
        tables = self.tables()
        self.assertEqual(set(tables), {'Small', 'Combined'})
        self.assertEqual(tables['Small'][1:], (2, {'ALPHA': 6, 'BETA': 1}))
        self.assertEqual(tables['Combined'][1:], (4, {'ALPHA': 12, 'BETA': 2, 'GAMMA': 5}))

    def test_case_aliases_fail_even_if_they_cancel(self):
        for text in (planet('Alpha') + ' + ' + planet('ALPHA'),
                     planet('Alpha') + ' - ' + planet('Alpha') + ' + ' + planet('ALPHA')):
            with self.assertRaisesRegex(ValueError, 'case-ambiguous'):
                planets.find_tables({'Bad': eq.parse(text)})

    def test_case_aliases_across_references(self):
        with self.assertRaisesRegex(ValueError, 'case-ambiguous'):
            planets.find_tables({'A': eq.parse(planet('Alpha')),
                                 'B': eq.parse('Function_A.Evaluate + ' + planet('ALPHA'))})

    def test_reference_cycles_and_missing_references_do_not_fit(self):
        self.assertEqual(planets.find_tables({'A': eq.parse('Function_B.Evaluate'),
                                             'B': eq.parse('Function_A.Evaluate'),
                                             'C': eq.parse('Function_Missing.Evaluate')}), {})

    def test_generated_lua_extends_the_evaluator(self):
        tables = {'Small': self.tables()['Small']}
        original = EVALUATOR_SOURCE.replace(b'\n', b'\r\n')
        lua = planets.generate_lua(tables, original)
        self.assertTrue(lua.startswith(original))
        self.assertNotIn(b'\n', lua.replace(b'\r\n', b''))
        self.assertEqual(lua[len(original):].decode().replace('\r\n', '\n'), '''
-- Alamo lag-fix layer: planet tables proved from SHA-pinned perception equations.
local planet_tables = {
    ["Alamo_Small"] = { default = 2, values = {
        ["ALPHA"] = 6,
        ["BETA"] = 1,
    } },
}

local alamo_original_evaluate = Evaluate

function Evaluate(name)
    local data = planet_tables[name]
    if data == nil then
        return alamo_original_evaluate(name)
    end
    object = Target.Get_Game_Object()
    if not TestValid(object) then
        return 0.0
    end
    local value = data.values[string.upper(object.Get_Type().Get_Name())]
    if value == nil then
        return data.default
    end
    return value
end
''')
        with self.assertRaisesRegex(ValueError, 'evaluator structure'):
            planets.generate_lua(tables, b'-- not an evaluator')
        self.assertEqual(planets.script_call('Small').params,
                         (('Parameter_Script_String', ('string', 'Alamo_Small')),))
        self.assertEqual(planets.lua_string('a\x00b"\\'), '"a\\000b\\"\\\\"')
        self.assertEqual(planets.lua_number(Fraction(1, 3)), '(1 / 3)')

    def test_body_spans_comments_and_check_copies(self):
        source = xml({'Small': planet('Alpha') + '+ 2*' + planet('Beta'), 'Unchanged': '7'})
        tables = planets.find_tables({n: node for n, node, _ in eq.xml_equations(source.decode())})
        changes, reports = planets.changes(source, tables)
        output, copies = make.edit_bodies(source, changes, True)
        parsed = {n: node for n, node, _ in eq.xml_equations(output.decode())}
        self.assertEqual(parsed['Small'], planets.script_call('Small'))
        self.assertEqual(parsed['Alamo_Orig_Small'], tables['Small'][0])
        self.assertIn(b'<Unchanged>\r\n<!-- inside -->\r\n7\r\n</Unchanged>', output)
        self.assertEqual(output.count(b'<!-- inside -->'), 3)
        self.assertIn('2 entries', reports[0])
        self.assertIn('check copies', copies[0])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            make.edit_bodies(output, planets.changes(output, {'Small': tables['Small']})[0], True)

    def test_script_counts_once_in_expanded_statistics(self):
        nodes = {'Small': planets.script_call('Small'),
                 'Caller': eq.parse('Function_Small.Evaluate + Script_Other.Evaluate + X')}
        self.assertEqual(eqstats.statistics(nodes), [('Caller', 2, 3), ('Small', 1, 1)])


class ComponentTests(SmallFixtures):
    def test_new_components_validate_all_inputs_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tr, out = root / 'tr', root / 'out'
            sources = {'factor.xml': xml({'Pair': matrix({'A': {'X': 1, 'Y': 1}})}),
                       'offensive.xml': xml({'Other': matrix({'B': {'X': 1, 'Y': 1}})}),
                       'generated.xml': xml({'Leaf': '3*' + planet('Alpha')}),
                       'basic.xml': xml({'Root': '2*Function_Leaf.Evaluate'})}
            for relative, data in sources.items():
                path = tr / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            def pinned(relative):
                return Path(relative), hashlib.sha256(sources[relative]).hexdigest()
            files = {'factoring': pinned('factor.xml'), 'planet-tables': pinned('generated.xml')}
            extra = {'factoring': (pinned('offensive.xml'),),
                     'planet-tables': (pinned('basic.xml'),)}
            with mock.patch.object(make, 'FILES', files), mock.patch.object(make, 'EXTRA_INPUTS', extra), \
                    pinned_evaluator(tr):
                (tr / 'basic.xml').write_bytes(b'bad')
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    make.build(tr, out, only=list(files))
                self.assertFalse(out.exists())
                (tr / 'basic.xml').write_bytes(sources['basic.xml'])
                make.build(tr, out, only=list(files), check=True)
                self.assertTrue((out / make.LUA_PATH).is_file())
                for relative, source in sources.items():
                    self.assertEqual((tr / relative).read_bytes(), source)
                    parsed = {n: node for n, node, _ in eq.xml_equations((out / relative).read_bytes().decode())}
                    name = next(n for n in parsed if not n.startswith(make.CHECK_PREFIX))
                    self.assertIn(make.CHECK_PREFIX + name, parsed)
                lua = (out / make.LUA_PATH).read_bytes()
                self.assertTrue(lua.startswith(EVALUATOR_SOURCE))
                self.assertIn(b'["Alamo_Root"]', lua)
                (tr / make.LUA_PATH).write_bytes(EVALUATOR_SOURCE + b'-- edited')
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    make.build(tr, root / "out2", only=list(files))

    def test_planet_serialization_failure_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tr, out = root / 'tr', root / 'out'
            tr.mkdir()
            data = xml({'Small': planet('Alpha')})
            relative = Path('generated.xml')
            (tr / relative).write_bytes(data)
            files = {'planet-tables': (relative, hashlib.sha256(data).hexdigest())}
            with mock.patch.object(make, 'FILES', files), mock.patch.object(make, 'EXTRA_INPUTS', {}), \
                    pinned_evaluator(tr):
                with mock.patch.object(planets, 'lua_number', side_effect=ValueError('proof failed')):
                    with self.assertRaisesRegex(ValueError, 'proof failed'):
                        make.build(tr, out, only=list(files))
                self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
