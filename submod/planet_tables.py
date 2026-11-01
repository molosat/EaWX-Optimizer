"""Recognize exact planet-type polynomials and emit a Lua 5.0 evaluator."""
import json

import equations as eq


class NotTable(ValueError):
    pass


def type_name(node):
    if (node.kind != 'lookup' or node.value != 'Variable_Target.Type.IsType'
            or len(node.params) != 1 or node.params[0][0] != 'Parameter_Type'
            or node.params[0][1][0] != 'string'):
        raise NotTable('not a planet-type lookup')
    return node.params[0][1][1]


MIN_ENTRIES = 8


def find_tables(definitions):
    """Inline only references whose bodies are tables; constants alone do not fit."""
    canonical = {}
    for name in definitions:
        if name.casefold() in canonical:
            raise ValueError('case-ambiguous equation names')
        canonical[name.casefold()] = name
    memo, active = {}, set()

    def table(name):
        if name in memo:
            if memo[name] is None:
                raise NotTable(name)
            return memo[name]
        if name in active or name not in definitions:
            raise NotTable('cycle or missing table reference: ' + name)
        active.add(name)
        try:
            def inline(node):
                if node.kind == 'function':
                    if node.params:
                        raise NotTable('parameterized table reference')
                    target = node.value.removeprefix('Function_').removesuffix('.Evaluate')
                    target = canonical.get(target.casefold(), target)
                    return table(target)[0]
                return eq.Node(node.kind, node.value, tuple(inline(n) for n in node.args),
                               node.params, node.text)
            expanded = inline(definitions[name])
            # Reject case aliases even if expansion cancels a term to zero.
            spellings = {}
            found = False
            for node in eq.walk(expanded):
                if node.kind == 'lookup':
                    value = type_name(node)
                    found = True
                    upper = value.upper()
                    if upper in spellings and spellings[upper] != value:
                        raise ValueError(f'{name}: case-ambiguous Parameter_Type values')
                    spellings[upper] = value
            if not found:
                raise NotTable('constant alone is not a table')
            try:
                polynomial = eq.expand(expanded)
            except ValueError as exc:
                raise NotTable(str(exc)) from exc
            default = polynomial.get((), eq.Fraction(0))
            entries, atoms = {}, {}
            for monomial, coefficient in polynomial.items():
                if not monomial:
                    continue
                if len(monomial) != 1:
                    raise NotTable('nonlinear planet table')
                atom = monomial[0]
                key = type_name(atom).upper()
                entries[key] = entries.get(key, eq.Fraction(0)) + coefficient
                atoms[key] = atom
            # Lua stores the result for each type, including the constant.
            values = {key: default + coefficient for key, coefficient in entries.items()}
            reconstructed = {(): default} if default else {}
            for key, value in values.items():
                if value != default:
                    reconstructed[(atoms[key],)] = value - default
            if reconstructed != polynomial:
                raise ValueError(f'{name}: planet table failed exact polynomial proof')
            result = expanded, default, values
            memo[name] = result
            return result
        except NotTable:
            memo[name] = None
            raise
        finally:
            active.remove(name)

    for name in definitions:
        try:
            table(name)
        except NotTable:
            pass
    # A Lua call costs more than a few lookups: small tables stay as equations (a
    # larger table may still inline them).
    return {name: value for name, value in memo.items() if value is not None and len(value[2]) >= MIN_ENTRIES}


def lua_string(value):
    # Lua 5.0 has decimal byte escapes, not JSON's Unicode escapes.
    result = []
    for char in value:
        if char in ('"', chr(92)):
            result.append(chr(92) + char)
        elif ord(char) < 32 or ord(char) > 126:
            if ord(char) > 255:
                raise ValueError('Lua table names must fit Latin-1')
            result.append(chr(92) + f'{ord(char):03d}')
        else:
            result.append(char)
    return '"' + ''.join(result) + '"'


def lua_number(value):
    printed = eq.fraction_text(value)
    if eq.expand(eq.parse(printed)) != ({(): value} if value else {}):
        raise ValueError('Lua numeric serialization failed exact proof')
    return printed


# The engine finds evaluator scripts by listing a folder a Modpath layer is not
# part of: a new Script_ name fails to parse, while a layer's copy of an existing
# evaluator file is used. So the tables extend TR's TargetHasProperty evaluator;
# names with KEY_PREFIX dispatch to a table, any other name runs TR's code.
EVALUATOR = 'TargetHasProperty'
KEY_PREFIX = 'Alamo_'


def generate_lua(tables, original):
    """TR's evaluator source, unchanged, followed by the table dispatch."""
    if b'function Evaluate(' not in original or b'require("PGBaseDefinitions")' not in original:
        raise ValueError(f'unexpected {EVALUATOR} evaluator structure')
    lines = ['', '-- Alamo lag-fix layer: planet tables proved from SHA-pinned perception equations.',
             'local planet_tables = {']
    for name, (_, default, entries) in sorted(tables.items()):
        lines.append('    [' + lua_string(KEY_PREFIX + name) + '] = { default = ' + lua_number(default)
                     + ', values = {')
        for key, value in sorted(entries.items()):
            lines.append('        [' + lua_string(key) + '] = ' + lua_number(value) + ',')
        lines.append('    } },')
    lines += ['}', '', 'local alamo_original_evaluate = Evaluate', '',
              'function Evaluate(name)', '    local data = planet_tables[name]',
              '    if data == nil then', '        return alamo_original_evaluate(name)', '    end',
              '    object = Target.Get_Game_Object()',
              '    if not TestValid(object) then', '        return 0.0', '    end',
              '    local value = data.values[string.upper(object.Get_Type().Get_Name())]',
              '    if value == nil then', '        return data.default', '    end',
              '    return value', 'end', '']
    newline = b'\r\n' if b'\r\n' in original else b'\n'
    return original + newline.join(line.encode('latin1') for line in lines)


def script_call(name):
    return eq.parse(f'Script_{EVALUATOR}.Evaluate {{Parameter_Script_String = '
                    + json.dumps(KEY_PREFIX + name) + '}')


def changes(source, tables):
    edits, reports = [], []
    for name, original, span in eq.xml_equations(source.decode('latin1')):
        if name not in tables:
            continue
        call = script_call(name)
        printed = eq.render(call)
        # The printed call must resolve to exactly the table just proved above.
        restored = eq.parse(printed)
        if restored != call or restored.params != (('Parameter_Script_String', ('string', KEY_PREFIX + name)),):
            raise ValueError(f'{name}: invalid printed table call')
        edits.append((name, printed, span))
        reports.append(f'{name}: planet table {len(tables[name][2])} entries -> 1 lookup')
    return edits, reports
