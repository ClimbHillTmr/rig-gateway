#requires -Version 5.1
<#
.SYNOPSIS
    SUPERSEDED AND DISABLED. Use Deploy-RigGateway.ps1 instead.

.DESCRIPTION
    This script replaced main() in server.py with a second copy of that function
    kept in the repo (patch_main.py). That is the "config disagrees with the
    running server" failure the Skill warns about, committed as tooling:

      * the copy drifted from the real source, so a later fix would not reach a
        host deployed this way;
      * the copy it shipped carried the literal-membership bind test that stops
        the server binding a TCP address at all -- deploying it would install a
        server that cannot start.

    It is kept only so an operator following an older note finds a clear refusal
    instead of a silent regression. Deploy-RigGateway.ps1 copies the whole
    package and verifies every deployed file by SHA-256 against the source, so
    running code and source cannot diverge.
#>
[CmdletBinding()]
param(
    [string]$Root = $PSScriptRoot
)

Write-Host 'SUPERSEDED: this script patches server.py with a stale copy of main().'
Write-Host 'It would break the bind path. Nothing has been changed.'
Write-Host ''
Write-Host 'Use instead:'
Write-Host '    Deploy-RigGateway.ps1 -Source <repo on a machine with git> -Dest <host path>'
Write-Host '    Start-RigGateway.ps1   (from the destination, to run it)'
exit 1
