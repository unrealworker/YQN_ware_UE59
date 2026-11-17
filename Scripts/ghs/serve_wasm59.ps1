param(
    [string]$EngineRoot = 'C:\UE\UE_5.9',
    [string]$StageDirectory = '',
    [int]$Port = 8800,
    [string]$BindAddress = '127.0.0.1',
    [string]$Certificate = '',
    [string]$PrivateKey = '',
    [string[]]$AllowedHosts = @()
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (!$StageDirectory) {
    $portableStage = Join-Path $projectRoot 'Deployment\GHS-Warehouse-Web-UE59-20261117-r2\Wasm'
    $StageDirectory = if (Test-Path (Join-Path $portableStage 'index.html')) { $portableStage } else { Join-Path $projectRoot 'Deployment\GHSWeb59\Wasm' }
}
if (!(Test-Path (Join-Path $StageDirectory 'index.html'))) { throw "Missing packaged index.html: $StageDirectory" }
if (($Certificate -eq '') -ne ($PrivateKey -eq '')) { throw 'Pass both -Certificate and -PrivateKey.' }
if ($BindAddress -notin @('127.0.0.1', 'localhost', '::1') -and !$Certificate) {
    throw 'LAN WebGPU requires HTTPS. Pass a trusted TLS certificate and private key.'
}
$serverArgs = @((Join-Path $EngineRoot 'Engine\Platforms\Wasm\Build\Tools\web\serve.py'), '--root', $StageDirectory, '--port', "$Port", '--bind', $BindAddress)
if ($Certificate) { $serverArgs += @('--tls-cert', $Certificate, '--tls-key', $PrivateKey) }
foreach ($allowedHost in $AllowedHosts) { $serverArgs += @('--allow-host', $allowedHost) }
& (Join-Path $EngineRoot 'Engine\Binaries\ThirdParty\Python3\Win64\python.exe') @serverArgs
if ($LASTEXITCODE) { throw "Web server failed: $LASTEXITCODE" }
