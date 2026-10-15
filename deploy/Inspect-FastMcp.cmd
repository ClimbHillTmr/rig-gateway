@echo off
rem Diagnostic probe: print the REAL FastMCP run() signature and Settings fields on
rem THIS host, so the launcher can be reasoned about from facts instead of guesses.
rem
rem Why it matters: the bind decision once shipped as a literal test for "host" in the
rem run() parameters. Modern FastMCP declares run(self, transport, **kwargs), so that
rem test was always False, the server fell through to Settings -- which has no host
rem field -- and exited without ever binding. This probe is what makes that visible.
rem
rem ASCII-only on purpose: the console codepage on a fresh Windows host mangles
rem non-ASCII output, and a diagnostic that prints garbage is not a diagnostic.
setlocal
cd /d %~dp0..

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

echo === versions ===
"%PY%" -c "import importlib.metadata as m; print('mcp', m.version('mcp'))" 2>nul || echo mcp not installed

echo === run() signature ===
"%PY%" -c "import inspect; from rig_gateway.server import mcp; print(inspect.signature(mcp.run))"

echo === does run() accept host/port? ===
"%PY%" -c "import inspect; from rig_gateway.server import mcp; p=inspect.signature(mcp.run).parameters; print('host in params :', 'host' in p); print('port in params :', 'port' in p); print('has **kwargs   :', any(v.kind==inspect.Parameter.VAR_KEYWORD for v in p.values()))"

echo === the decision this build will make ===
"%PY%" -c "from rig_gateway.server import resolve_http_binding, mcp; print('resolve_http_binding ->', resolve_http_binding(mcp.run))"

echo === Settings fields (for the fallback path only) ===
"%PY%" -c "from rig_gateway.server import mcp; print(sorted(type(mcp.settings).model_fields.keys()))"

echo === tier inventory as configured ===
"%PY%" -c "from rig_gateway import server; server.build(False, False); print(sorted(server.mcp._tool_manager._tools.keys()))"

echo PROBE_DONE
