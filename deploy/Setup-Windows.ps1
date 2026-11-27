#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory)][ValidateSet('Host','Client')][string]$Role,
      [ValidateSet('Codex','Claude')][string]$Client,
      [string]$Record, [ValidateRange(1024,65535)][int]$Port = 8099)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$panel = Join-Path $PSScriptRoot 'operator-panel\Panel.ps1'
$helper = Join-Path $root 'skills\rig-remote-ops\scripts\setup_connection.py'
if (-not $Record) { $Record = Join-Path $root 'rig-connection.json' }

function Install-PackageId([string]$id) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "Install Windows App Installer (WinGet), then rerun setup. Required package: $id"
    }
    & winget.exe install --id $id --exact --source winget --accept-package-agreements --accept-source-agreements | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "WinGet could not install $id (exit $LASTEXITCODE)." }
    $env:Path += ';' + [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}

function Find-Python {
    foreach ($spec in 'py','python') {
        $exe = Get-Command "$spec.exe" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $exe) { continue }
        $opts = @()
        if ($spec -eq 'py') { $opts += '-3' }
        try {
            $out = & $exe.Source @opts -c 'import sys; print(sys.executable) if sys.version_info >= (3,10) else sys.exit(1)' 2>$null
        } catch {
            # Windows App Installer aliases may exist before Python is installed.
            continue
        }
        if ($LASTEXITCODE -eq 0 -and $out -and (Test-Path -LiteralPath $out -PathType Leaf)) { return $out }
    }
}

function Connect-Tailnet {
    $cli = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (-not (Test-Path -LiteralPath $cli)) { Install-PackageId 'Tailscale.Tailscale' }
    if ((Get-Service Tailscale).Status -ne 'Running') { Start-Service Tailscale }
    $status = (& $cli status --json | Out-String) | ConvertFrom-Json
    if ($status.BackendState -ne 'Running') {
        & $cli up --timeout=5m | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Complete Tailscale sign-in, then rerun setup.' }
    }
    $addr = & $cli ip -4 | Select-Object -First 1
    if ($LASTEXITCODE -ne 0 -or -not $addr) { throw 'Tailscale IPv4 is unavailable.' }
    return $addr
}

try {
    if ($Role -eq 'Client' -and -not (Test-Path -LiteralPath $Record -PathType Leaf)) {
        Add-Type -AssemblyName PresentationFramework
        $dialog = New-Object Microsoft.Win32.OpenFileDialog
        $dialog.Title = 'Select rig-connection.json from the target PC'
        $dialog.Filter = 'Deployment record (*.json)|*.json'
        if (-not $dialog.ShowDialog()) { throw 'Select the host deployment record to connect.' }
        $Record = $dialog.FileName
    }
    $ip = Connect-Tailnet
    $python = Find-Python
    if (-not $python) { Install-PackageId 'Python.Python.3.12'; $python = Find-Python }
    if (-not $python) { throw 'Python 3.10+ was not found. Reopen setup after installation.' }
    if ($Role -eq 'Client') {
        if (-not $Client) {
            $choice = Read-Host 'MCP client: 1 Codex [default], 2 Claude Code'
            $Client = switch ($choice) { '2' { 'Claude' } '1' { 'Codex' } '' { 'Codex' } default { throw 'Choose 1 or 2.' } }
        }
        if (-not (Get-Command $Client -ErrorAction SilentlyContinue)) {
            $id = if ($Client -eq 'Codex') { 'OpenAI.Codex' } else { 'Anthropic.ClaudeCode' }
            Install-PackageId $id
        }
        & $python $helper $Record $Client
        if ($LASTEXITCODE -ne 0) { throw 'Client registration or verification failed.' }
        return
    }

    $installed = Get-ScheduledTask -TaskPath '\' | Where-Object TaskName -in 'rig-gateway','rig-gateway-user'
    if (-not $installed) {
        if (Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq $Port) {
            throw "Port $Port is occupied. Select a free -Port or verify the existing deployment."
        }
        $venv = Join-Path $root '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $venv)) {
            & $python -m venv (Join-Path $root '.venv')
            if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
        }
        & $venv -m pip install "$root[mcp]"
        if ($LASTEXITCODE -ne 0) { throw 'Gateway installation failed.' }
        $action = New-ScheduledTaskAction -Execute (Join-Path $root '.venv\Scripts\pythonw.exe') -Argument "-I -m rig_gateway.server --transport streamable-http --host $ip --port $Port"
        $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([timespan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName 'rig-gateway-user' -TaskPath '\' -Description 'rig-gateway one-click Tier 1' -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    }
    $deployment = & $panel -Describe
    if ($deployment.Address -ne $ip) { throw 'Existing task binds another address. Check it in the operator panel.' }
    $listeners = @(Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq $deployment.Port)
    if (-not $listeners.Count -and $deployment.Task.State -ne 'Running') {
        Start-ScheduledTask -InputObject $deployment.Task
    }
    $deadline = (Get-Date).AddSeconds(45)
    while ($listeners.LocalAddress -notcontains $ip) {
        if ($listeners.Count -or (Get-Date) -gt $deadline) { throw 'Expected gateway listener unavailable. Inspect the task and port.' }
        Start-Sleep -Seconds 1
        $listeners = @(Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq $deployment.Port)
    }
    & $python $helper $Record export $ip $deployment.Port $deployment.Tier ([Environment]::MachineName)
    if ($LASTEXITCODE -ne 0) { throw 'Host acceptance failed. No new handoff was issued.' }
    Write-Host "Verified http://${ip}:$($deployment.Port)/mcp (Tier $($deployment.Tier))."
    Write-Host "Give this file to the client PC: $Record"
    Write-Host "Host controls: $(Join-Path $PSScriptRoot 'operator-panel\Open-Panel.cmd')"
} catch {
    Write-Error -ErrorAction Continue $_.Exception.Message
    exit 1
}
