#requires -Version 5.1
<#
.SYNOPSIS
    Starts rig-gateway on the remote host with the fixes that keep it alive.

.DESCRIPTION
    Two changes from a naive `python -m ... > log.txt` launch, both of which are
    the difference between a working channel and one that looks fine:

      1. stdout/stderr are NOT redirected to a pipe. Redirecting and never
         draining fills the ~64KB buffer and the server blocks permanently --
         every HTTP request then times out while the socket still accepts.
         Here the child inherits this console.

      2. ENABLE_QUICK_EDIT_MODE is cleared before launch. A user who
         click-drags text in this window stops the console servicing its handle
         and the server blocks on its next write.

    Read-only tier only. Tier 2/3 stay off until the machine's owner opts in.
#>
param(
    [string]$Root = $PSScriptRoot,
    [string]$BindIp = '127.0.0.1',
    [ValidateRange(1024, 65535)][int]$Port = 8099,
    [string]$ClientIp = '127.0.0.1',
    [string]$SandboxRoot = ''
)
if ($PSBoundParameters.ContainsKey('ClientIp')) {
    Write-Warning '-ClientIp is accepted for symmetry with the winremote launcher but is NOT enforced: rig-gateway has no IP allowlist. Restrict access with tailnet ACLs.'
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- clear QuickEdit/echo before starting the child (fix #2) ----------------
try {
    if (-not ('Win32Guard.ConsoleMode' -as [type])) {
        Add-Type -Namespace 'Win32Guard' -Name 'ConsoleMode' -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);
[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
'@
    }
    $h = [Win32Guard.ConsoleMode]::GetStdHandle(-11)
    $mode = [uint32]0
    if ($h -ne [IntPtr]::Zero -and [Win32Guard.ConsoleMode]::GetConsoleMode($h, [ref]$mode)) {
        [void][Win32Guard.ConsoleMode]::SetConsoleMode($h, $mode -band (-bnot 0x0040) -band (-bnot 0x0004))
        Write-Host 'Console QuickEdit/echo cleared.'
    }
} catch {
    Write-Warning 'Could not clear QuickEdit. Never drag-select text in this window, or the server will stop answering.'
}

# --- environment -------------------------------------------------------------
$py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { throw "venv python not found: $py" }
& $py -c "import sys; assert struct.calcsize('P')==8, 'need 64-bit'"
if ($LASTEXITCODE -ne 0) { throw 'Interpreter is not 64-bit.' }

# The package must be INSTALLED, not just present on disk. Running
# `python -I -m rig_gateway.server` fails with ModuleNotFoundError because -I
# removes the current directory from sys.path -- so an unpacked-but-uninstalled
# tree is invisible. Install it, then run without -I.
& $py -c "import rig_gateway, sys; sys.exit(0)" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'rig_gateway not importable; installing this tree into the venv...'
    & $py -m pip install --quiet --disable-pip-version-check --no-deps $Root
    if ($LASTEXITCODE -ne 0) { throw 'pip install of rig_gateway failed.' }
    & $py -c "import rig_gateway; print('installed from', rig_gateway.__file__)"
    if ($LASTEXITCODE -ne 0) { throw 'Still not importable after install.' }
}

if (-not $SandboxRoot) { $SandboxRoot = (Join-Path $Root 'sandbox') }
if (-not (Test-Path -LiteralPath $SandboxRoot)) { New-Item -ItemType Directory -Path $SandboxRoot | Out-Null }
$env:RIG_SANDBOX_ROOT = $SandboxRoot

# --- pre-flight: prove the bind decision BEFORE serving ----------------------
# A server that exits on a bad bind looks, from the client, exactly like a
# network fault. Catch it here, where the operator can see it, rather than
# letting them debug a tailnet that was never the problem.
& $py -c @"
import sys
from rig_gateway.server import resolve_http_binding, mcp
how = resolve_http_binding(mcp.run)
print('bind decision: run(%s)' % how)
sys.exit(0 if how == 'kwargs' else 2)
"@
if ($LASTEXITCODE -ne 0) {
    throw ('This rig_gateway cannot bind host/port through run() -- it would fall back to '
         + 'Settings and exit without listening. Redeploy from current source.')
}

Write-Host "rig-gateway starting on http://${BindIp}:${Port}/mcp"
Write-Host "sandbox root : $SandboxRoot  (writes confined here)"
Write-Host 'tiers: 1 only (read-only). Stop with Ctrl+C.'

# NOTE: rig-gateway has NO built-in authentication and NO IP allowlist. Binding to
# a tailnet address means every device on that tailnet can reach it. That is the
# documented design -- auth is meant to be explicit and added by the operator
# (reverse proxy, mTLS, or tailnet ACLs) rather than a silent default.
# Do not add a "client allowed" line here without also adding the code that enforces it.

# --- launch: inherited handles, no pipe (fix #1) -----------------------------
# No -I here: it strips the CWD from sys.path, which would hide an installed
# package only if it were not installed -- and we install it above. The venv
# itself is the isolation boundary, so -I would add nothing and break the import.
& $py -m rig_gateway.server --transport streamable-http --host $BindIp --port $Port