"""Build a SHA-pinned XML/Lua layer from a read-only TR installation."""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

# Isolated Python (-I) omits the script directory from sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common_factors
import equations as eq
import native_groups
import planet_scan
import planet_tables

_spec = importlib.util.spec_from_file_location(
    '_tr_stagger', Path(__file__).resolve().parents[1]
    / 'layers/tr-freestore-stagger/make_layer.py')
stagger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stagger)

FILES = {
    'stagger': (stagger.SCRIPT,
                'eac113fe28d62453b68891acdbe5f29b3455014fb3770f0611dd9aefa85b8090'),
    'search-memo': (stagger.SCRIPT,
                    'eac113fe28d62453b68891acdbe5f29b3455014fb3770f0611dd9aefa85b8090'),
    'sleep': (Path('Data/XML/DifficultyAdjustments.xml'),
              'f42ee0705810d62e0632c64893d5340cde37875524df29c3230b0e95c4c28e3f'),
    'equations': (Path('Data/XML/AI/PerceptualEquations/TROffensiveGalacticEquations.xml'),
                  '02685829a18b22d8f994db1a39d74f1b75423c3a1e2504818ef06467ef6c20b0'),
}
# The legacy equations selector remains available for the offensive file alone.
FILES.update({
    'factoring': (Path('Data/XML/AI/PerceptualEquations/TRBasicGalacticEquations.xml'),
                  '26ba49747eea914ac70b38d8d12920675cfc9e8e0bab48343407e47e9b981a1f'),
    'planet-tables': (Path('Data/XML/AI/PerceptualEquations/BasicGalacticEquations_Generated.xml'),
                      '5ce5f9d740a953e680a5cd8086f2d22dad3ae702f7cb1fdca383e9d6f2daa64c'),
})
FILES['common-factors'] = (Path('Data/XML/AI/PerceptualEquations/DefensiveGalacticEquations.xml'),
                           '36039362055ce1a4653edd6f458bc2645e2203f2be2227537a680ce416667357')
FILES.update({
    'hero-cadence': FILES['stagger'],
    'move-guards': FILES['stagger'],
    'order-cap': FILES['stagger'],
    'native-groups': FILES['planet-tables'],
    'faction-groups': FILES['factoring'],
    'quiet-scoring': (Path('Data/Scripts/Miscellaneous/GameScoring.lua'),
                      '7fc2c99a0a234e722e3151cfa2e9aed47f248fe9b751c2b7a21b3be5c4644927'),
    'plugin-due': (Path('Data/Scripts/Library/deepcore/std/plugin_updatecycle.lua'),
                   'aacb1382c99ad349f62f2486017093292cfeb3f4845bd7f5a1f871d36748022d'),
    'keydummy-slices': (Path('Data/Scripts/Library/eawx-plugins/key-dummy-lifecycle-handler/KeyDummyLifeCycleHandler.lua'),
                        '25d471c3d199c6544fd2113eb2677705f768d79a56b3da21894add8a6071007b'),
})
OPT_IN = {'sleep', 'faction-groups', 'planet-tables', 'native-groups', 'quiet-scoring', 'plugin-due', 'keydummy-slices',
          'hero-cadence', 'move-guards', 'order-cap'}
EXTRA_INPUTS = {
    # Read only for lookup costs, which steer the factoring order; the proof does not use them.
    'common-factors': (FILES['equations'], FILES['factoring'],
                       (Path('Data/XML/AI/PerceptualEquations/BasicGalacticEquations.xml'),
                        '38259fca98027b26dd7c161ae727793943aca0aeb214036e9808003c1b4f34c8')),
    'factoring': (FILES['equations'],),
    'planet-tables': ((Path('Data/XML/AI/PerceptualEquations/BasicGalacticEquations.xml'),
                       '38259fca98027b26dd7c161ae727793943aca0aeb214036e9808003c1b4f34c8'),),
}
EXTRA_INPUTS['native-groups'] = EXTRA_INPUTS['planet-tables']
EXTRA_INPUTS['faction-groups'] = (FILES['equations'],)
# The test layer's phase is player ID mod 12, so players 12 IDs apart share a
# phase (Pentastar and Yevetha did in the stagger study). Here the phase is the
# fractional part of ID times the golden ratio: distinct IDs never share a
# phase, and any set of consecutive IDs spreads evenly over the period. (A
# shared GlobalValue slot counter, and then math.floor, both stopped the
# wrapper before TR's FreeStoreService: neither seems available in free-store
# scripts (verify). The block uses only what TR's own scripts use there.)
STAGGER = '''

-- Alamo lag-fix layer (stagger): each AI player's free-store pass gets its own phase.
StaggerPeriod = 40
local Stagger_TR_FreeStoreService = FreeStoreService

function FreeStoreService()
    if StaggerPhase == nil and LastService ~= nil then
        local spread = PlayerObject.Get_ID() * 0.6180339887
        while spread >= 1 do
            spread = spread - 1
        end
        StaggerPhase = spread * StaggerPeriod
        ServiceRate = StaggerPeriod + StaggerPhase
        UnitServiceRate = StaggerPeriod + StaggerPhase
    elseif ServiceRate ~= StaggerPeriod then
        ServiceRate = StaggerPeriod
        UnitServiceRate = StaggerPeriod
    end
    Stagger_TR_FreeStoreService()
end
'''

# The free store runs 2-4 FindTarget.Reachable_Target searches for each unit it
# moves, each scoring every friendly planet, and all of a player's units are
# serviced in one frame. Units at one planet get one search per score in that
# pass; everything TR checks after the search still runs per unit. The key holds
# the searching unit's type because Reachable_Target receives the unit, so two
# unit types at one planet must not share a result. The memo is keyed by game
# time, so it never outlives the frame of its pass. In check mode every hit also
# runs the real search, counts hits, misses and disagreements in plain globals
#, and returns the real
# result on a disagreement.
SEARCH_MEMO = '''

-- Alamo lag-fix layer (search-memo): one target search per origin planet and score in each pass.
AlamoSearchMemoCheck = %(check)s
AlamoMemoHits, AlamoMemoMisses, AlamoMemoMismatches = 0, 0, 0

local function Alamo_Memo_Search(tr_find, player, score, kind, reach, probability, source)
    local origin = source.Get_Planet_Location()
    if not TestValid(origin) then
        return tr_find.Reachable_Target(player, score, kind, reach, probability, source)
    end
    if AlamoSearchMemoTime ~= GetCurrentTime() then
        AlamoSearchMemoTime = GetCurrentTime()
        AlamoSearchMemo = {}
    end
    local key = score .. "|" .. kind .. "|" .. reach .. "|" .. tostring(probability) .. "|"
        .. origin.Get_Type().Get_Name() .. "|" .. source.Get_Type().Get_Name() .. "|"
        .. tostring(source.Is_Transport())
    local cached = AlamoSearchMemo[key]
    if cached == nil then
        local found = tr_find.Reachable_Target(player, score, kind, reach, probability, source)
        if found then
            AlamoSearchMemo[key] = found
        else
            AlamoSearchMemo[key] = false
        end
        if AlamoSearchMemoCheck then
            AlamoMemoMisses = AlamoMemoMisses + 1
        end
        return found
    end
    if AlamoSearchMemoCheck then
        AlamoMemoHits = AlamoMemoHits + 1
        local real = tr_find.Reachable_Target(player, score, kind, reach, probability, source)
        local same = (not real and not cached)
            or (real and cached and real.Get_Game_Object() == cached.Get_Game_Object())
        if not same then
            AlamoMemoMismatches = AlamoMemoMismatches + 1
            return real
        end
    end
    if cached then
        return cached
    end
    return nil
end

local function Alamo_Memo_Call(tr_target_function, object)
    local tr_find = FindTarget
    FindTarget = {Reachable_Target = function(player, score, kind, reach, probability, source)
        return Alamo_Memo_Search(tr_find, player, score, kind, reach, probability, source)
    end}
    local result = tr_target_function(object)
    FindTarget = tr_find
    return result
end

local Alamo_TR_Find_Ground_Unit_Target = Find_Ground_Unit_Target
local Alamo_TR_Find_Space_Unit_Target = Find_Space_Unit_Target

function Find_Ground_Unit_Target(object)
    return Alamo_Memo_Call(Alamo_TR_Find_Ground_Unit_Target, object)
end

function Find_Space_Unit_Target(object)
    return Alamo_Memo_Call(Alamo_TR_Find_Space_Unit_Target, object)
end
'''

# Safe combat heroes get alternate passes, split by stable type-name parity.
# Unsafe units still use TR's emergency path. Only Lua 5.0 operations available
# in free-store states are used; the service wrapper chains after stagger.
HERO_CADENCE = '''

-- Alamo lag-fix layer (hero-cadence): alternate safe combat hero moves by type-name parity.
AlamoHeroPass = 0
AlamoHeroParity = {}
local AlamoHero_TR_FreeStoreService = FreeStoreService
local AlamoHero_TR_On_Unit_Service = On_Unit_Service

function FreeStoreService()
    AlamoHeroPass = 1 - AlamoHeroPass
    return AlamoHero_TR_FreeStoreService()
end

-- Parity of the sum of a type name's bytes, worked out once per hero type.
local function Alamo_Hero_Parity(name)
    local parity = AlamoHeroParity[name]
    if parity == nil then
        parity = 0
        for index = 1, string.len(name) do
            local bit = string.byte(name, index)
            while bit >= 2 do
                bit = bit - 2
            end
            parity = parity + bit
            if parity == 2 then
                parity = 0
            end
        end
        AlamoHeroParity[name] = parity
    end
    return parity
end

function On_Unit_Service(object)
    if object.Is_Category("Structure") then
        return false
    end
    -- The cheap type checks come first, so non-heroes never pay for the safety check.
    if object.Get_Type().Is_Hero() and not object.Is_Category("NonCombatHero")
        and FreeStore.Is_Unit_Safe(object) ~= false then
        if AlamoHeroPass ~= Alamo_Hero_Parity(object.Get_Type().Get_Name()) then
            MoveUnit(object)
        end
        return
    end
    return AlamoHero_TR_On_Unit_Service(object)
end
'''

# Fewer fleet orders, fewer engine path rebuilds. An order census on the candidate
# layer (two earlier runs) found a third of hero orders sent the hero to the
# planet it was already on, and about 64% of searches from On_Unit_Added were for
# units already in transit, which TR's own service pass never searches for. With
# the guards, orders from added units were unchanged, so those searches almost
# never produced an order. The MoveUnit copy below is TR's body plus one guard
# (the source file is pinned by hash).
MOVE_GUARDS = '''

-- Alamo lag-fix layer (move-guards): no order to the planet a unit is resting on, and no
-- new search for a unit added while in transit (TR's service pass skips those too).
function MoveUnit(object)
    dest_target = nil
    object_type = object.Get_Type()
    if object_type.Is_Hero() then
        dest_target = Find_Custom_Target(object)
    end

    if not TestValid(dest_target) then
        if object.Is_Transport() then
            dest_target = Find_Ground_Unit_Target(object)
        else
            dest_target = Find_Space_Unit_Target(object)
        end
    end

    if dest_target then
        -- Still counts as a move, so TR's per-pass move budget is spent as before.
        -- Find_Custom_Target returns a search result, the other finders a planet object,
        -- which has no Get_Game_Object (calling it raises an error).
        local here = object.Get_Planet_Location()
        local unwrapped, there = pcall(function() return dest_target.Get_Game_Object() end)
        if not unwrapped then
            there = dest_target
        end
        if TestValid(here) and there == here
            and FreeStore.Is_Unit_In_Transit(object) == false then
            return true
        end
        FreeStore.Move_Object(object, dest_target)
        return true
    else
        DebugMessage(
            "%s -- Object: %s, unable to find a suitable destination for this object.",
            tostring(Script),
            tostring(object)
        )
        return false
    end
end

local AlamoGuard_TR_On_Unit_Added = On_Unit_Added
function On_Unit_Added(object)
    if not object.Is_Category("Structure") and FreeStore.Is_Unit_In_Transit(object) then
        return
    end
    return AlamoGuard_TR_On_Unit_Added(object)
end
'''

# Fewer orders in one frame, smaller rebuild bursts. A unit pass calls On_Unit_Service
# for every unit of a store in one frame, and a store can also take many On_Unit_Added
# calls at once. Each MoveUnit runs 2-4 target searches and each order clears planet
# icons, which the next frame pays for with galaxy-wide path rebuilds (the 3.6 s stall
# in an earlier test made 347 clears and then 37 rebuilds). The cap counts MoveUnit calls per
# store per frame (GetCurrentTime changes once a frame); over the cap a unit is not
# searched for and waits for its next service under TR's own rules, except an unsafe
# unit, which always moves. The counters are AlamoDiag globals, which scripthealth.py
# sums over the stores; the histogram counts frames by their number of calls.
ORDER_CAP = '''

-- Alamo lag-fix layer (order-cap): at most %(cap)d target searches and orders per free store
-- per frame. Over the cap a unit waits for its next service; unsafe units always move.
AlamoOrderCap = %(cap)d
AlamoCapCount = 0
AlamoCapAdded = false
AlamoDiagCapCalls, AlamoDiagCapSkipService, AlamoDiagCapSkipAdded, AlamoDiagCapExempt = 0, 0, 0, 0
AlamoDiagCapFrames1, AlamoDiagCapFrames5, AlamoDiagCapFrames9 = 0, 0, 0
AlamoDiagCapFrames17, AlamoDiagCapFrames33 = 0, 0
local AlamoCap_TR_MoveUnit = MoveUnit
local AlamoCap_TR_On_Unit_Added = On_Unit_Added

-- Files the finished frame's call count in a histogram bucket.
local function Alamo_Cap_File(count)
    if count >= 33 then
        AlamoDiagCapFrames33 = AlamoDiagCapFrames33 + 1
    elseif count >= 17 then
        AlamoDiagCapFrames17 = AlamoDiagCapFrames17 + 1
    elseif count >= 9 then
        AlamoDiagCapFrames9 = AlamoDiagCapFrames9 + 1
    elseif count >= 5 then
        AlamoDiagCapFrames5 = AlamoDiagCapFrames5 + 1
    elseif count >= 1 then
        AlamoDiagCapFrames1 = AlamoDiagCapFrames1 + 1
    end
end

function MoveUnit(object)
    if AlamoCapTime ~= GetCurrentTime() then
        Alamo_Cap_File(AlamoCapCount)
        AlamoCapTime = GetCurrentTime()
        AlamoCapCount = 0
    end
    if AlamoCapCount >= AlamoOrderCap then
        if FreeStore.Is_Unit_Safe(object) == false then
            AlamoDiagCapExempt = AlamoDiagCapExempt + 1
        else
            if AlamoCapAdded then
                AlamoDiagCapSkipAdded = AlamoDiagCapSkipAdded + 1
            else
                AlamoDiagCapSkipService = AlamoDiagCapSkipService + 1
            end
            -- Not a move, so TR's per-pass move budget is not spent.
            return false
        end
    end
    AlamoCapCount = AlamoCapCount + 1
    AlamoDiagCapCalls = AlamoDiagCapCalls + 1
    return AlamoCap_TR_MoveUnit(object)
end

function On_Unit_Added(object)
    AlamoCapAdded = true
    local result = AlamoCap_TR_On_Unit_Added(object)
    AlamoCapAdded = false
    return result
end
'''

LUA_PATH = Path('Data/Scripts/Evaluators/TargetHasProperty.lua')
# TR's evaluator that the planet tables extend (planet_tables.EVALUATOR).
EVALUATOR_INPUT = (LUA_PATH, '1f2902077802e7bdd4e33eecb7e1238d16296d0c51b809d88fb1d78ffeb9031a')
CHECK_PREFIX = 'Alamo_Orig_'
SLEEP_NAMES = ('Normal_Default', 'Hard_Default', 'Normal_Skynet', 'Hard_Skynet')


def no_links(path):
    """Reject symlinks and Windows reparse points in all existing ancestors."""
    # Retain '..' until after checking ancestors, so a link cannot hide before it.
    path = Path(path).absolute()
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'output path uses a link or reparse point: {part}')
        if part == path and stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise ValueError(f'output file has hard links: {part}')


def check_destination(tr, out, relative):
    """Reuse the stagger overlap check and reject linked output paths."""
    no_links(out)
    # The original helper checks resolved overlap and aliases of its script.
    stagger.check_destination(tr, out)
    dst = Path(out).absolute() / relative
    no_links(dst)
    source = Path(tr) / relative
    if dst.exists() and source.exists() and dst.samefile(source):
        raise ValueError(f'output aliases TR: {dst}')
    return dst


def atomic_write(tr, out, relative, data):
    dst = check_destination(tr, out, relative)
    dst.parent.mkdir(parents=True, exist_ok=True)
    check_destination(tr, out, relative)
    fd, temporary = tempfile.mkstemp(dir=dst.parent, prefix='.submod-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        check_destination(tr, out, relative)
        os.replace(temporary, dst)
    except BaseException:
        os.unlink(temporary)
        raise
    return dst


def sleep_value(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('sleep must be a finite nonnegative number') from exc
    if not number.is_finite() or number < 0:
        raise ValueError('sleep must be a finite nonnegative number')
    text = format(number, 'f')
    return text if '.' in text else text + '.0'


def replace_spans(text, replacements):
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def edit_sleep(source, value):
    """Change exactly four numeric text spans, retaining all other bytes."""
    text = source.decode('latin1')
    masked = eq.comment_mask(text)
    blocks = re.compile(r'<Difficulty_Adjustment\b[^>]*\bName\s*=\s*([\'"])(.*?)\1[^>]*>'
                        r'(.*?)</Difficulty_Adjustment\s*>', re.S)
    tag = re.compile(r'<Galactic_AI_Goal_Cycle_Sleep_Duration\s*>\s*('
                     + eq.NUMBER + r')\s*</Galactic_AI_Goal_Cycle_Sleep_Duration\s*>')
    replacements, reports, seen = [], [], set()
    for block in blocks.finditer(masked):
        name = block[2]
        if name not in SLEEP_NAMES:
            continue
        if name in seen:
            raise ValueError(f'duplicate difficulty {name}')
        seen.add(name)
        values = list(tag.finditer(block[3]))
        if len(values) != 1:
            raise ValueError(f'{name}: expected exactly one goal-cycle sleep value')
        found = values[0]
        start, end = found.span(1)
        offset = block.start(3)
        replacements.append((offset + start, offset + end, value))
        reports.append(f'{name}: sleep {found[1]} -> {value}')
    if seen != set(SLEEP_NAMES):
        raise ValueError(f'missing difficulty adjustments: {sorted(set(SLEEP_NAMES) - seen)}')
    return replace_spans(text, replacements).encode('latin1'), reports


def binary(op, left, right):
    return eq.Node('binary', op, (left, right))


def total(nodes):
    nodes = list(nodes)
    if not nodes:
        return eq.Node('number', eq.Fraction(0))
    result = nodes[0]
    for node in nodes[1:]:
        result = binary('+', result, node)
    return result


def faction(node):
    parameters = dict(node.params)
    if len(parameters) != len(node.params):
        raise ValueError('faction lookup has repeated parameters')
    value = parameters.get('Parameter_Faction')
    if value is None or value[0] != 'string':
        raise ValueError('faction lookup lacks a quoted faction')
    return value[1]


def connectivity_polynomial(node):
    """Validate bilinear IsFaction/IsConnectedTo rows, retaining quirks."""
    polynomial = eq.expand(node)
    selves, connections, rows = {}, {}, {}
    for monomial, coefficient in polynomial.items():
        if len(monomial) != 2 or coefficient != 1:
            raise ValueError('expected unit-coefficient connectivity products')
        self_nodes = [x for x in monomial if x.kind == 'lookup'
                      and x.value == 'Variable_Self.IsFaction']
        connected = [x for x in monomial if x.kind == 'lookup'
                     and x.value == 'Variable_Target.IsConnectedTo']
        if len(self_nodes) != 1 or len(connected) != 1:
            raise ValueError('unexpected connectivity factors')
        own, conn = self_nodes[0], connected[0]
        for table, item in ((selves, own), (connections, conn)):
            name = faction(item)
            if name in table and table[name] != item:
                raise ValueError(f'inconsistent lookup parameters for {name}')
            table[name] = item
        rows.setdefault(faction(own), set()).add(faction(conn))
    if not rows:
        raise ValueError('empty connectivity equation')
    return selves, connections, rows


def family(node):
    """A lookup family retains the variable, token and every other binding."""
    faction(node)
    return node.value, tuple(p for p in node.params if p[0] != 'Parameter_Faction')


def scaled(coefficient, node):
    if coefficient == 1:
        return node
    return binary('*', eq.Node('number', coefficient), node)


def product(nodes):
    result = eq.Node('number', eq.Fraction(1))
    for node in nodes:
        result = node if result.kind == 'number' and result.value == 1 else binary('*', result, node)
    return result


def factor_factions(original):
    """Cheapest row-grouped or rectangular-complement form, or None if unfit.

    Both orientations are considered. Column bundles also cover nested
    tables such as human-faction * connection, without any boolean assumptions.
    Column bundles retain their original bindings, including mismatched faction
    names. Degree-one terms and constants are carried through exactly.
    """
    body = original
    comparison = original.kind == 'binary' and original.value in eq.COMPARISONS
    constant_left = False
    try:
        if comparison:
            body, bound = original.args
            if any(key for key in eq.expand(bound)):
                if eq.expand(body).keys() - {()}:
                    return None
                body, bound = bound, body
                constant_left = True
        polynomial = eq.expand(body)
        pairs = {m: c for m, c in polynomial.items() if len(m) >= 2}
        if not pairs or any(len(m) > 3 for m in pairs):
            return None
        signatures = {family(n) for m in pairs for n in m if n.kind == 'lookup'}
        if any(n.kind != 'lookup' for m in pairs for n in m):
            return None
        if len(signatures) not in (2, 3):
            return None
        if any(len(m) != len(signatures) or {family(n) for n in m} != signatures
               for m in pairs):
            return None
    except ValueError:
        return None
    tail = total(scaled(c, product(m)) for m, c in polynomial.items() if len(m) < 2)
    candidates = []
    for signature in sorted(signatures, key=repr):
        rows, aa, bb = {}, {}, {}
        for monomial, coefficient in pairs.items():
            a = next(n for n in monomial if family(n) == signature)
            bs = tuple(n for n in monomial if family(n) != signature)
            aa[a] = a
            bb[bs] = product(bs)
            rows.setdefault(a, {})[bs] = coefficient
        # Include A-only rows and B-only columns in the rectangle. Missing rows
        # must be subtracted in full rather than silently acquiring products.
        for m in polynomial:
            if len(m) == 1 and m[0].kind == 'lookup':
                try:
                    sig = family(m[0])
                except ValueError:
                    continue
                if sig == signature:
                    aa[m[0]] = m[0]
                elif len(signatures) == 2 and sig in signatures:
                    bb[(m[0],)] = m[0]
        row_order, col_order = sorted(aa, key=repr), sorted(bb, key=repr)
        direct = total(binary('*', a, total(scaled(c, bb[b]) for b, c in
                       sorted(rows[a].items(), key=lambda item: repr(item[0]))))
                       for a in row_order if a in rows)
        forms = [direct]
        # A non-unit common coefficient can be cheaper too; all candidates are
        # exact, including negative or fractional row corrections.
        for baseline in sorted(set(pairs.values()) | {eq.Fraction(1)}):
            rectangle = scaled(baseline, binary('*', total(row_order), total(bb[b] for b in col_order)))
            corrections = []
            for a in row_order:
                delta = [(b, rows.get(a, {}).get(b, 0) - baseline) for b in col_order]
                missing = total(scaled(-c, bb[b]) for b, c in delta if c < 0)
                extra = total(scaled(c, bb[b]) for b, c in delta if c > 0)
                if any(c < 0 for _, c in delta):
                    corrections.append(('-', binary('*', a, missing)))
                if any(c > 0 for _, c in delta):
                    corrections.append(('+', binary('*', a, extra)))
            for op, correction in corrections:
                rectangle = binary(op, rectangle, correction)
            forms.append(rectangle)
        for form in forms:
            if eq.expand(tail):
                form = binary('+', form, tail)
            if comparison:
                form = (binary(original.value, bound, form) if constant_left
                        else binary(original.value, form, bound))
            candidates.append(form)
    if not candidates:
        return None
    result = min(candidates, key=eq.lookup_count)
    if not eq.equivalent(original, result):
        raise ValueError('faction factoring failed exact polynomial proof')
    return result if eq.lookup_count(result) < eq.lookup_count(original) else original


def factor_enemy(original):
    """Compatibility entry point for the former connectivity-only factoring."""
    result = factor_factions(original)
    if result is None or eq.lookup_count(result) >= eq.lookup_count(original):
        raise ValueError('equation has no cheaper faction-pair form')
    return result


def edit_bodies(source, changes, check=False, escaped=False):
    """Apply already-proven body changes while preserving surrounding bytes."""
    text = source.decode('latin1')
    newline = '\r\n' if '\r\n' in text else '\n'
    replacements, originals = [], []
    for name, printed, (start, end) in changes:
        body = text[start:end]
        comments = re.findall(r'<!--.*?-->', body, re.S)
        prefix = re.match(r'\s*', body)[0]
        suffix = re.search(r'\s*$', body)[0]
        rendered = printed if escaped else printed.replace('&', '&amp;').replace('<', '&lt;')
        replacement = prefix + (newline.join(comments) + newline if comments else '') + rendered + suffix
        replacements.append((start, end, replacement))
        originals.append((name, body))
    text = replace_spans(text, replacements)
    reports = []
    if check and originals:
        names = {n.casefold() for n, _, _ in eq.xml_equations(text)}
        if any((CHECK_PREFIX + n).casefold() in names for n, _ in originals):
            raise ValueError('check copy already exists')
        closing = text.rindex('</Equations>')
        extra = ''.join(f'\t<{CHECK_PREFIX}{n}>{body}</{CHECK_PREFIX}{n}>{newline}{newline}'
                        for n, body in originals)
        text = text[:closing] + extra + text[closing:]
        reports.append('check copies: ' + ', '.join(CHECK_PREFIX + n for n, _ in originals))
    return text.encode('latin1'), reports


def edit_factoring(source, check=False):
    changes, reports = [], []
    for name, original, span in eq.xml_equations(source.decode('latin1')):
        rewritten = factor_factions(original)
        if rewritten is None:
            continue
        before, after = eq.lookup_count(original), eq.lookup_count(rewritten)
        reports.append(f'{name}: lookups {before} -> {after}')
        if after < before:
            printed = eq.render(rewritten)
            if not eq.equivalent(original, eq.parse(printed)):
                raise ValueError(f'{name}: rewrite is not polynomial-identical')
            if eq.paren_depth(printed) > eq.MAX_DEPTH:
                raise ValueError(f'{name}: nesting {eq.paren_depth(printed)} exceeds {eq.MAX_DEPTH}')
            changes.append((name, printed, span))
    output, copies = edit_bodies(source, changes, check)
    return output, reports + copies


def edit_equations(source, check=False):
    """Rewrite the target bodies; with check, also append each original under
    CHECK_PREFIX + name so the game can compare the two (EvaluatePerception)."""
    text = source.decode('latin1')
    parsed = {name: (node, span) for name, node, span in eq.xml_equations(text)}
    # Is_Connected_To_Me is already one lookup pair per faction; it is checked, not rewritten.
    targets = ('Is_Connected_To_Enemy',)
    if not all(name in parsed for name in targets + ('Is_Connected_To_Me',)):
        raise ValueError('missing required connectivity equation')
    selves, connections, rows = connectivity_polynomial(parsed['Is_Connected_To_Me'][0])
    if any(row != {own} for own, row in rows.items()):
        raise ValueError('unexpected self-connectivity structure')
    output, reports = edit_factoring(source, check)
    # Preserve the historical equations-component report scope.
    return output, [r for r in reports if not r.startswith('Is_Connected_To_Me:')]


def group_size_value(value):
    if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
        raise ValueError('group-size must be a nonnegative integer (0 means unlimited)')
    return int(value)


def order_cap_value(value):
    if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]*', str(value)):
        raise ValueError('order-cap must be a positive integer')
    return int(value)


def build(tr, out, sleep='10.0', only=None, check=False, group_size=0, order_cap=16):
    # planet-tables is opt-in: on a save made without the layer, the save's copy of
    # TR's evaluator replaces the layer's and every table scores 0 (README).
    defaults = tuple(k for k in FILES if (k != 'equations' or 'factoring' not in FILES)
                     and k not in OPT_IN)
    selected = defaults if only is None else tuple(only)
    if not selected or len(set(selected)) != len(selected) or set(selected) - FILES.keys():
        raise ValueError('only must contain unique names from ' + ','.join(FILES))
    value = sleep_value(sleep)
    group_size = group_size_value(group_size)
    order_cap = order_cap_value(order_cap)
    if {'native-groups', 'planet-tables'} <= set(selected):
        raise ValueError('native-groups and planet-tables rewrite the same bodies; select one')
    prepared = []
    # Validate every selected source and destination before creating any output.
    inputs = {}
    for component in selected:
        sources = []
        for relative, expected in (FILES[component], *EXTRA_INPUTS.get(component, ())):
            check_destination(tr, out, relative)
            source = (Path(tr) / relative).read_bytes()
            sha = hashlib.sha256(source).hexdigest()
            if sha != expected:
                raise ValueError(f'{relative}: SHA-256 mismatch (expected {expected}, got {sha})')
            sources.append((relative, source, sha))
        inputs[component] = sources
        if component == 'planet-tables':
            relative, expected = EVALUATOR_INPUT
            evaluator = (Path(tr) / relative).read_bytes()
            sha = hashlib.sha256(evaluator).hexdigest()
            if sha != expected:
                raise ValueError(f'{relative}: SHA-256 mismatch (expected {expected}, got {sha})')
    for component, sources in inputs.items():
        if component == 'faction-groups':
            continue  # Applied to the final bodies below, regardless of selection order.
        if component == 'planet-tables':
            definitions = {}
            for _, source, _ in sources:
                for name, node, _ in eq.xml_equations(source.decode('latin1')):
                    if name in definitions:
                        raise ValueError(f'duplicate equation {name}')
                    definitions[name] = node
            tables = planet_tables.find_tables(definitions)
            if not tables:
                raise ValueError('no planet tables found')
            for relative, source, sha in sources:
                changes, report = planet_tables.changes(source, tables)
                transformed, copies = edit_bodies(source, changes, check)
                prepared.append((relative, transformed, report + copies, sha))
            check_destination(tr, out, LUA_PATH)
            prepared.append((LUA_PATH, planet_tables.generate_lua(tables, evaluator),
                             [f'planet-tables: extended {planet_tables.EVALUATOR} evaluator'],
                             EVALUATOR_INPUT[1]))
            continue
        if component == 'common-factors':
            definitions = {}
            for _, source, _ in sources:
                for name, node, _ in eq.xml_equations(source.decode('latin1')):
                    definitions.setdefault(name, node)
            atom_cost = common_factors.costs(definitions)
            relative, source, sha = sources[0]
            changes, report = [], []
            for name, original, span in eq.xml_equations(source.decode('latin1')):
                factored = common_factors.rewrite(original, atom_cost)
                if factored is None:
                    continue
                printed = eq.render(factored)
                if not eq.equivalent(original, eq.parse(printed)):
                    raise ValueError(f'{name}: printed common-factor rewrite is not identical')
                if eq.paren_depth(printed) > eq.MAX_DEPTH:
                    raise ValueError(f'{name}: nesting {eq.paren_depth(printed)} exceeds {eq.MAX_DEPTH}')
                changes.append((name, printed, span))
                report.append(f'{name}: weighted lookups {common_factors.weighted(original, atom_cost)} -> '
                              f'{common_factors.weighted(factored, atom_cost)}')
            if not changes:
                raise ValueError('no common-factor rewrites found')
            transformed, copies = edit_bodies(source, changes, check)
            prepared.append((relative, transformed, report + copies, sha))
            continue
        for relative, source, sha in sources:
            if component in ('stagger', 'search-memo', 'hero-cadence', 'move-guards', 'order-cap'):
                # These components append to TR's free-store script; whichever comes
                # first writes the blocks for every selected one.
                needed = [b'function FreeStoreService()', b'UnitServiceRate = 40']
                if 'search-memo' in selected:
                    needed += [b'function Find_Ground_Unit_Target(object)',
                               b'function Find_Space_Unit_Target(object)', b'FindTarget.Reachable_Target(']
                if 'hero-cadence' in selected:
                    needed += [b'function On_Unit_Service(object)',
                               b'not object.Is_Category("NonCombatHero")']
                if 'move-guards' in selected:
                    needed += [b'function MoveUnit(object)', b'dest_target = Find_Custom_Target(object)',
                               b'FreeStore.Move_Object(object, dest_target)', b'function On_Unit_Added(object)']
                if 'order-cap' in selected:
                    needed += [b'function MoveUnit(object)', b'function On_Unit_Added(object)',
                               b'if MoveUnit(object) then']
                for text in needed:
                    if text not in source:
                        raise ValueError('unexpected free-store script structure')
                newline = b'\r\n' if b'\r\n' in source else b'\n'
                blocks, report = '', []
                if 'stagger' in selected:
                    blocks += STAGGER
                    report.append('stagger: appended slot-claiming stagger block')
                if 'search-memo' in selected:
                    blocks += SEARCH_MEMO % {'check': 'true' if check else 'false'}
                    report.append('search-memo: appended per-pass target search memo'
                                  + (' with in-game check counters' if check else ''))
                if 'hero-cadence' in selected:
                    blocks += HERO_CADENCE
                    report.append('hero-cadence: appended alternate-pass safe combat hero moves')
                if 'move-guards' in selected:
                    blocks += MOVE_GUARDS
                    report.append('move-guards: appended same-planet and added-in-transit order guards')
                if 'order-cap' in selected:
                    # Last, so it wraps whichever MoveUnit and On_Unit_Added are in force.
                    blocks += ORDER_CAP % {'cap': order_cap}
                    report.append(f'order-cap: appended a cap of {order_cap} searches and orders per store per frame')
                transformed = source + blocks.encode().replace(b'\n', newline)
            elif component == 'sleep':
                transformed, report = edit_sleep(source, value)
            elif component == 'factoring':
                transformed, report = edit_factoring(source, check and 'faction-groups' not in selected)
            elif component == 'native-groups':
                changes, report = native_groups.changes(source, group_size)
                transformed, copies = edit_bodies(source, changes, check, escaped=True)
                report += copies
            elif component == 'quiet-scoring':
                transformed, report = planet_scan.quiet_scoring(source)
            elif component == 'plugin-due':
                transformed, report = planet_scan.plugin_due(source)
            elif component == 'keydummy-slices':
                transformed, report = planet_scan.keydummy_slices(source)
            else:
                transformed, report = edit_equations(source, check and 'faction-groups' not in selected)
            prepared.append((relative, transformed, report, sha))
    if 'faction-groups' in selected:
        for relative, source, sha in inputs['faction-groups']:
            # Replace every prepared copy so the existing first-write rule cannot
            # discard this final pass. Sources remain the original pinned bytes.
            prior = next((item for item in prepared if item[0] == relative), None)
            body_source = prior[1] if prior else source
            changes, report = native_groups.changes(
                body_source, group_size, native_groups.FACTION_GROUPS)
            transformed, _ = edit_bodies(body_source, changes, escaped=True)
            copies = []
            if check:
                final = {n: (node, span) for n, node, span in
                         eq.xml_equations(transformed.decode('latin1'))}
                text = transformed.decode('latin1')
                combined = []
                for name, original, span in eq.xml_equations(source.decode('latin1')):
                    node, (start, end) = final[name]
                    if node != original:
                        combined.append((name, eq.comment_mask(text[start:end]).strip(), span))
                transformed, copies = edit_bodies(source, combined, True, escaped=True)
            item = (relative, transformed,
                    (prior[2] if prior else []) + report + copies, sha)
            prepared = [entry for entry in prepared if entry[0] != relative]
            prepared.append(item)
    reports, written = [], set()
    for relative, transformed, report, sha in prepared:
        if relative in written:
            continue
        dst = atomic_write(tr, out, relative, transformed)
        written.add(relative)
        reports.extend([f'{dst} from TR sha256 {sha}', *report])
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tr_folder', type=Path)
    parser.add_argument('out_folder', type=Path)
    parser.add_argument('--sleep', default='10.0', metavar='SECONDS')
    parser.add_argument('--group-size', default=0, type=group_size_value, metavar='N',
                        help='native-groups/faction-groups binding cap: positive integer, or 0 for unlimited (default)')
    parser.add_argument('--order-cap', default=16, type=order_cap_value, metavar='N',
                        help='order-cap: MoveUnit calls per free store per frame (default 16)')
    parser.add_argument('--only',
                        help='comma-list of stagger,search-memo,sleep,factoring,planet-tables,'
                             'common-factors,native-groups,faction-groups,quiet-scoring,plugin-due,keydummy-slices,hero-cadence,move-guards,order-cap; '
                             'equations selects legacy offensive factoring '
                             '(default: stagger,search-memo,factoring,common-factors)')
    parser.add_argument('--check', action='store_true',
                        help=f'also keep each rewritten original as {CHECK_PREFIX}<name> for in-game comparison')
    args = parser.parse_args()
    try:
        reports = build(args.tr_folder, args.out_folder, args.sleep,
                        None if args.only is None else args.only.split(','), args.check, args.group_size,
                        args.order_cap)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'error: {exc}\n')
    print('\n'.join(reports))


if __name__ == '__main__':
    main()
