#requires -Version 5.1
<#
.SYNOPSIS
    Patches rig_gateway/server.py on this host: replaces main() with the
    version that probes FastMCP's run() signature instead of assuming it.

.DESCRIPTION
    Why this exists: the original code assigned mcp.settings.host, which raises
    ValueError on FastMCP versions whose Settings model has no such field. The
    replacement detects which calling convention this FastMCP supports, and
    fails loudly rather than silently binding 127.0.0.1.

    The script is idempotent and refuses to run twice. It verifies the result
    parses as Python before finishing.
#>
param(
    [string]$Root = $PSScriptRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$target = Join-Path $Root 'rig_gateway\server.py'
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
    throw "server.py not found at $target"
}

$text = [IO.File]::ReadAllText($target, [Text.Encoding]::UTF8)

if ($text -match 'inspect\.signature\(mcp\.run\)') {
    Write-Host 'ALREADY PATCHED - nothing to do.'
    exit 0
}

$start = $text.IndexOf('def main() -> None:')
if ($start -lt 0) { throw 'Could not find "def main()" in server.py' }
$end = $text.IndexOf('if __name__ == "__main__":', $start)
if ($end -lt 0) { throw 'Could not find the __main__ guard after main()' }

$patchFile = Join-Path $PSScriptRoot 'patch_main.py'
if (-not (Test-Path -LiteralPath $patchFile -PathType Leaf)) {
    throw "Patch body not found next to this script: $patchFile"
}
$patch = [IO.File]::ReadAllText($patchFile, [Text.Encoding]::UTF8).TrimEnd()

# patch_main.py already ends with its own __main__ guard, and $text's tail has
# one too. Appending both duplicates it, so keep the patch's and drop the tail's.
$patchHasGuard = $patch.Contains('if __name__ == "__main__":')
if ($patchHasGuard) {
    $tail = $text.Substring($end)
    $guardAt = $tail.IndexOf('if __name__ == "__main__":', [StringComparison]::Ordinal)
    if ($guardAt -ge 0) { $tail = $tail.Substring(0, $guardAt) }
    $newText = $text.Substring(0, $start) + $patch + "`r`n" + $tail.TrimEnd() + "`r`n"
} else {
    $newText = $text.Substring(0, $start) + $patch + "`r`n`r`n" + $text.Substring($end)
}

$backup = "$target.bak-" + (Get-Date -Format 'yyyyMMdd_HHmmss')
Copy-Item -LiteralPath $target -Destination $backup -Force
[IO.File]::WriteAllText($target, $newText, (New-Object Text.UTF8Encoding($false)))

Write-Host "Patched. Backup: $backup"

# --- prove it still parses before declaring success -------------------------
$py = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $py -PathType Leaf) {
    & $py -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())" $target
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'Patched file does not parse. Restoring the backup.'
        Copy-Item -LiteralPath $backup -Destination $target -Force
        throw 'Syntax check failed; original restored.'
    }
    Write-Host 'Syntax check: OK'
} else {
    Write-Warning 'venv python not found; skipped the syntax check.'
}
Write-Host 'Done. Restart the gateway for this to take effect.'
