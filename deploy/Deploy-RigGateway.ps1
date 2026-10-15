#requires -Version 5.1
<#
.SYNOPSIS
    Deploys rig-gateway to a host that has no git, then PROVES the deployed tree
    matches the source it was copied from.

.DESCRIPTION
    Why this exists: the rig has no git, so "pull the fix" is not an option there.
    The first attempt at this replaced main() in place with a second copy of that
    function kept in the repo. That is the "config disagrees with the running
    server" failure the Skill warns about, committed as tooling: the copy silently
    drifted, and a later fix to server.py would not reach the host.

    So this script does not carry a copy of any code. It copies the whole package
    tree, then hashes every deployed .py against the source and refuses to claim
    success unless they match. A stale file is a failure, not a warning.

    Read-only by default: it deploys files and verifies them. It does not start
    the server -- use Start-RigGateway.ps1 for that.
#>
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Dest,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-TreeHashes([string]$root) {
    $map = @{}
    Get-ChildItem -LiteralPath $root -Recurse -File -Filter *.py |
        Where-Object { $_.FullName -notmatch '\\__pycache__\\' } |
        ForEach-Object {
            $rel = $_.FullName.Substring($root.Length).TrimStart('\', '/')
            $map[$rel] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    return $map
}

$srcPkg = Join-Path $Source 'rig_gateway'
if (-not (Test-Path -LiteralPath $srcPkg -PathType Container)) {
    throw "Source does not contain a rig_gateway package: $srcPkg"
}
$srcServer = Join-Path $srcPkg 'server.py'
if (-not (Test-Path -LiteralPath $srcServer -PathType Leaf)) {
    throw "server.py not found in source: $srcServer"
}

if ((Test-Path -LiteralPath $Dest) -and -not $Force) {
    throw "Destination already exists: $Dest. Pass -Force to overwrite it."
}

# --- fail fast on the bug this script used to carry -------------------------
# If the source still has the literal-membership test for host/port, deploying it
# would install a server that cannot bind a TCP address at all.
$text = [IO.File]::ReadAllText($srcServer, [Text.Encoding]::UTF8)

# One line per throw on purpose. Multi-line message concatenation inside throw()
# is what broke the earlier version of this tooling at parse time -- keep the
# messages single-line and the quoting trivial.
$badPredicate = 'accepts_kwargs\s*=\s*.host. in run_params'
if ($text -match $badPredicate) { throw 'Source server.py decides the bind by literal signature membership (misses **kwargs): the server would fail to bind. Fix that first.' }
if ($text -notmatch 'def resolve_http_binding') { throw 'Source server.py has no resolve_http_binding(); refusing to deploy an unverified bind path.' }

# --- copy ------------------------------------------------------------------
if (Test-Path -LiteralPath $Dest) { Remove-Item -LiteralPath $Dest -Recurse -Force }
New-Item -ItemType Directory -Path $Dest | Out-Null

$destPkg = Join-Path $Dest 'rig_gateway'
Copy-Item -LiteralPath $srcPkg -Destination $destPkg -Recurse -Force
Get-ChildItem -LiteralPath $destPkg -Recurse -Directory -Filter '__pycache__' |
    Remove-Item -Recurse -Force

foreach ($extra in @('pyproject.toml', 'README.md')) {
    $f = Join-Path $Source $extra
    if (Test-Path -LiteralPath $f -PathType Leaf) {
        Copy-Item -LiteralPath $f -Destination (Join-Path $Dest $extra) -Force
    }
}

# --- prove what landed is what was meant to land ---------------------------
$srcHashes = Get-TreeHashes $srcPkg
$dstHashes = Get-TreeHashes $destPkg

$missing = @($srcHashes.Keys | Where-Object { -not $dstHashes.ContainsKey($_) })
$extra = @($dstHashes.Keys | Where-Object { -not $srcHashes.ContainsKey($_) })
$diff = @($srcHashes.Keys | Where-Object {
    $dstHashes.ContainsKey($_) -and $dstHashes[$_] -ne $srcHashes[$_]
})

if ($missing.Count -or $extra.Count -or $diff.Count) {
    Write-Host 'DEPLOY MISMATCH:'
    $missing | ForEach-Object { Write-Host "  missing at destination: $_" }
    $extra   | ForEach-Object { Write-Host "  unexpected at destination: $_" }
    $diff    | ForEach-Object { Write-Host "  content differs: $_" }
    throw 'Deployed tree does not match the source. Not reporting success.'
}

Write-Host ("Deployed {0} files to {1} and verified every SHA-256 matches source." -f $srcHashes.Count, $Dest)
Write-Host 'Next: run Start-RigGateway.ps1 from the destination.'
