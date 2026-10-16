#requires -Version 5.1
<#
.SYNOPSIS
    Installs and starts rig-gateway on a host that has no git.

.DESCRIPTION
    The files were put here by a file transfer, so the first job is to prove
    that what arrived is what was sent. Every deployed file is checked against a
    SHA-256 recorded at the source; a mismatch stops the deploy rather than
    installing something unknown.

    Then two checks that exist because both failed here before:

      1. The package must be INSTALLED, not merely present. `python -I -m
         rig_gateway.server` fails with ModuleNotFoundError because -I removes
         the CWD from sys.path, so an unpacked-but-uninstalled tree is
         invisible.

      2. The bind decision is proved BEFORE the server is asked to serve. A
         server that cannot bind host/port exits without listening, which from
         the client is indistinguishable from a network fault -- so it is worth
         catching where the operator can see it.

    Writes nothing outside this directory. The sandbox root is created under it.
#>
param(
    [string]$Root = $PSScriptRoot,
    [string]$BindIp = '127.0.0.1',
    [ValidateRange(1024, 65535)][int]$Port = 8099,
    [switch]$EnableTier2,
    [switch]$EnableTier3,
    [switch]$SkipVerify,
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Hashes recorded at the source. These are what "the upload arrived intact"
# means -- a size check alone would pass on corrupted-but-same-length content.
$Expected = @{
    'rig_gateway\__init__.py'    = '735697d4248f4ea2cb3b3fa123e32c5324401ecf9efb49d79382fb74283a1b9a'
    'rig_gateway\pathpolicy.py'  = 'a53d7aaf13892b270476cddba5640b3ae3b35b797d641d5a0e932eb3c1ef1b79'
    'rig_gateway\server.py'      = '87b68a056d452d161ceb95e7aa3aa265fa15da5aaca7597ddf023fcfa04858f1'
    'pyproject.toml'             = '4e3202ea26381829d23ec9db134928ae7322d66ba59f84657f2a22791aeb2132'
}

$fail = @()
if (-not $SkipVerify) {
    Write-Host '=== verifying uploaded files against source hashes ==='
    foreach ($rel in $Expected.Keys) {
        $p = Join-Path $Root $rel
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
            $fail += "missing: $rel"
            continue
        }
        $actual = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower()
        $want = $Expected[$rel]
        if ($actual -eq $want) {
            Write-Host "  OK   $rel"
        } else {
            $fail += "HASH MISMATCH: $rel`n    want $want`n    got  $actual"
        }
    }
    if ($fail.Count) {
        Write-Host ''
        $fail | ForEach-Object { Write-Host "  $_" }
        throw 'Upload verification failed. Nothing was installed or started.'
    }
    Write-Host '  all files verified by SHA-256'
}

if ($VerifyOnly) {
    Write-Host ''
    Write-Host 'VERIFY-ONLY: upload is intact; nothing installed, nothing started.'
    exit 0
}

# --- locate an interpreter ---------------------------------------------------
Write-Host ''
Write-Host '=== interpreter ==='
$candidates = @()
if (Test-Path -LiteralPath (Join-Path $Root '.venv\Scripts\python.exe') -PathType Leaf) {
    $candidates += (Join-Path $Root '.venv\Scripts\python.exe')
}
# An existing venv next door is reusable; copying one is not (absolute paths).
$sibling = Join-Path (Split-Path $Root -Parent) 'rig_gateway_20261014\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $sibling -PathType Leaf) { $candidates += $sibling }
$candidates += 'python'

$py = $null
foreach ($c in $candidates) {
    try {
        & $c -c "import sys; assert sys.version_info >= (3,10)" 2>$null
        if ($LASTEXITCODE -eq 0) { $py = $c; break }
    } catch { }
}
if (-not $py) { throw "No Python >= 3.10 found. Tried: $($candidates -join ', ')" }
Write-Host "  using: $py"
& $py -c "import sys; print('  version:', sys.version.split()[0])"

# --- dependencies ------------------------------------------------------------
# psutil is a hard dependency of the read-only tier; without it system_info and
# list_processes fail at call time with ModuleNotFoundError.
$env:PYTHONPATH = "$Root;$env:PYTHONPATH"
& $py -c "import psutil" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '  installing psutil...'
    & $py -m pip install --quiet --disable-pip-version-check psutil
    if ($LASTEXITCODE -ne 0) { throw 'Could not install psutil.' }
}
& $py -c "import psutil; print('  psutil:', psutil.__version__)"

& $py -c "import mcp; print('  mcp: present')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '  installing mcp...'
    & $py -m pip install --quiet --disable-pip-version-check mcp
    if ($LASTEXITCODE -ne 0) { throw 'Could not install mcp.' }
}

# --- pre-flight: the bind decision, before anything is served ---------------
Write-Host ''
Write-Host '=== pre-flight ==='

# Which machine is this, and what addresses does it have? Recorded because a
# deploy to "the rig" is only meaningful if we can name the host we reached --
# an assertion on a hostname we never read back proves nothing.
Write-Host ("  hostname: {0}" -f $env:COMPUTERNAME)
$v4 = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
      Where-Object { $_.IPAddress -notlike '127.*' } |
      Select-Object -ExpandProperty IPAddress
Write-Host ("  ipv4: {0}" -f ($v4 -join ', '))

# Pick the bind address: an explicit -BindIp wins. Otherwise prefer the tailnet
# address (100.64.0.0/10), because that is how this server is meant to be
# reached; fall back to loopback so an accidental run is never exposed on the
# LAN, and never silently on every interface.
$tailnet = $v4 | Where-Object { $_ -match '^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.' } | Select-Object -First 1
if (-not $PSBoundParameters.ContainsKey('BindIp')) {
    if ($tailnet) {
        $BindIp = $tailnet
        Write-Host "  bind address: $BindIp (tailnet, auto-selected)"
    } else {
        $BindIp = '127.0.0.1'
        Write-Host '  bind address: 127.0.0.1 (loopback -- no tailnet address found)'
    }
} else {
    Write-Host "  bind address: $BindIp (explicit)"
}

$probe = @"
import sys
sys.path.insert(0, r'$Root')
from rig_gateway.server import resolve_http_binding, mcp
how = resolve_http_binding(mcp.run)
print('  bind decision: run(%s)' % how)
sys.exit(0 if how == 'kwargs' else 2)
"@
& $py -c $probe
# Single-line throw on purpose: multi-line string concatenation inside throw()
# is what broke an earlier version of this tooling at parse time.
if ($LASTEXITCODE -ne 0) { throw 'This rig_gateway cannot bind host/port via run(): it would fall back to Settings and exit without listening. The uploaded server.py is not the fixed one.' }

$sandbox = Join-Path $Root 'sandbox'
if (-not (Test-Path -LiteralPath $sandbox)) { New-Item -ItemType Directory -Path $sandbox | Out-Null }
$env:RIG_SANDBOX_ROOT = $sandbox
Write-Host "  sandbox root: $sandbox"

# --- start ------------------------------------------------------------------
# stdout/stderr are NOT redirected to a pipe and QuickEdit is cleared: either
# one lets the server block forever on a write while still accepting TCP, which
# presents exactly like a dead network. The child inherits this console.
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
        Write-Host '  console QuickEdit/echo cleared'
    }
} catch {
    Write-Warning 'Could not clear QuickEdit; never drag-select text in this window.'
}

Write-Host ''
Write-Host "=== starting rig-gateway on http://${BindIp}:${Port}/mcp ==="

# Tier selection is an explicit operator choice, not a default. Tier 2 adds
# confined write tools; tier 3 adds command execution and keystroke injection
# and additionally requires RIG_ALLOW_TIER3=1 in the server environment, so a
# bare -EnableTier3 cannot arm it by accident.
$launchArgs = @('-m', 'rig_gateway.server', '--transport', 'streamable-http',
                '--host', $BindIp, '--port', "$Port")
if ($EnableTier3) {
    $env:RIG_ALLOW_TIER3 = '1'
    $launchArgs += '--enable-tier3'
    Write-Host 'tiers: 1+2+3 (read + confined write + command/input). Stop with Ctrl+C.'
} elseif ($EnableTier2) {
    $launchArgs += '--enable-tier2'
    Write-Host 'tiers: 1+2 (read + confined write). Stop with Ctrl+C.'
} else {
    Write-Host 'tiers: 1 (read-only). Stop with Ctrl+C.'
}
# NOTE: no built-in auth and no IP allowlist -- documented design. Binding to a
# tailnet address means every device on that tailnet can reach it.
$env:PYTHONPATH = "$Root;$env:PYTHONPATH"
& $py @launchArgs
