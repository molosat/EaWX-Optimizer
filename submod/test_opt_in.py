"""Opt-in transforms on invented fixtures, never installed TR files."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import equations as eq
import make_submod as make
import native_groups as groups
import planet_scan as scan
from test_transforms import planet, xml


SCORING = b'''-- preface\r
function GameService()\r
\ttimer = timer + 0.1\r
\tif timer >= 40 and CampaignGame then\r
\t\t--Print_Stat_Table(TacticalKillStatsTable)\r
\t\tGameScoringMessage("GameScoring -- Galactic Stats dump.")\r
\t\tPrint_Stat_Table(GalacticKillStatsTable)\r
\t\tPrint_Build_Stats_Table(GalacticBuildStatsTable)\r
\t\tDebug_Print_Score_Vals()\r
\t\tother_statement()\r
\t\ttimer = 0\r
\tend\r
end\r
function Outside()\r
    Debug_Print_Score_Vals()\r
end\r
'''

PLUGIN = '''local galactic_plugin_update_cycle = callable {
    generic_plugin_update_cycle = generic_plugin_update_cycle,
    allowed_to_update = allowed_to_update,
    call = function(self, context)
        local target_cache = {}
        self.generic_plugin_update_cycle(context, target_cache)

        for _, planet in pairs(context.planets) do
            for _, container in ipairs(context.planet_dependent_plugin_containers) do
                local can_update = self.allowed_to_update(target_cache, container)

                if can_update then
                    container.plugin:update(planet)
                end
            end
        end
    end
}
return galactic_plugin_update_cycle
'''

KEY = '''KeyDummyLifeCycleHandler = {}
function KeyDummyLifeCycleHandler:update(planet)
    if not self:should_update() then
        return
    end

    if self.planet_cycle_index == 0 then
        self.changed_keys_for_current_cycle = self.changed_keys_for_next_cycle
        self.changed_keys_for_next_cycle = {}
    end

    self.planet_cycle_index = self.planet_cycle_index + 1
    self:process(planet)
    if self.planet_cycle_index == self.number_of_planets then
        self.last_update = GetCurrentTime()
        self.planet_cycle_index = 0
    end
end
function KeyDummyLifeCycleHandler:should_update()
    return not self.last_update or GetCurrentTime() - self.last_update > self.interval
end
function KeyDummyLifeCycleHandler:on_planet_owner_changed(planet, owner)
    self.owners[planet] = owner
    table.insert(self.ownership_calls, planet)
end
'''


class NativeGroupsTests(unittest.TestCase):
    def prove(self, text, cap=0):
        original = eq.parse(text)
        rewritten = groups.rewrite(original, cap)
        self.assertTrue(groups.equivalent(original, rewritten))
        self.assertTrue(groups.equivalent(original, eq.parse(eq.render(rewritten))))
        return rewritten

    def test_coefficients_runs_and_remaining_terms(self):
        a, b, c, d, e, f = map(planet, 'ABCDEF')
        result = self.prove(f'7 + 2*{a} + {b}*2 + X + {c}/2 + 0.5*{d} - 3*{e} - 3*{f}')
        self.assertEqual(eq.lookup_count(result), 4)
        self.assertEqual(groups.linear_map(groups.expand_groups(result))[0],
                         {'A': 2, 'B': 2, 'C': eq.Fraction(1, 2),
                          'D': eq.Fraction(1, 2), 'E': -3, 'F': -3})

    def test_caps_duplicates_and_case_aliases(self):
        text = ' + '.join(map(planet, 'ABCDE'))
        for cap, count in ((0, 1), (1, 5), (2, 3), (3, 2), (20, 1)):
            result = self.prove(text, cap)
            self.assertEqual(eq.lookup_count(result), count)
            if cap:
                self.assertTrue(all(len(groups.type_names(n) or ()) <= cap for n in eq.walk(result)))
        result = self.prove(' + '.join(map(planet, ['A', 'B', 'A', 'C', 'D', 'a'])))
        bindings = [groups.type_names(n) for n in eq.walk(result) if groups.type_names(n)]
        self.assertEqual(bindings, [('A', 'B'), ('A',), ('C', 'D'), ('a',)])

    def test_nested_sums_comparisons_and_boundaries(self):
        for text in (f'(-{planet("A")} - {planet("B")}) >= X',
                     f'X*({planet("A")} + {planet("B")}) + 9',
                     f'3 <= ({planet("A")}/3 + {planet("B")}/3)',
                     f'clamp({planet("A")} + {planet("B")}, 0, 1)'):
            self.prove(text)
        for text in (f'{planet("A")} + X + {planet("B")}',
                     f'{planet("A")} + 2*{planet("B")}',
                     f'{planet("A")} * {planet("B")}',
                     f'(X-X)*{planet("A")} + (X-X)*{planet("B")}',
                     planet('A') + ' + Variable_Target.Type.IsType {Parameter_Type="B", Extra=1}'):
            original = eq.parse(text)
            self.assertEqual(groups.rewrite(original), original)

    def test_proof_detects_bad_bindings_coefficients_and_remaining_terms(self):
        original = eq.parse(f'2*{planet("A")} + 2*{planet("B")} + X')
        for names, coefficient, tail in ((('A', 'C'), 2, 'X'), (('A', 'B'), 3, 'X'),
                                         (('A', 'B'), 2, 'Y')):
            candidate = eq.parse(f'{coefficient}*{eq.render(groups.grouped(names))} + {tail}')
            self.assertFalse(groups.equivalent(original, candidate))
        with self.assertRaisesRegex(ValueError, 'repeated'):
            groups.equivalent(original, groups.grouped(('A', 'a')))

    def test_bytes_check_copies_proof_and_depth_guards(self):
        source = xml({'Grouped': planet('A') + '+' + planet('B'), 'Untouched': ' X + 7 '})
        changes, report = groups.changes(source)
        result, _ = make.edit_bodies(source, changes, True)
        self.assertIn(b'<Untouched>\r\n<!-- inside -->\r\n X + 7 \r\n</Untouched>', result)
        self.assertIn(b'<!-- outside -->\r\n', result)
        parsed = {n: node for n, node, _ in eq.xml_equations(result.decode())}
        self.assertEqual(parsed['Alamo_Orig_Grouped'], eq.parse(planet('A') + '+' + planet('B')))
        self.assertEqual(report, ['Grouped: lookups 2 -> 1'])
        with mock.patch.object(groups, 'equivalent', side_effect=[True, False]):
            with self.assertRaisesRegex(ValueError, 'linear-map proof'):
                groups.changes(source)
        with mock.patch.object(eq, 'MAX_DEPTH', 0):
            with self.assertRaisesRegex(ValueError, 'nesting'):
                groups.changes(xml({'Weighted': '2*' + planet('A') + '+2*' + planet('B')}))
        self.assertEqual(make.edit_bodies(source, groups.changes(source, 1)[0])[0], source)
        collision = source.replace(b'</Equations>', b'<Alamo_Orig_Grouped>1</Alamo_Orig_Grouped></Equations>')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            make.edit_bodies(collision, groups.changes(collision)[0], True)

    def test_unrelated_term_spelling_entities_and_parentheses_survive(self):
        body = ('(0.000 + ' + planet('A') + ' + ' + planet('B') + ') + '
                'Variable_Target.Other {Extra = 1.00} * 2.000 + '
                '(' + planet('C') + ' + ' + planet('D') + ') &gt; 9.000')
        source = xml({'Mixed': body})
        changes, _ = groups.changes(source)
        output, _ = make.edit_bodies(source, changes, escaped=True)
        self.assertIn(b'Variable_Target.Other {Extra = 1.00} * 2.000', output)
        self.assertIn(b'0.000 + ', output)
        self.assertIn(b' &gt; 9.000', output)
        parsed = eq.xml_equations(output.decode())[0][1]
        self.assertEqual(eq.lookup_count(parsed), 3)
        self.assertTrue(groups.equivalent(eq.xml_equations(source.decode())[0][1], parsed))

    def test_source_edits_for_signed_fractional_and_nested_runs(self):
        a, b, c, d = map(planet, 'ABCD')
        for body in (f'X - 2*{a} - 2*{b} + Y',
                     f'-{a} - {b} + X',
                     f'{a}/3 + {b}/3 + X',
                     f'({a} + {b}) + {c} + {d}',
                     f'X*({a} + {b}) + Y',
                     f'clamp({a} + {b}, 0, 1)',
                     f'{a} + {b} + {a} + {c} + {d}'):
            source = xml({'E': body})
            for cap in (0, 1, 2):
                changes, _ = groups.changes(source, cap)
                output, _ = make.edit_bodies(source, changes, escaped=True)
                original = eq.xml_equations(source.decode())[0][1]
                printed = eq.xml_equations(output.decode())[0][1]
                self.assertTrue(groups.equivalent(original, printed))


class LuaEditTests(unittest.TestCase):
    def test_quiet_removes_only_exact_calls_in_service(self):
        for source in (SCORING, SCORING.replace(b'\r\n', b'\n')):
            result, reports = scan.quiet_scoring(source)
            expected = b''.join(line for line in source.splitlines(keepends=True)
                                if line.rstrip(b'\r\n').decode() not in scan.SCORING_CALLS)
            self.assertEqual(result, expected)
            self.assertEqual(len(reports), 4)
            self.assertIn('removed line 6:', reports[0])
            self.assertIn(b'    Debug_Print_Score_Vals()', result)
            self.assertIn(b'other_statement()', result)
        for source in (SCORING.replace(b'GalacticKillStatsTable', b'OtherStats'),
                       SCORING.replace(b'\t\tDebug_Print_Score_Vals()', b'\t\t--Debug_Print_Score_Vals()'),
                       SCORING.replace(b'\t\ttimer = 0', b'\t\tPrint_Stat_Table(Other)\r\n\t\ttimer = 0'),
                       SCORING + SCORING):
            with self.assertRaises(ValueError):
                scan.quiet_scoring(source)

    def test_script_spans_line_endings_and_fail_closed(self):
        for source, transform in ((PLUGIN.encode(), scan.plugin_due), (KEY.encode(), scan.keydummy_slices)):
            for newline in (b'\n', b'\r\n'):
                original = b'-- outside\n'.replace(b'\n', newline) + source.replace(b'\n', newline)
                result, _ = transform(original)
                self.assertTrue(result.startswith(b'-- outside' + newline))
                if newline == b'\r\n':
                    self.assertNotIn(b'\n', result.replace(b'\r\n', b''))
            with self.assertRaisesRegex(ValueError, 'structure'):
                transform(source.replace(b'planet)', b'changed)', 1))
            with self.assertRaisesRegex(ValueError, 'structure'):
                transform(source + source)
        result, _ = scan.keydummy_slices(KEY.encode())
        tail = KEY[KEY.index('function KeyDummyLifeCycleHandler:should_update'):].encode()
        self.assertTrue(result.endswith(tail))


class OptInBuildTests(unittest.TestCase):
    def test_preflight_all_inputs_and_leave_sources_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            tr, out = Path(folder) / 'tr', Path(folder) / 'out'
            sources = {'generated.xml': xml({'A': planet('A') + '+' + planet('B')}),
                       'basic.xml': xml({'B': '2*' + planet('C') + '+2*' + planet('D')}),
                       'score.lua': SCORING, 'plugin.lua': PLUGIN.encode(), 'key.lua': KEY.encode()}
            def pin(name):
                return Path(name), hashlib.sha256(sources[name]).hexdigest()
            files = dict(zip(('native-groups', 'quiet-scoring', 'plugin-due', 'keydummy-slices'),
                             map(pin, ('generated.xml', 'score.lua', 'plugin.lua', 'key.lua'))))
            for name, source in sources.items():
                path = tr / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(source)
            with mock.patch.object(make, 'FILES', files), mock.patch.object(make, 'EXTRA_INPUTS',
                    {'native-groups': (pin('basic.xml'),)}):
                for name in sources:
                    (tr / name).write_bytes(b'bad')
                    with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                        make.build(tr, out, only=list(files))
                    self.assertFalse(out.exists())
                    (tr / name).write_bytes(sources[name])
                with mock.patch.object(groups, 'equivalent', return_value=False):
                    with self.assertRaisesRegex(ValueError, 'linear-map proof'):
                        make.build(tr, out, only=list(files))
                    self.assertFalse(out.exists())
                report = make.build(tr, out, only=list(files), check=True, group_size=2)
                self.assertEqual({p.name for p in out.iterdir()}, set(sources))
                self.assertTrue(any('removed line' in r for r in report))
                for name, source in sources.items():
                    self.assertEqual((tr / name).read_bytes(), source)
                for name in ('generated.xml', 'basic.xml'):
                    self.assertIn(b'<Alamo_Orig_', (out / name).read_bytes())

    def test_defaults_exclude_opt_ins(self):
        with tempfile.TemporaryDirectory() as folder:
            tr, out = Path(folder) / 'tr', Path(folder) / 'out'
            source = b'function FreeStoreService()\r\nend\r\nUnitServiceRate = 40\r\n'
            relative = make.FILES['stagger'][0]
            path = tr / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(source)
            files = {k: v for k, v in make.FILES.items() if k in make.OPT_IN}
            files['stagger'] = relative, hashlib.sha256(source).hexdigest()
            with mock.patch.object(make, 'FILES', files):
                make.build(tr, out)
            self.assertEqual([p for p in out.rglob('*') if p.is_file()], [out / relative])

    def test_cli_options_and_incompatible_xml(self):
        for cap in (-1, 1.5, True, 'bad'):
            with self.assertRaisesRegex(ValueError, 'group-size'):
                make.build('tr', 'out', only=['native-groups'], group_size=cap)
        with self.assertRaisesRegex(ValueError, 'same bodies'):
            make.build('tr', 'out', only=['native-groups', 'planet-tables'])
        result = subprocess.run([sys.executable, '-I', '-B', make.__file__, '--help'], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        help_text = b''.join(result.stdout.split())
        for word in ('--group-size', 'native-groups', 'quiet-scoring', 'plugin-due', 'keydummy-slices'):
            self.assertIn(word.encode(), help_text)
        result = subprocess.run([sys.executable, '-I', '-B', make.__file__, 'tr', 'out',
                                 '--group-size', '-1'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b'Traceback', result.stderr)


LUA50 = os.environ.get('LUA50') or shutil.which('lua5.0')


@unittest.skipUnless(LUA50, 'set LUA50 to a Lua 5.0 interpreter for runtime regressions')
class LuaRuntimeTests(unittest.TestCase):
    def test_runtime_regressions(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for name, text in {'original_plugin': PLUGIN, 'original_key': KEY,
                               'due': scan.plugin_due(PLUGIN.encode())[0].decode(),
                               'sliced': scan.keydummy_slices(KEY.encode())[0].decode(),
                               'quiet': scan.quiet_scoring(SCORING)[0].decode()}.items():
                (folder / (name + '.lua')).write_text(text, encoding='ascii')
            harness = Path(__file__).with_name('opt_in_selftest.lua')
            result = subprocess.run([LUA50, str(harness)], cwd=folder, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode())


if __name__ == '__main__':
    unittest.main()
