$ErrorActionPreference='Stop'
$tempRoot = (New-Item -ItemType Directory -Path (Join-Path $env:TEMP ([guid]::NewGuid().ToString()))).FullName
try {
    $runner = New-Item -ItemType File -Path (Join-Path $tempRoot 'Run-Task.ps1')
    $bootTrigger = [pscustomobject]@{Enabled=$true;CimClass=@{CimClassName='MSFT_TaskBootTrigger'}}
    $action = @{Execute=(Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
        Arguments=('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Root "{1}" -BindIp "127.0.0.1" -Port 8112 -Tier 1' -f $runner.FullName,$tempRoot)}
    $taskFixture = [pscustomobject]@{Description='rig-gateway scheduled task';State='Ready';Actions=@($action);Triggers=@($bootTrigger)}
    $script:started = 0
    $script:saved = 0
    $script:ports = @()
    function Get-ScheduledTask($TaskName,$TaskPath) { if ($TaskName -eq 'rig-gateway') { $taskFixture } }
    function Get-NetTCPConnection($State) { $script:ports }
    function Get-Service($Name) { return $null }
    function Start-ScheduledTask($InputObject) { $script:started++ }
    function Set-ScheduledTask($TaskName,$TaskPath,$Trigger) {
        if ($TaskName -ne 'rig-gateway' -or $TaskPath -ne '\') { throw 'wrong task' }
        $script:saved++
    }
    . (Join-Path $PSScriptRoot '../deploy/operator-panel/Panel.ps1') -Inspect | Out-Null
    function Click($button) {
        $button.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
    }
    if ($ui.Url.Text -ne 'http://127.0.0.1:8112/mcp' -or -not $ui.StartBtn.IsEnabled) { throw 'endpoint or start state' }
    Click $ui.StartBtn
    if ($script:started -ne 1) { throw 'start was not dispatched' }
    Click $ui.BootBtn
    if ($script:saved -ne 1 -or $bootTrigger.Enabled) { throw 'boot trigger disable failed' }
    Click $ui.BootBtn
    if ($script:saved -ne 2 -or -not $bootTrigger.Enabled) { throw 'boot trigger enable failed' }
    $script:ports = @([pscustomobject]@{LocalPort=8112;LocalAddress='127.0.0.1'})
    Update-Panel
    if ($ui.StartBtn.IsEnabled) { throw 'duplicate start enabled' }
    $action.Arguments='-File "unrelated.ps1"'
    Update-Panel
    if ($ui.BootBtn.IsEnabled -or $ui.StartBtn.IsEnabled) { throw 'unexpected action accepted' }
    'Panel controls passed.'
} finally {
    if ($runner) { Remove-Item -LiteralPath $runner.FullName }
    Remove-Item -LiteralPath $tempRoot
}
