#requires -Version 7.2
param(
    [string]$EngineRoot = 'C:\UE\UE_5.9',
    [string]$OutputDirectory = '',
    [string]$EmsdkRoot = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (!$OutputDirectory) { $OutputDirectory = Join-Path $projectRoot 'Deployment\GHSWeb59' }
if (!$EmsdkRoot) { $EmsdkRoot = Join-Path $projectRoot 'Saved\Toolchains\emsdk' }
$sdkVersion = Join-Path $EmsdkRoot 'upstream\emscripten\emscripten-version.txt'
if (!(Test-Path $sdkVersion) -or (Get-Content $sdkVersion -Raw).Trim() -ne '6.0.10') {
    throw 'UE 5.9 requires an activated Emscripten 6.0.10 SDK. Pass -EmsdkRoot.'
}
$env:WASM_EMSDK_ROOT = $EmsdkRoot
$projectFile = Join-Path $projectRoot 'Test.uproject'
New-Item -ItemType Directory -Force (Join-Path $projectRoot 'Saved\StagedBuilds\Wasm') | Out-Null
& (Join-Path $EngineRoot 'Engine\Build\BatchFiles\Build.bat') TestEditor Win64 Development "-Project=$projectFile" -WaitMutex -NoHotReloadFromIDE
if ($LASTEXITCODE) { throw "Editor build failed: $LASTEXITCODE" }
$uatArgs = @(
    'BuildCookRun', "-project=$projectFile", '-target=TestGame', '-platform=Wasm',
    '-clientconfig=Shipping', '-build', '-cook', '-stage', '-pak', '-iostore',
    '-package', '-archive', "-archivedirectory=$OutputDirectory", '-unattended', '-utf8output',
    '-map=/Game/Maps/GHS_GlobalWarehouse+/Game/Maps/GHS_CAD_NormalWarehouse_ZcoolSmartFactory+/Game/Maps/MPR_CAD_Warehouse_B50B57',
    '-AdditionalCookerOptions=-unattended -nopause -nosplash -nullrhi -DisablePlugins=AllToolsets'
)
& (Join-Path $EngineRoot 'Engine\Build\BatchFiles\RunUAT.bat') @uatArgs
if ($LASTEXITCODE) { throw "Wasm packaging failed: $LASTEXITCODE" }
& (Join-Path $PSScriptRoot 'finalize_wasm_web_assets.ps1') -StageDirectory (Join-Path $projectRoot 'Saved\StagedBuilds\Wasm')
& (Join-Path $PSScriptRoot 'finalize_wasm_web_assets.ps1') -StageDirectory (Join-Path $OutputDirectory 'Wasm')
& (Join-Path $EngineRoot 'Engine\Binaries\ThirdParty\Python3\Win64\python.exe') (Join-Path $EngineRoot 'Engine\Platforms\Wasm\Build\Tools\deploy\check_stage.py') (Join-Path $OutputDirectory 'Wasm')
if ($LASTEXITCODE) { throw "Wasm stage verification failed: $LASTEXITCODE" }

