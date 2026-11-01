-- Synthetic runtime regressions. Invoked by test_opt_in.py with LUA50.
assert(string.find(_VERSION, "Lua 5.0", 1, true))

callable = function(t)
    return setmetatable(t, {__call=function(self, ...) return self.call(self, unpack(arg)) end})
end
function allowed_to_update(cache, c)
    if cache[c.target] == nil then cache[c.target] = c.target() end
    return cache[c.target]
end
generic_plugin_update_cycle = function(ctx, cache)
    for _, c in ipairs(ctx.plugin_containers) do
        if allowed_to_update(cache, c) then c.plugin:update() end
    end
end
local original = dofile("original_plugin.lua")
local due = dofile("due.lua")
local function run(cycle, planets, flags)
    local calls, checks = {}, {}
    local containers = {}
    for i, flag in ipairs(flags) do
        local index, value = i, flag
        containers[i] = {
            target=function()
                checks[index] = (checks[index] or 0) + 1
                return value
            end,
            plugin={update=function(self, p)
                table.insert(calls, index .. ":" .. tostring(p))
            end}
        }
    end
    cycle {planets=planets, plugin_containers={containers[1]},
           planet_dependent_plugin_containers=containers}
    return table.concat(calls, ","), checks
end
for _, planets in ipairs({{}, {"A"}, {"A", "B", "C"}}) do
    for _, flags in ipairs({{true, false, true}, {false, false, false}}) do
        local before = run(original, planets, flags)
        local after, checks = run(due, planets, flags)
        assert(before == after)
        assert(checks[1] == 1)
        if next(planets) then assert(checks[2] == 1 and checks[3] == 1)
        else assert(checks[2] == nil and checks[3] == nil) end
    end
end

-- A real interval target is consumed once, including when shared with generic plugins.
local time, checks, updates, next_due = 0, 0, 0, 0
local target = function()
    checks = checks + 1
    if time >= next_due then next_due = time + 10; return true end
    return false
end
local container = {target=target, plugin={update=function() updates = updates + 1 end}}
local ctx = {planets={"A", "B"}, plugin_containers={container},
             planet_dependent_plugin_containers={container, container}}
due(ctx)
assert(checks == 1 and updates == 5)
time = 1
due(ctx)
assert(checks == 2 and updates == 5)
time = 10
due(ctx)
assert(checks == 3 and updates == 10)

local now = 0
GetCurrentTime = function() return now end
dofile("sliced.lua")
local sliced = KeyDummyLifeCycleHandler
local function instance(count)
    local obj = {planet_cycle_index=0, number_of_planets=count, interval=10,
        changed_keys_for_current_cycle={}, changed_keys_for_next_cycle={first=true},
        owners={}, ownership_calls={}, calls={}, generations={}}
    setmetatable(obj, {__index=sliced})
    obj.process = function(self, planet)
        table.insert(self.calls, planet)
        table.insert(self.generations, self.changed_keys_for_current_cycle)
    end
    return obj
end
local obj = instance(300)
local function tick(reverse)
    for i=1,300 do obj:update(reverse and 301-i or i) end
end
tick(false)
assert(table.getn(obj.calls) == 128 and obj.planet_cycle_index == 128)
local generation = obj.changed_keys_for_current_cycle
obj.changed_keys_for_next_cycle.later = true
obj:on_planet_owner_changed(250, "NewOwner")
assert(obj.owners[250] == "NewOwner" and table.getn(obj.ownership_calls) == 1)
tick(true)
assert(table.getn(obj.calls) == 128) -- Same timestamp cannot exceed the budget.
now = 0.1
tick(true)
assert(table.getn(obj.calls) == 256 and obj.changed_keys_for_current_cycle == generation)
now = 0.2
tick(false)
assert(table.getn(obj.calls) == 300 and obj.planet_cycle_index == 0 and obj.last_update == now)
local seen = {}
for i, planet in ipairs(obj.calls) do
    assert(not seen[planet])
    seen[planet] = true
    assert(obj.generations[i] == generation and not obj.generations[i].later)
end
assert(obj.changed_keys_for_next_cycle.later)
now = 10.2
tick(false)
assert(table.getn(obj.calls) == 300) -- Strict > 10 interval retained.
now = 10.3
tick(false)
assert(table.getn(obj.calls) == 428 and obj.changed_keys_for_current_cycle.later)
now = 10.4
tick(false)
now = 10.5
tick(false)
assert(table.getn(obj.calls) == 600)

-- Old saves restore original functions, losing only the optimization.
dofile("original_key.lua")
local old = instance(300)
setmetatable(old, {__index=KeyDummyLifeCycleHandler})
now = 20
for i=1,300 do old:update(i) end
assert(table.getn(old.calls) == 300 and old.planet_cycle_index == 0)
local small = instance(1)
small:update(1)
assert(table.getn(small.calls) == 1 and small.planet_cycle_index == 0)
local empty = instance(0)
assert(empty.last_update == nil)

-- A partially completed sliced sweep retains its state across an ordinary save:
-- copying the scalar fields and keeping serialized tables/functions is sufficient.
local resumed = instance(129)
now = 30
for i=1,129 do resumed:update(i) end
assert(resumed.planet_cycle_index == 128)
local saved = {}
for key, value in pairs(resumed) do saved[key] = value end
setmetatable(saved, getmetatable(resumed))
now = 30.1
for i=1,129 do saved:update(i) end
assert(table.getn(saved.calls) == 129 and saved.planet_cycle_index == 0)

-- Periodic scoring work is gone; timer and other service statements still execute.
local other, outside = 0, 0
other_statement = function() other = other + 1 end
Debug_Print_Score_Vals = function() outside = outside + 1 end
GameScoringMessage = function() error("dump still active") end
Print_Stat_Table = GameScoringMessage
Print_Build_Stats_Table = GameScoringMessage
dofile("quiet.lua")
timer, CampaignGame = 39.9, true
GameService()
assert(timer == 0 and other == 1)
Outside()
assert(outside == 1)
CampaignGame = false
timer = 39.9
GameService()
assert(timer == 40 and other == 1)

