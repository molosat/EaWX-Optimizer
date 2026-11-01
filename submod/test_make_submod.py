"""Synthetic build, byte preservation and destination safety tests."""
import hashlib
import itertools
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import make_submod as make
import eqstats
from test_equations import fixture


TAG = 'Galactic_AI_Goal_Cycle_Sleep_Duration'


def sleep_fixture():
    return ('<Root>\r\n<!-- preserve me -->\r\n' + ''.join(
        f'<Difficulty_Adjustment Name="{name}"><{TAG}>  {index}.0\t</{TAG}>'
        '<Other> unchanged </Other></Difficulty_Adjustment>\r\n'
        for index, name in enumerate(('Easy_Default', *make.SLEEP_NAMES, 'Other')))
        + '</Root>\r\n').encode()


def free_store_fixture():
    return b'''UnitServiceRate = 40
function FreeStoreService()
    On_Unit_Service(unit)
end
function On_Unit_Service(object)
    if object.Is_Category("Structure") then
        return false
    end
    if FreeStore.Is_Unit_Safe(object) == false or
        (object.Get_Type().Is_Hero() and not object.Is_Category("NonCombatHero")) then
        MoveUnit(object)
        return
    end
end
function Find_Ground_Unit_Target(object)
    return FindTarget.Reachable_Target(player, score, kind, reach, probability, object)
end
function Find_Space_Unit_Target(object)
end
'''


class HeroCadenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tr = self.root / 'tr'
        self.relative = make.stagger.SCRIPT
        self.source = free_store_fixture()
        self.path = self.tr / self.relative
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(self.source)
        self.components = ('stagger', 'search-memo', 'hero-cadence')
        pinned = (self.relative, hashlib.sha256(self.source).hexdigest())
        patch = mock.patch.object(make, 'FILES', dict.fromkeys(self.components, pinned))
        patch.start()
        self.addCleanup(patch.stop)

    def test_alone_and_every_combination_in_every_order(self):
        for newline in (b'\n', b'\r\n'):
            source = self.source.replace(b'\n', newline)
            self.path.write_bytes(source)
            pinned = (self.relative, hashlib.sha256(source).hexdigest())
            with mock.patch.object(make, 'FILES', dict.fromkeys(self.components, pinned)):
                for count in range(1, 4):
                    for selected in itertools.permutations(self.components, count):
                        if 'hero-cadence' not in selected:
                            continue
                        with self.subTest(selected=selected, newline=newline):
                            out = self.root / 'out'
                            reports = make.build(self.tr, out, only=selected)
                            script = (out / self.relative).read_bytes()
                            blocks = (make.STAGGER if 'stagger' in selected else '')
                            if 'search-memo' in selected:
                                blocks += make.SEARCH_MEMO % {'check': 'false'}
                            blocks += make.HERO_CADENCE
                            self.assertEqual(script, source + blocks.encode().replace(b'\n', newline))
                            self.assertEqual(script.count(b'-- Alamo lag-fix layer (hero-cadence)'), 1)
                            self.assertEqual(sum('hero-cadence:' in r for r in reports), 1)
                            self.assertEqual(sum('from TR sha256' in r for r in reports), 1)
                            self.assertEqual(self.path.read_bytes(), source)

    def test_default_selection_excludes_hero_cadence(self):
        out = self.root / 'default'
        make.build(self.tr, out)
        expected = make.STAGGER + make.SEARCH_MEMO % {'check': 'false'}
        self.assertEqual((out / self.relative).read_bytes(), self.source + expected.encode())

    def test_refuses_missing_required_structure_before_writing(self):
        required = (b'function On_Unit_Service(object)', b'function FreeStoreService()',
                    b'not object.Is_Category("NonCombatHero")')
        for missing in required:
            source = self.source.replace(missing, b'-- missing')
            self.path.write_bytes(source)
            pinned = (self.relative, hashlib.sha256(source).hexdigest())
            with mock.patch.object(make, 'FILES', dict.fromkeys(self.components, pinned)):
                for selected in (('hero-cadence',), self.components, self.components[::-1]):
                    with self.subTest(missing=missing, selected=selected):
                        out = self.root / 'refused'
                        with self.assertRaisesRegex(ValueError, 'unexpected free-store script structure'):
                            make.build(self.tr, out, only=selected)
                        self.assertFalse(out.exists())

    def test_lua50_and_service_guards(self):
        block = make.HERO_CADENCE
        for unsupported in ('%', '#', 'math.floor', 'GlobalValue', 'string.gmatch', '[=['):
            self.assertNotIn(unsupported, block)
        self.assertLess(block.index('object.Is_Category("Structure")'),
                        block.index('object.Get_Type().Is_Hero()'))
        # Non-heroes skip the safety check here; TR's On_Unit_Service runs it for them.
        self.assertLess(block.index('object.Get_Type().Is_Hero()'),
                        block.index('FreeStore.Is_Unit_Safe(object) ~= false'))
        self.assertIn('and not object.Is_Category("NonCombatHero")', block)
        # The pass flag toggles and each type's parity is cached, so the per-unit
        # cost stays constant however long the campaign runs.
        self.assertIn('AlamoHeroPass = 1 - AlamoHeroPass\n'
                      '    return AlamoHero_TR_FreeStoreService()', block)
        self.assertIn('AlamoHeroParity[name] = parity', block)
        self.assertIn('return AlamoHero_TR_On_Unit_Service(object)', block)
        self.assertIn('if AlamoHeroPass ~= Alamo_Hero_Parity(object.Get_Type().Get_Name()) then\n'
                      '            MoveUnit(object)\n        end\n        return', block)


class SearchMemoTests(unittest.TestCase):
    def test_key_holds_unit_type_and_check_returns_real(self):
        block = make.SEARCH_MEMO % {'check': 'true'}
        # Reachable_Target receives the searching unit, so unit types never share a result.
        self.assertIn('origin.Get_Type().Get_Name() .. "|" .. source.Get_Type().Get_Name()', block)
        self.assertIn('AlamoMemoMismatches = AlamoMemoMismatches + 1\n            return real', block)


class MoveGuardsTests(unittest.TestCase):
    TR_SCRIPT = Path(os.environ.get('TR_FOLDER', 'TR-not-set')) / Path('Data/Scripts/FreeStore/GalacticFreeStore.lua')

    def test_lua50_and_guards(self):
        block = make.MOVE_GUARDS
        for unsupported in ('%d', '#', 'math.floor', 'GlobalValue', 'string.gmatch', '[=['):
            self.assertNotIn(unsupported, block)
        # The same-planet guard comes before the order and still reports a move.
        self.assertLess(block.index('there == here'),
                        block.index('FreeStore.Move_Object(object, dest_target)'))
        self.assertIn('TestValid(here)', block)
        # Planet objects from the ground and space finders have no Get_Game_Object.
        self.assertIn('pcall(function() return dest_target.Get_Game_Object() end)', block)
        self.assertIn('if not unwrapped then\n            there = dest_target', block)
        self.assertIn('FreeStore.Is_Unit_In_Transit(object) == false then\n            return true', block)
        self.assertIn('FreeStore.Is_Unit_In_Transit(object) then\n        return\n    end\n'
                      '    return AlamoGuard_TR_On_Unit_Added(object)', block)

    def test_move_unit_is_tr_body_plus_guard(self):
        if not self.TR_SCRIPT.exists():
            self.skipTest('TR is not installed here')
        tr = self.TR_SCRIPT.read_text(encoding='latin1').replace('\r\n', '\n')
        start = tr.index('function MoveUnit(object)')
        original = tr[start:tr.index('\nend\n', start) + 5]
        block = make.MOVE_GUARDS
        start = block.index('function MoveUnit(object)')
        copy = block[start:block.index('\nend\n', start) + 5]
        guard = block[block.index('        -- Still counts as a move'):block.index('        FreeStore.Move_Object')]
        self.assertEqual(copy.replace(guard, ''), original)


class OrderCapTests(unittest.TestCase):
    RUNNER = Path(__file__).resolve().parents[1] / 'build-lua-selftest/runner/Debug/helpers_selftest.exe'
    # Stubs for the engine calls the block uses, then the block, then the checks.
    HARNESS = '''
local failures = {}
local function check(ok, message) if not ok then table.insert(failures, message) end end
NOW = 1
function GetCurrentTime() return NOW end
UNSAFE = {}
FreeStore = {Is_Unit_Safe = function(object) return not UNSAFE[object] end}
MOVED = {}
function MoveUnit(object) table.insert(MOVED, object) return true end
function On_Unit_Added(object) return MoveUnit(object) end
%(block)s
UNSAFE.u4 = true
local r = {}
for i = 1, 5 do r[i] = MoveUnit("u" .. i) end
check(r[1] and r[2] and r[3], "the first three calls move")
check(r[4] == true, "an unsafe unit over the cap still moves")
check(r[5] == false, "a safe unit over the cap does not move")
check(table.getn(MOVED) == 4, "four units reached the original MoveUnit")
check(AlamoDiagCapCalls == 4 and AlamoDiagCapExempt == 1 and AlamoDiagCapSkipService == 1,
      "frame one counters")
NOW = 2
check(MoveUnit("v1") == true, "a new frame starts a new count")
MoveUnit("v2")
MoveUnit("v3")
check(On_Unit_Added("a1") == false, "an added unit over the cap does not move")
check(AlamoDiagCapSkipAdded == 1 and AlamoCapAdded == false, "added skips are counted apart")
check(AlamoDiagCapFrames1 == 1, "frame one, four calls, is filed in the 1-4 bucket")
NOW = 3
MoveUnit("w1")
check(AlamoDiagCapFrames1 == 2, "frame two, three calls, is filed when frame three starts")
return {failures = failures}
'''

    def test_lua50_and_order(self):
        block = make.ORDER_CAP % {'cap': 12}
        for unsupported in ('%d', '#', 'math.floor', 'GlobalValue', 'string.gmatch', '[=['):
            self.assertNotIn(unsupported, block)
        # Unsafe units are checked only once the cap is reached, and never skipped.
        self.assertLess(block.index('AlamoCapCount >= AlamoOrderCap'),
                        block.index('FreeStore.Is_Unit_Safe(object) == false'))
        self.assertIn('AlamoOrderCap = 12', block)

    def test_block_wraps_last(self):
        with tempfile.TemporaryDirectory() as folder:
            tr, out = Path(folder) / 'tr', Path(folder) / 'out'
            source = (b'function FreeStoreService()\nend\nUnitServiceRate = 40\nfunction MoveUnit(object)\n'
                      b'dest_target = Find_Custom_Target(object)\nFreeStore.Move_Object(object, dest_target)\n'
                      b'function On_Unit_Added(object)\nif MoveUnit(object) then\nfunction On_Unit_Service(object)\n'
                      b'not object.Is_Category("NonCombatHero")\n')
            relative = make.FILES['order-cap'][0]
            (tr / relative).parent.mkdir(parents=True)
            (tr / relative).write_bytes(source)
            files = {name: (relative, hashlib.sha256(source).hexdigest())
                     for name in ('stagger', 'hero-cadence', 'move-guards', 'order-cap')}
            with mock.patch.object(make, 'FILES', files):
                reports = make.build(tr, out, only=['order-cap', 'move-guards', 'hero-cadence'], order_cap=7)
            script = (out / relative).read_text()
            self.assertGreater(script.index('(order-cap)'), script.index('(move-guards)'))
            self.assertGreater(script.index('(order-cap)'), script.index('(hero-cadence)'))
            self.assertIn('AlamoOrderCap = 7', script)
            self.assertTrue(any('order-cap: appended a cap of 7' in r for r in reports))
        for bad in (0, -1, '3.5', True):
            with self.assertRaises(ValueError):
                make.order_cap_value(bad)

    def test_runs_in_lua50(self):
        if not self.RUNNER.exists():
            self.skipTest('32-bit Debug Lua 5.0 runner not built')
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder) / 'first.lua', Path(folder) / 'cap.lua'
            first.write_text('return {}\n')
            second.write_text(self.HARNESS % {'block': make.ORDER_CAP % {'cap': 3}})
            result = subprocess.run([str(self.RUNNER), str(first), str(second), 'general'],
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('0 failures', result.stdout)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tr, self.out = self.root / 'tr', self.root / 'out'
        self.sources = {
            'stagger': b'function FreeStoreService()\r\nend\r\nUnitServiceRate = 40\r\n',
            'sleep': sleep_fixture(), 'equations': fixture(),
        }
        files = {}
        for name, source in self.sources.items():
            relative = make.FILES[name][0]
            path = self.tr / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source)
            files[name] = (relative, hashlib.sha256(source).hexdigest())
        patch = mock.patch.object(make, 'FILES', files)
        patch.start()
        self.addCleanup(patch.stop)

    def test_build_all_keeps_source_and_stagger_block(self):
        reports = make.build(self.tr, self.out, only=list(self.sources))
        for name, source in self.sources.items():
            self.assertEqual((self.tr / make.FILES[name][0]).read_bytes(), source)
            self.assertTrue((self.out / make.FILES[name][0]).is_file())
        script = (self.out / make.FILES['stagger'][0]).read_bytes()
        self.assertEqual(script, self.sources['stagger']
                         + make.STAGGER.encode().replace(b'\n', b'\r\n'))
        self.assertTrue(any('Normal_Skynet: sleep 3.0 -> 10.0' in r for r in reports))
        self.assertFalse(list(self.out.rglob('.submod-*')))

    def test_default_build_keeps_tr_sleep(self):
        reports = make.build(self.tr, self.out)
        self.assertFalse((self.out / make.FILES['sleep'][0]).exists())
        self.assertFalse(any('sleep' in r for r in reports))

    def test_search_memo_appends_after_the_stagger(self):
        source = (self.sources['stagger'] + b'function Find_Ground_Unit_Target(object)\r\n'
                  b'    return FindTarget.Reachable_Target(PlayerObject, "S", "Friendly", "Friendly_Only", 1.0, object)\r\n'
                  b'end\r\nfunction Find_Space_Unit_Target(object)\r\nend\r\n')
        relative = make.FILES['stagger'][0]
        (self.tr / relative).write_bytes(source)
        pinned = (relative, hashlib.sha256(source).hexdigest())
        files = dict(make.FILES, stagger=pinned)
        files['search-memo'] = pinned
        with mock.patch.object(make, 'FILES', files):
            make.build(self.tr, self.out, only=['stagger', 'search-memo'])
            script = (self.out / relative).read_bytes()
            memo = make.SEARCH_MEMO % {'check': 'false'}
            self.assertEqual(script, source + (make.STAGGER + memo).encode().replace(b'\n', b'\r\n'))
            make.build(self.tr, self.root / 'checked', only=['search-memo'], check=True)
            checked = (self.root / 'checked' / relative).read_bytes()
            self.assertIn(b'AlamoSearchMemoCheck = true', checked)
            self.assertNotIn(b'StaggerPhase', checked)
            (self.tr / relative).write_bytes(self.sources['stagger'])
            files = dict(files, stagger=(relative, hashlib.sha256(self.sources['stagger']).hexdigest()))
            files['search-memo'] = files['stagger']
            with mock.patch.object(make, 'FILES', files):
                with self.assertRaisesRegex(ValueError, 'free-store script structure'):
                    make.build(self.tr, self.root / 'refused', only=['search-memo'])

    def test_sleep_only_four_values_change(self):
        source = self.sources['sleep']
        output, reports = make.edit_sleep(source, '12.25')
        expected = source
        for index in range(1, 5):
            expected = expected.replace(f'>  {index}.0\t<'.encode(), b'>  12.25\t<')
        self.assertEqual(output, expected)
        self.assertEqual(len(reports), 4)
        for source in (source.replace(b'Normal_Default', b'Missing'),
                       source.replace(f'<{TAG}>  1.0\t</{TAG}>'.encode(), b'')):
            with self.assertRaises(ValueError):
                make.edit_sleep(source, '10.0')

    def test_sha_failure_preflights_all_before_writing(self):
        path = self.tr / make.FILES['equations'][0]
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            make.build(self.tr, self.out)
        self.assertFalse(self.out.exists())

    def test_every_component_pins_sha(self):
        for name in make.FILES:
            with self.subTest(name=name):
                path = self.tr / make.FILES[name][0]
                original = path.read_bytes()
                path.write_bytes(original + b'!')
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    make.build(self.tr, self.out, only=[name])
                path.write_bytes(original)

    def test_refuses_overlapping_folders(self):
        for out in (self.tr, self.tr / 'Data', self.root):
            with self.subTest(out=out), self.assertRaises((SystemExit, ValueError)):
                make.build(self.tr, out)

    def test_refuses_hard_link_and_preserves_tr(self):
        relative = make.FILES['sleep'][0]
        dst = self.out / relative
        dst.parent.mkdir(parents=True)
        os.link(self.tr / relative, dst)
        with self.assertRaises(ValueError):
            make.build(self.tr, self.out, only=['sleep'])
        self.assertEqual((self.tr / relative).read_bytes(), self.sources['sleep'])

    def test_refuses_directory_symlink_or_junction(self):
        target = self.root / 'elsewhere'
        target.mkdir()
        link = self.out
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                self.skipTest('symlinks unavailable')
            # Junction creation needs no Windows developer-mode privilege.
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                    capture_output=True)
            if result.returncode:
                self.skipTest('symlinks and junctions unavailable')
            self.addCleanup(lambda: os.rmdir(link))
        with self.assertRaises(ValueError):
            make.build(self.tr, link, only=['sleep'])
        self.assertEqual(list(target.iterdir()), [])

    def test_atomic_replace_never_writes_through_hard_link(self):
        relative = make.FILES['sleep'][0]
        dst = self.out / relative
        dst.parent.mkdir(parents=True)
        os.link(self.tr / relative, dst)
        with mock.patch.object(make, 'check_destination', return_value=dst):
            make.atomic_write(self.tr, self.out, relative, b'new bytes')
        self.assertEqual((self.tr / relative).read_bytes(), self.sources['sleep'])
        self.assertEqual(dst.read_bytes(), b'new bytes')

    def test_atomic_failure_cleans_temporary_file(self):
        with mock.patch.object(make.os, 'replace', side_effect=OSError('failed')):
            with self.assertRaises(OSError):
                make.build(self.tr, self.out, only=['sleep'])
        self.assertFalse(list(self.out.rglob('.submod-*')))

    def test_check_keeps_the_original_under_a_new_name(self):
        output, reports = make.edit_equations(self.sources['equations'], check=True)
        parsed = {n: node for n, node, _ in make.eq.xml_equations(output.decode('latin1'))}
        original = {n: node for n, node, _ in make.eq.xml_equations(self.sources['equations'].decode('latin1'))}
        self.assertEqual(parsed[make.CHECK_PREFIX + 'Is_Connected_To_Enemy'], original['Is_Connected_To_Enemy'])
        self.assertNotEqual(make.eq.render(parsed['Is_Connected_To_Enemy']),
                            make.eq.render(original['Is_Connected_To_Enemy']))
        self.assertIn('check copies', reports[-1])

    def test_failed_proof_writes_nothing(self):
        with mock.patch.object(make.eq, 'equivalent', return_value=False):
            with self.assertRaisesRegex(ValueError, 'polynomial'):
                make.build(self.tr, self.out, only=['equations'])
        self.assertFalse(self.out.exists())

    def test_existing_output_is_replaced(self):
        relative = make.FILES['sleep'][0]
        dst = self.out / relative
        dst.parent.mkdir(parents=True)
        dst.write_bytes(b'previous layer')
        make.build(self.tr, self.out, only=['sleep'])
        self.assertEqual(dst.read_bytes(), make.edit_sleep(self.sources['sleep'], '10.0')[0])

    def test_only_and_invalid_options(self):
        make.build(self.tr, self.out, only=['sleep'])
        self.assertFalse((self.out / make.FILES['stagger'][0]).exists())
        for only in ([], ['bad'], ['sleep', 'sleep']):
            with self.assertRaises(ValueError):
                make.build(self.tr, self.out, only=only)
        for value in ('nan', 'inf', '-1', 'invalid'):
            with self.assertRaises(ValueError):
                make.build(self.tr, self.out, sleep=value)

    def test_isolated_cli(self):
        result = subprocess.run([sys.executable, '-I', '-B',
                                 str(Path(make.__file__)), '--help'], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'--only', result.stdout)
        self.assertIn(b'hero-cadence', result.stdout)
        result = subprocess.run([sys.executable, '-I', '-B', str(Path(make.__file__)),
                                 str(self.tr), str(self.out), '--only', 'sleep'],
                                capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'SHA-256 mismatch', result.stderr)
        self.assertNotIn(b'Traceback', result.stderr)
        self.assertFalse(self.out.exists())

    def test_statistics_folder_cli(self):
        folder = self.root / 'stats'
        folder.mkdir()
        (folder / 'first.xml').write_bytes(b'<Equations><Leaf>X + Y</Leaf></Equations>')
        (folder / 'second.XML').write_bytes(
            b'<Equations><Root>Function_Leaf.Evaluate + Z</Root></Equations>')
        result = subprocess.run([sys.executable, '-I', '-B', eqstats.__file__, str(folder)],
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode().splitlines(),
                         ['expanded\town\tequation', '3\t1\tRoot', '2\t2\tLeaf'])


if __name__ == '__main__':
    unittest.main()
