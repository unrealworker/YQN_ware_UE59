#requires -Version 5.1
#requires -RunAsAdministrator
param(
    [string]$DeploymentDirectory = '',
    [string]$TaskName = 'GHS-Warehouse-Web',
    [ValidateRange(1,65535)][int]$Port = 8800,
    [string]$BindAddress = '127.0.0.1',
    [ValidatePattern('^[A-Za-z0-9.-]+$')][string[]]$AllowedHosts = @()
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (!$DeploymentDirectory) { $DeploymentDirectory = Join-Path $projectRoot 'Deployment\GHS-Warehouse-Web-UE59-20261117-r2' }
$delivery = (Resolve-Path -LiteralPath $DeploymentDirectory).Path
$python = Join-Path $delivery 'Runtime\python.exe'
$server = Join-Path $delivery 'serve.py'
$site = Join-Path $delivery 'Wasm'
foreach ($required in @($python,$server,(Join-Path $site 'index.html'))) {
    if (!(Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing deployment file: $required" }
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "Task already exists: $TaskName. Inspect it before updating."
}
[void][Net.IPAddress]::Parse($BindAddress)
$arguments = '-I -B -u "{0}" --root "{1}" --bind {2} --port {3}' -f $server,$site,$BindAddress,$Port
foreach ($allowedHost in $AllowedHosts) { $arguments += ' --allow-host ' + $allowedHost }
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $delivery
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\LOCAL SERVICE' -LogonType ServiceAccount -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'GHS UE5.9 browser site: independent static HTTP backend. The existing HTTPS gateway forwards /web/ to loopback port 8800.'
Register-ScheduledTask -TaskName $TaskName -InputObject $task | Select-Object TaskName,State
Write-Output 'Registered only. Start the task after confirming the selected port is free.'
