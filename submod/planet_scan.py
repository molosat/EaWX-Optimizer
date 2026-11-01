"""Small, fail-closed text edits for the pinned campaign Lua scripts."""
import re


SCORING_CALLS = (
    '\t\tGameScoringMessage("GameScoring -- Galactic Stats dump.")',
    '\t\tPrint_Stat_Table(GalacticKillStatsTable)',
    '\t\tPrint_Build_Stats_Table(GalacticBuildStatsTable)',
    '\t\tDebug_Print_Score_Vals()',
)


def quiet_scoring(source):
    text = source.decode('latin1')
    functions = list(re.finditer(r'^function GameService\(\)\r?\n.*?^end\r?$', text, re.M | re.S))
    if len(functions) != 1:
        raise ValueError('quiet-scoring: expected one GameService')
    function = functions[0]
    lines = function[0].splitlines(keepends=True)
    for call in SCORING_CALLS:
        if sum(line.rstrip('\r\n') == call for line in lines) != 1:
            raise ValueError(f'quiet-scoring: expected exact line {call.strip()}')
    dump = re.compile(r'^\s*(?:GameScoringMessage|Print_Stat_Table|Print_Build_Stats_Table|'
                      r'Debug_Print_Score_Vals)\s*\(')
    if any(dump.match(line) and line.rstrip('\r\n') not in SCORING_CALLS for line in lines):
        raise ValueError('quiet-scoring: unexpected periodic dump call')
    start_line = text.count('\n', 0, function.start()) + 1
    reports = [f'quiet-scoring: removed line {start_line + index}: {line.strip()}'
               for index, line in enumerate(lines) if line.rstrip('\r\n') in SCORING_CALLS]
    replacement = ''.join(line for line in lines if line.rstrip('\r\n') not in SCORING_CALLS)
    return (text[:function.start()] + replacement + text[function.end():]).encode('latin1'), reports


PLUGIN_LOOP = '''        for _, planet in pairs(context.planets) do
            for _, container in ipairs(context.planet_dependent_plugin_containers) do
                local can_update = self.allowed_to_update(target_cache, container)

                if can_update then
                    container.plugin:update(planet)
                end
            end
        end'''

DUE_LOOP = '''        -- No targets were evaluated by TR when the planet list was empty.
        if next(context.planets) == nil then
            return
        end
        local due_plugins = {}
        for _, container in ipairs(context.planet_dependent_plugin_containers) do
            if self.allowed_to_update(target_cache, container) then
                table.insert(due_plugins, container)
            end
        end
        if table.getn(due_plugins) == 0 then
            return
        end
        for _, planet in pairs(context.planets) do
            for _, container in ipairs(due_plugins) do
                container.plugin:update(planet)
            end
        end'''

KEY_UPDATE = '''function KeyDummyLifeCycleHandler:update(planet)
    if not self:should_update() then
        return
    end

    if self.planet_cycle_index == 0 then
        self.changed_keys_for_current_cycle = self.changed_keys_for_next_cycle
        self.changed_keys_for_next_cycle = {}
    end

    self.planet_cycle_index = self.planet_cycle_index + 1'''

KEY_BATCH_SIZE = 128
KEY_SLICED_UPDATE = '''-- Alamo: cap actual planet work at 128 planets per distinct game timestamp.
local ALAMO_KEYDUMMY_BATCH_SIZE = 128

function KeyDummyLifeCycleHandler:update(planet)
    if not self:should_update() then
        return
    end

    local now = GetCurrentTime()
    if self.alamo_slice_time ~= now then
        self.alamo_slice_time = now
        self.alamo_slice_count = 0
    end
    if self.alamo_slice_count >= ALAMO_KEYDUMMY_BATCH_SIZE then
        return
    end
    if self.alamo_sweep_seen and self.alamo_sweep_seen[planet] then
        return
    end

    if self.planet_cycle_index == 0 then
        -- Promote one generation at sweep start, never between batches.
        self.changed_keys_for_current_cycle = self.changed_keys_for_next_cycle
        self.changed_keys_for_next_cycle = {}
        self.alamo_sweep_seen = {}
    end

    self.alamo_sweep_seen[planet] = true
    self.alamo_slice_count = self.alamo_slice_count + 1
    self.planet_cycle_index = self.planet_cycle_index + 1'''

KEY_COMPLETE = '''    if self.planet_cycle_index == self.number_of_planets then
        self.last_update = GetCurrentTime()
        self.planet_cycle_index = 0
    end'''

KEY_SLICED_COMPLETE = '''    if self.planet_cycle_index == self.number_of_planets then
        self.last_update = GetCurrentTime()
        self.planet_cycle_index = 0
        self.alamo_sweep_seen = nil
    end'''


def replace_exact(source, edits, component):
    """Retain every byte outside uniquely matched, explicitly expected spans."""
    newline = b'\r\n' if b'\r\n' in source else b'\n'
    prepared = [(old.encode().replace(b'\n', newline), new.encode().replace(b'\n', newline))
                for old, new in edits]
    if any(source.count(old) != 1 for old, _ in prepared):
        raise ValueError(f'{component}: unexpected script structure')
    for old, new in prepared:
        source = source.replace(old, new, 1)
    return source


def plugin_due(source):
    return (replace_exact(source, [(PLUGIN_LOOP, DUE_LOOP)], 'plugin-due'),
            ['plugin-due: select due planet plugins once per update; retain planet/plugin call order'])


def keydummy_slices(source):
    output = replace_exact(source, [(KEY_UPDATE, KEY_SLICED_UPDATE),
                                    (KEY_COMPLETE, KEY_SLICED_COMPLETE)], 'keydummy-slices')
    return output, [f'keydummy-slices: batch {KEY_BATCH_SIZE} planets per game timestamp; '
                    'dirty-key generation changes only between complete sweeps; ownership handler unchanged']
