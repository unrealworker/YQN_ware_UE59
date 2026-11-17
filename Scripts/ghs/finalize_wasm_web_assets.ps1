#requires -Version 7.2
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$StageDirectory)
$ErrorActionPreference = 'Stop'
$stage = (Resolve-Path -LiteralPath $StageDirectory).Path
$worker = Join-Path $stage 'sw.js'
if (!(Test-Path -LiteralPath (Join-Path $stage 'wasm-manifest.json'))) { throw 'Expected a packaged Wasm stage.' }
$text = [IO.File]::ReadAllText($worker)
$pattern = 'function typeOf\(url\) \{[\s\S]*?\r?\n\}'
$matches = [regex]::Matches($text, $pattern)
if ($matches.Count -ne 1) { throw 'Unrecognized service worker: expected one typeOf(url) function.' }
$old = $matches[0].Value
$known = @'
function typeOf(url) {
  if (url.endsWith('.wasm')) return 'application/wasm';
  if (url.endsWith('.js')) return 'text/javascript';
  return 'application/octet-stream';
}
'@
$replacement = @'
function typeOf(url) {
  // GHS_WEB_MIME_TYPES: HUD assets share the engine cache and retain their browser content types.
  const extension = url.split(/[?#]/, 1)[0].split('.').pop().toLowerCase();
  const types = {
    wasm: 'application/wasm', js: 'text/javascript', mjs: 'text/javascript',
    css: 'text/css; charset=utf-8', html: 'text/html; charset=utf-8',
    json: 'application/json', webmanifest: 'application/manifest+json',
    txt: 'text/plain; charset=utf-8', csv: 'text/csv; charset=utf-8',
    svg: 'image/svg+xml', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg',
    webp: 'image/webp', gif: 'image/gif', ico: 'image/x-icon',
    ttf: 'font/ttf', otf: 'font/otf', woff: 'font/woff', woff2: 'font/woff2'
  };
  return types[extension] || 'application/octet-stream';
}
'@
if ($old.Replace("`r`n", "`n") -ne $known.Replace("`r`n", "`n") -and
    $old.Replace("`r`n", "`n") -ne $replacement.Replace("`r`n", "`n")) {
    throw 'Unrecognized typeOf(url) implementation; review the new engine template before patching.'
}
# sw.js is a page file, intentionally excluded from UE's data-cache manifests.
# Refuse an unexpected manifest contract instead of leaving stale integrity metadata.
foreach ($listName in @('wasm-manifest.json', 'wasm-cache.json')) {
    $entries = Get-Content -LiteralPath (Join-Path $stage $listName) -Raw | ConvertFrom-Json
    if ($entries | Where-Object { $_.url -match '^(\./)?sw\.js(\.br)?$' }) {
        throw "$listName unexpectedly hashes sw.js; update the finalizer for this engine version."
    }
}
$updated = $text.Substring(0, $matches[0].Index) + $replacement + $text.Substring($matches[0].Index + $matches[0].Length)
$bytes = [Text.UTF8Encoding]::new($false).GetBytes($updated)
$compressed = [IO.MemoryStream]::new()
$brotli = [IO.Compression.BrotliStream]::new($compressed, [IO.Compression.CompressionLevel]::SmallestSize, $true)
try { $brotli.Write($bytes, 0, $bytes.Length) } finally { $brotli.Dispose() }
$packed = $compressed.ToArray()
$compressed.Dispose()
if ($packed.Length -ge $bytes.Length) { throw 'Unexpected Brotli result: worker did not compress.' }
if ($updated -ne $text) { [IO.File]::WriteAllBytes($worker, $bytes) }
[IO.File]::WriteAllBytes($worker + '.br', $packed)
# Confirm that the compressed response is exactly the source that was just finalized.
$inputStream = [IO.MemoryStream]::new($packed, $false)
$decoder = [IO.Compression.BrotliStream]::new($inputStream, [IO.Compression.CompressionMode]::Decompress)
$decoded = [IO.MemoryStream]::new()
try { $decoder.CopyTo($decoded) } finally { $decoder.Dispose(); $inputStream.Dispose() }
if ([Convert]::ToBase64String($decoded.ToArray()) -ne [Convert]::ToBase64String($bytes)) { throw 'Brotli round-trip failed.' }
$decoded.Dispose()
Write-Output "Wasm HUD content types finalized: $worker ($($bytes.Length) bytes; Brotli $($packed.Length) bytes)."
