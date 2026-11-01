"""Faction grouping and build composition on small invented inputs."""
import hashlib
import itertools
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock

import equations as eq
import make_submod as make
import native_groups as groups
from test_transforms import lookup, matrix, planet, xml


SPEC = groups.FACTION_GROUPS


class FactionGroupsTests(unittest.TestCase):
    def transform(self, body, cap=0):
        source = xml({'Test': body, 'Untouched': ' X + 7 '})
        changes, reports = groups.changes(source, cap, SPEC)
        output, _ = make.edit_bodies(source, changes, escaped=True)
        self.assertIn(b'<Untouched>\r\n<!-- inside -->\r\n X + 7 \r\n</Untouched>', output)
        node = dict((n, v) for n, v, _ in eq.xml_equations(output.decode()))['Test']
        self.assertTrue(groups.equivalent(eq.parse(body), node, SPEC))
        return node, output, reports

    def test_basic_merge_and_first_appearance(self):
        body = ' + '.join(lookup('Self', n) for n in ('Z', 'B', 'A'))
        node, _, report = self.transform(body)
        self.assertEqual(SPEC.names(node), tuple(('Variable_Self.IsFaction', n) for n in ('Z', 'B', 'A')))
        self.assertEqual(report, ['Test: lookups 3 -> 1'])

    def test_repeated_names_and_prefix_boundaries(self):
        body = ' + '.join(lookup('Self', n) for n in ('A', 'B', 'A', 'C', 'D', 'a'))
        node, _, _ = self.transform(body)
        self.assertEqual([tuple(n[1] for n in SPEC.names(v)) for v in eq.walk(node) if SPEC.names(v)],
                         [('A', 'B'), ('A',), ('C', 'D'), ('a',)])
        node, _, _ = self.transform(' + '.join(lookup(p, n) for p, n in
                                             [('Self', 'A'), ('Target', 'B'), ('Target', 'C')]))
        self.assertEqual(eq.lookup_count(node), 2)
        self.assertEqual(groups.linear_map(groups.expand_groups(node, SPEC), SPEC)[0],
                         {('Variable_Self.IsFaction', 'A'): 1,
                          ('Variable_Target.IsFaction', 'B'): 1,
                          ('Variable_Target.IsFaction', 'C'): 1})
        node, _, _ = self.transform('Other.Owner.IsFaction {Parameter_Faction="A"} + '
                                   'Other.Owner.IsFaction {Parameter_Faction="B"}')
        self.assertEqual(node.value, 'Other.Owner.IsFaction')

    def test_coefficients_subtraction_and_caps(self):
        a, b, c, d = (lookup('Self', n) for n in 'ABCD')
        node, _, _ = self.transform(f'7 - 2*{a} - {b}*2 + {c}/2 + 0.5*{d}')
        self.assertEqual(eq.lookup_count(node), 2)
        for body in (f'{a} + 2*{b}', f'{a} - {b}', f'{a} + X + {b}',
                     f'{a} * {b}',
                     'P.HasUnit {Parameter_Faction="A"} + P.HasUnit {Parameter_Faction="B"}'):
            _, output, report = self.transform(body)
            self.assertEqual(output, xml({'Test': body, 'Untouched': ' X + 7 '}))
            self.assertEqual(report, [])
        body = ' + '.join(lookup('Target', n) for n in 'ABCDE')
        for cap, count in ((0, 1), (1, 5), (2, 3), (3, 2)):
            node, _, _ = self.transform(body, cap)
            self.assertEqual(eq.lookup_count(node), count)

    def test_independent_proof_checks_path_and_printed_output(self):
        original = eq.parse(lookup('Self', 'A') + '+' + lookup('Self', 'B'))
        wrong = eq.parse(lookup('Target', 'A') + '+' + lookup('Target', 'B'))
        self.assertFalse(groups.equivalent(original, wrong, SPEC))
        with mock.patch.object(groups, 'equivalent', side_effect=[True, False]):
            with self.assertRaisesRegex(ValueError, 'linear-map proof'):
                groups.changes(xml({'Test': eq.render(original)}), spec=SPEC)

    def test_native_output_unchanged(self):
        source = xml({'Test': '2*' + planet('A') + ' + 2*' + planet('B')})
        changes, report = groups.changes(source)
        self.assertEqual(report, ['Test: lookups 2 -> 1'])
        self.assertEqual(changes[0][1], '(2 * Variable_Target.Type.IsType '
                         '{Parameter_Type = "A", Parameter_Type = "B"})')
        self.assertEqual(groups.changes(source, spec=SPEC), ([], []))

    def test_build_composition_checks_pins_and_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tr = root / 'tr'
            basic, offensive = make.FILES['factoring'][0], make.FILES['equations'][0]
            defensive = make.FILES['common-factors'][0]
            bodies = {'Rectangle': matrix({'A': {'C': 1, 'D': 1}, 'B': {'C': 1, 'D': 1}}),
                      'Singles': lookup('Self', 'E') + '+' + lookup('Self', 'F'),
                      'Untouched': 'X + 7',
                      'Costly': ' + '.join(f'Variable_Target.L{i}' for i in range(22))}
            sources = {basic: xml(bodies), offensive: xml({'Other': bodies['Singles']}),
                       defensive: xml({'Repeated': 'Function_Costly.Evaluate*Y + Function_Costly.Evaluate*Z'})}
            pins = {}
            for path, source in sources.items():
                target = tr / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source)
                pins[path] = (path, hashlib.sha256(source).hexdigest())
            files = {'factoring': pins[basic], 'equations': pins[offensive],
                     'faction-groups': pins[basic], 'common-factors': pins[defensive]}
            extra = {'factoring': (pins[offensive],), 'faction-groups': (pins[offensive],),
                     'common-factors': (pins[basic], pins[offensive])}
            with mock.patch.object(make, 'FILES', files), mock.patch.object(make, 'EXTRA_INPUTS', extra):
                selections = [('faction-groups',)]
                for other in ('factoring', 'common-factors'):
                    selections.extend(itertools.permutations((other, 'faction-groups')))
                selections.extend(itertools.permutations(
                    ('factoring', 'common-factors', 'faction-groups')))
                for selection in selections:
                    out = root / 'out'
                    make.build(tr, out, only=selection, check=True)
                    nodes = {n: v for n, v, _ in eq.xml_equations((out / basic).read_text())}
                    self.assertEqual(eq.lookup_count(nodes['Singles']), 1)
                    self.assertEqual(nodes['Alamo_Orig_Singles'], eq.parse(bodies['Singles']))
                    if 'factoring' in selection:
                        self.assertEqual(eq.lookup_count(nodes['Rectangle']), 2)
                        self.assertEqual(nodes['Alamo_Orig_Rectangle'], eq.parse(bodies['Rectangle']))
                    self.assertNotIn('Alamo_Orig_Untouched', nodes)
                    self.assertEqual((tr / basic).read_bytes(), sources[basic])
                make.build(tr, root / 'default')
                default = (root / 'default' / basic).read_bytes()
                self.assertIn(bodies['Singles'].encode(), default)
                make.build(tr, root / 'cap', only=['faction-groups'], group_size=1)
                self.assertEqual((root / 'cap' / basic).read_bytes(), sources[basic])
                with mock.patch.object(groups, 'equivalent', return_value=False):
                    with self.assertRaisesRegex(ValueError, 'linear-map proof'):
                        make.build(tr, root / 'refused', only=['faction-groups'])
                    self.assertFalse((root / 'refused').exists())
                (tr / offensive).write_bytes(sources[offensive] + b'!')
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    make.build(tr, root / 'bad-pin', only=['faction-groups'])
                self.assertFalse((root / 'bad-pin').exists())

    def test_cli_help(self):
        result = subprocess.run([sys.executable, '-I', '-B', make.__file__, '--help'],
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'faction-groups', result.stdout)
