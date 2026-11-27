#requires -Version 5.1
param([switch]$Inspect)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
[xml]$layout = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Panel.xaml') -Raw -Encoding UTF8
$reader = New-Object System.Xml.XmlNodeReader $layout
try { $window = [Windows.Markup.XamlReader]::Load($reader) } finally { $reader.Close() }
$ui = @{}
foreach ($name in 'RefreshBtn','StartBtn','BootBtn','TsBtn','GatewayState','TsState','BootState','Url','Message') {
    $ui[$name] = $window.FindName($name)
}
$tsCli = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'

function Label([string]$key) { $window.Resources[$key] }
function Flag([bool]$value) { if ($value) { Label On } else { Label Off } }

function Get-Deployment {
    $task = Get-ScheduledTask -TaskName 'rig-gateway' -TaskPath '\' -ErrorAction SilentlyContinue
    $actions = @($task.Actions)
    $triggers = @($task.Triggers)
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not $task -or $task.Description -ne 'rig-gateway scheduled task' -or
        $actions.Count -ne 1 -or $actions[0].Execute -ne $powershell -or
        $triggers.Count -ne 1 -or $triggers[0].CimClass.CimClassName -ne 'MSFT_TaskBootTrigger') {
        throw (Label Invalid)
    }
    $pattern = '^-NoProfile -ExecutionPolicy Bypass -File "([^"]+)" -Root "([^"]+)" -BindIp "([0-9.]+)" -Port (\d+) -Tier ([123])$'
    if ($actions[0].Arguments -notmatch $pattern) { throw (Label Invalid) }
    $runner, $root, $addr, $port, $tier = $Matches[1], $Matches[2], $Matches[3], [int]$Matches[4], $Matches[5]
    if ($runner -ne (Join-Path $root 'Run-Task.ps1') -or -not (Test-Path -LiteralPath $runner -PathType Leaf) -or
        $addr -eq '0.0.0.0' -or $port -lt 1 -or $port -gt 65535) { throw (Label Invalid) }
    [pscustomobject]@{Task=$task; Trigger=$triggers[0]; Address=([ipaddress]$addr).ToString(); Port=$port; Tier=$tier}
}

function Get-Listeners($deployment) {
    Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq $deployment.Port
}

function Get-TailscaleState {
    $svc = Get-Service -Name Tailscale -ErrorAction SilentlyContinue
    if (-not $svc -or -not (Test-Path -LiteralPath $tsCli -PathType Leaf)) { return (Label TsAbsent) }
    if ($svc.Status -ne 'Running') { return [string]$svc.Status }
    $json = & $tsCli status --json 2>$null
    if (-not $json) { return 'Service running / status unavailable' }
    ($json | ConvertFrom-Json).BackendState
}

function Update-Panel {
    $ui.StartBtn.IsEnabled = $false
    $ui.BootBtn.IsEnabled = $false
    $ui.Url.Text = ''
    $ui.BootState.Text = ''
    try {
        $d = Get-Deployment
        $ui.Url.Text = 'http://{0}:{1}/mcp' -f $d.Address, $d.Port
        $listeners = @(Get-Listeners $d)
        $listener = if ($listeners.LocalAddress -contains $d.Address) { Label Listening }
                    elseif ($listeners.Count) { Label Busy } else { Label Idle }
        $ui.GatewayState.Text = "$listener  /  Tier $($d.Tier)  /  $(Label Task) $($d.Task.State)"
        $ui.StartBtn.IsEnabled = -not $listeners.Count -and $d.Task.State -notin 'Disabled','Running'
        $logon = Get-ScheduledTask -TaskName 'rig-gateway-logon' -TaskPath '\' -ErrorAction SilentlyContinue
        $logonState = Label Missing
        if ($logon -and @($logon.Actions).Count -eq 1 -and
            $logon.Actions[0].Execute -eq $d.Task.Actions[0].Execute -and
            $logon.Actions[0].Arguments -eq $d.Task.Actions[0].Arguments) {
            $active = @($logon.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' -and $_.Enabled })
            $logonState = Flag ($logon.State -ne 'Disabled' -and $active.Count -gt 0)
        }
        $ui.BootState.Text = "$(Label Boot) $(Flag ($d.Trigger.Enabled -and $d.Task.State -ne 'Disabled'))  /  $(Label Logon) $logonState"
        $ui.BootBtn.Tag = -not $d.Trigger.Enabled
        $ui.BootBtn.Content = if ($d.Trigger.Enabled) { Label BootOff } else { Label BootOn }
        $ui.BootBtn.IsEnabled = $d.Task.State -ne 'Disabled'
    } catch { $ui.GatewayState.Text = $_.Exception.Message }
    try {
        $ui.TsState.Text = Get-TailscaleState
        $ui.TsBtn.IsEnabled = $ui.TsState.Text -ne (Label TsAbsent)
    } catch { $ui.TsState.Text = $_.Exception.Message }
}

function Invoke-PanelAction([scriptblock]$action) {
    try { $ui.Message.Text = & $action } catch { $ui.Message.Text = $_.Exception.Message }
    Update-Panel
}

$ui.RefreshBtn.Add_Click({ Update-Panel })
$ui.StartBtn.Add_Click({ Invoke-PanelAction {
    $d = Get-Deployment
    if (@(Get-Listeners $d).Count) { return (Label Busy) }
    if ($d.Task.State -eq 'Disabled') { throw (Label TaskDisabled) }
    if ($d.Task.State -ne 'Running') { Start-ScheduledTask -InputObject $d.Task }
    Label Started
} })
$ui.BootBtn.Add_Click({ Invoke-PanelAction {
    $d = Get-Deployment
    if ($d.Task.State -eq 'Disabled') { throw (Label TaskDisabled) }
    $desired = [bool]$ui.BootBtn.Tag
    if ($d.Trigger.Enabled -ne $desired) {
        $d.Trigger.Enabled = $desired
        Set-ScheduledTask -TaskName 'rig-gateway' -TaskPath '\' -Trigger $d.Trigger | Out-Null
    }
    if ((Get-Deployment).Trigger.Enabled -ne $desired) { throw (Label Invalid) }
    Label Saved
} })
$ui.TsBtn.Add_Click({ Invoke-PanelAction {
    $svc = Get-Service -Name Tailscale
    if ($svc.Status -ne 'Running') { Start-Service -InputObject $svc }
    if ((Get-TailscaleState) -eq 'Running') { return (Label TsReady) }
    # The operator can see any sign-in URL or existing-preference conflict.
    Start-Process -FilePath $tsCli -ArgumentList 'up','--timeout=60s'
    Label TsStart
} })

Update-Panel
if ($Inspect) {
    [pscustomobject]@{ Endpoint=$ui.Url.Text; Gateway=$ui.GatewayState.Text; Tailscale=$ui.TsState.Text
        Autostart=$ui.BootState.Text; StartAvailable=$ui.StartBtn.IsEnabled; BootControl=$ui.BootBtn.IsEnabled }
    return
}
[void]$window.ShowDialog()
