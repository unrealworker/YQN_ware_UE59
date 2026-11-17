#requires -Version 7.2
param(
    [Parameter(Mandatory=$true)][string]$ArchiveDirectory,
    [Parameter(Mandatory=$true)][string]$DeliveryDirectory,
    [string]$PythonDirectory = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$archive = (Resolve-Path -LiteralPath $ArchiveDirectory).Path
if (!$PythonDirectory) { $PythonDirectory = Join-Path $projectRoot 'Saved\Toolchains\emsdk\python\3.13.3_64bit' }
if (!(Test-Path -LiteralPath (Join-Path $archive 'Wasm\index.html'))) { throw 'Missing packaged site.' }
if (Test-Path -LiteralPath $DeliveryDirectory) { throw 'Delivery already exists; refusing to overwrite.' }
$zipPath = [IO.Path]::GetFullPath($DeliveryDirectory) + '.zip'
if (Test-Path -LiteralPath $zipPath) { throw 'Delivery zip already exists; refusing to overwrite.' }
New-Item -ItemType Directory -Path $DeliveryDirectory | Out-Null
$delivery = (Resolve-Path -LiteralPath $DeliveryDirectory).Path
Copy-Item -LiteralPath (Join-Path $archive 'Wasm') -Destination $delivery -Recurse
Copy-Item -LiteralPath (Join-Path $archive 'serve.py') -Destination $delivery
Copy-Item -Path (Join-Path $projectRoot 'Tools\WasmDeployment\*') -Destination $delivery -Recurse
Copy-Item -LiteralPath $PythonDirectory -Destination (Join-Path $delivery 'Runtime') -Recurse
& (Join-Path $delivery 'Runtime\python.exe') -I -B -c 'import ssl, http.server, json; print("Portable server runtime:", ssl.OPENSSL_VERSION)'
if ($LASTEXITCODE) { throw 'Portable Python runtime validation failed.' }
& (Join-Path $delivery 'Runtime\python.exe') -I -B (Join-Path $delivery 'start_server.py') --help
if ($LASTEXITCODE) { throw 'Portable launcher validation failed.' }
$rootPrefix = $delivery.TrimEnd('\') + '\'
$manifest = Get-ChildItem -LiteralPath $delivery -File -Recurse | ForEach-Object {
    [pscustomobject]@{path=$_.FullName.Substring($rootPrefix.Length).Replace('\','/');size=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $delivery 'file-manifest.json') -Encoding utf8
[IO.Compression.ZipFile]::CreateFromDirectory($delivery,$zipPath,[IO.Compression.CompressionLevel]::Optimal,$true)
$hash = Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
($hash.Hash.ToLowerInvariant() + '  ' + [IO.Path]::GetFileName($zipPath)) | Set-Content -LiteralPath ($zipPath + '.sha256') -Encoding ascii
Get-Item -LiteralPath $zipPath | Select-Object FullName,Length
