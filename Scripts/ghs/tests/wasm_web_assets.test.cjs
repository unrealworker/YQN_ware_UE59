const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const zlib = require('node:zlib');
const {spawnSync} = require('node:child_process');
const script = path.join(__dirname, '../finalize_wasm_web_assets.ps1');
const original = `function typeOf(url) {
  if (url.endsWith('.wasm')) return 'application/wasm';
  if (url.endsWith('.js')) return 'text/javascript';
  return 'application/octet-stream';
}`;

function stage(callback) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ghs-wasm-mime-'));
  try {
    fs.writeFileSync(path.join(directory, 'sw.js'), original);
    for (const name of ['wasm-manifest.json', 'wasm-cache.json']) fs.writeFileSync(path.join(directory, name), '[]');
    callback(directory, () => spawnSync('pwsh', ['-NoProfile', '-File', script, '-StageDirectory', directory], {encoding: 'utf8'}));
  } finally {
    // This fixture owns these four files only; never recursively delete a computed directory.
    for (const name of ['sw.js', 'sw.js.br', 'wasm-manifest.json', 'wasm-cache.json']) {
      const file = path.join(directory, name); if (fs.existsSync(file)) fs.unlinkSync(file);
    }
    fs.rmdirSync(directory);
  }
}

test('finalized cached HUD resources keep browser MIME types and lossless Brotli', () => stage((directory, run) => {
  const result = run(); assert.equal(result.status, 0, result.stderr);
  const bytes = fs.readFileSync(path.join(directory, 'sw.js'));
  assert.deepEqual(zlib.brotliDecompressSync(fs.readFileSync(path.join(directory, 'sw.js.br'))), bytes);
  const context = vm.createContext({}); vm.runInContext(bytes.toString(), context);
  for (const [url, mime] of [
    ['Test/Content/GHSTwinUI/web/globe.css', 'text/css; charset=utf-8'],
    ['Test/Content/GHSTwinUI/web/globe.html', 'text/html; charset=utf-8'],
    ['assets/DroidSansFallback.ttf', 'font/ttf'], ['image.webp', 'image/webp'],
    ['state.JSON?v=one#anchor', 'application/json'], ['data.ucas', 'application/octet-stream'],
    ['game.wasm', 'application/wasm'], ['app.js', 'text/javascript']
  ]) assert.equal(context.typeOf(url), mime);
  const second = run(); assert.equal(second.status, 0, second.stderr);
  assert.deepEqual(fs.readFileSync(path.join(directory, 'sw.js')), bytes, 'repeated packaging is byte-for-byte stable');
}));

test('unknown future engine worker implementation is refused without mutation', () => stage((directory, run) => {
  const changed = original.replace("return 'application/octet-stream';", "return 'application/custom-future';");
  fs.writeFileSync(path.join(directory, 'sw.js'), changed);
  const result = run(); assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Unrecognized typeOf/);
  assert.equal(fs.readFileSync(path.join(directory, 'sw.js'), 'utf8'), changed);
  assert.equal(fs.existsSync(path.join(directory, 'sw.js.br')), false);
}));
