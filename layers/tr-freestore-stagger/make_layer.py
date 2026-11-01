"""Build the TR free-store stagger test layer: python -I -B make_layer.py <TR mod folder> <out folder>

Copies Thrawn's Revenge's Data/Scripts/FreeStore/GalacticFreeStore.lua into
<out>/Data/Scripts/FreeStore/ unchanged and appends STAGGER, which wraps
FreeStoreService so that each AI player's free-store pass runs at its own phase
of the 40 s cycle. TR's files are never written; the copy lives only in <out>.
Launch with the layer first: Modpath=<out> Modpath=<TR mod folder>.
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

SCRIPT = Path('Data/Scripts/FreeStore/GalacticFreeStore.lua')
# TR GalacticFreeStore.lua the layer was written against (Workshop 1125571106).
EXPECTED_SHA256 = 'eac113fe28d62453b68891acdbe5f29b3455014fb3770f0611dd9aefa85b8090'

# The engine runs a free-store state's Lua thread when ServiceRate seconds have
# passed since LastService, then calls On_Unit_Service for every unit once
# UnitServiceRate seconds have passed since LastUnitService, and writes both
# times back as globals. All AI states start together, so their passes share a
# frame. Stretching both rates once, by a per-player phase, moves this state's
# later passes by that phase; the next call restores TR's 40. Nothing else in
# the service changes.
STAGGER = '''

-- Alamo Profiler test layer (tr-freestore-stagger): only the timing changes.
StaggerSlots = 12
StaggerPeriod = 40
local Stagger_TR_FreeStoreService = FreeStoreService

function FreeStoreService()
    if StaggerPhase == nil and LastService ~= nil then
        local slot = PlayerObject.Get_ID()
        while slot >= StaggerSlots do
            slot = slot - StaggerSlots
        end
        StaggerPhase = slot * StaggerPeriod / StaggerSlots
        ServiceRate = StaggerPeriod + StaggerPhase
        UnitServiceRate = StaggerPeriod + StaggerPhase
    elseif ServiceRate ~= StaggerPeriod then
        ServiceRate = StaggerPeriod
        UnitServiceRate = StaggerPeriod
    end
    Stagger_TR_FreeStoreService()
end
'''


def check_destination(tr, out):
    """Refuse any output that is TR's folder, lies inside it, or contains it, or
    whose script is TR's own file (a symlink, junction alias or hard link)."""
    tr, out = Path(tr).resolve(), Path(out).resolve()
    if out == tr or tr in out.parents or out in tr.parents:
        raise SystemExit(f'output folder {out} overlaps the TR folder {tr}')
    dst = out / SCRIPT
    if dst.exists() and (dst.resolve() == (tr / SCRIPT).resolve() or dst.samefile(tr / SCRIPT)):
        raise SystemExit(f'{dst} is the TR script itself')
    return dst


def build(tr, out):
    dst = check_destination(tr, out)
    src = (Path(tr) / SCRIPT).read_bytes()
    if b'function FreeStoreService()' not in src or b'UnitServiceRate = 40' not in src:
        raise SystemExit('unexpected GalacticFreeStore.lua: no FreeStoreService or UnitServiceRate = 40')
    if EXPECTED_SHA256 and hashlib.sha256(src).hexdigest() != EXPECTED_SHA256:
        raise SystemExit('GalacticFreeStore.lua changed since the layer was written')
    dst.parent.mkdir(parents=True, exist_ok=True)
    newline = b'\r\n' if b'\r\n' in src else b'\n'
    # Write a new file and move it into place: an existing dst is replaced, never
    # written through, so a link that escaped the checks still cannot change TR.
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix='.stagger-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(src + STAGGER.encode().replace(b'\n', newline))
        os.replace(tmp, dst)
    except BaseException:
        os.unlink(tmp)
        raise
    return dst, hashlib.sha256(src).hexdigest()


if __name__ == '__main__':
    path, sha = build(sys.argv[1], sys.argv[2])
    print(path, 'from TR sha256', sha)
