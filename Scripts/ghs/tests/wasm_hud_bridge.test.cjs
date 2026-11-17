const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {spawnSync} = require('node:child_process');

const source = fs.readFileSync(path.join(__dirname, '../../../Source/Test/SGHSWasmBrowser.cpp'), 'utf8');
const body = source.match(/EM_JS\(void, InstallHud,[\s\S]*?, \{\n([\s\S]*?)\n\}\);/)[1];

test('embedded JavaScript also survives the C++ macro tokenizer', context => {
  const compiler = path.join(__dirname, '../../../Saved/Toolchains/emsdk/upstream/bin/clang++.exe');
  if (!fs.existsSync(compiler)) {context.skip('Local Emscripten clang is not installed'); return;}
  const macros = [...source.matchAll(/EM_JS\(void, (?:InstallHud|ApplyHud),[\s\S]*?\n\}\);/g)].map(match => match[0]);
  const input = '#define EM_JS(ret, name, params, ...) const char* name = #__VA_ARGS__;\n' + macros.join('\n');
  const result = spawnSync(compiler, ['-fsyntax-only', '-x', 'c++', '-Werror', '-'], {input, encoding: 'utf8'});
  assert.equal(result.status, 0, result.stderr || String(result.error || 'compiler failed'));
});

test('wasm64 pointer arguments are converted before Emscripten heap string access', () => {
  const applyBody = source.match(/EM_JS\(void, ApplyHud,[\s\S]*?, \{\n([\s\S]*?)\n\}\);/)[1];
  let received;
  const context = vm.createContext({Payload: 1234n, ghsWasmHUD: {apply: value => {received = value;}},
    UTF8ToString: pointer => {assert.equal(typeof pointer, 'number'); assert.equal(pointer, 1234); return '{"op":"remove","id":1}';}});
  vm.runInContext('(function(){\n' + applyBody + '\n})();', context);
  assert.equal(received.op, 'remove');
});

async function harness() {
  const intervals = [], children = [], requests = [], evaluated = [];
  const buffer = new SharedArrayBuffer(65544);
  const canvas = {getBoundingClientRect: () => ({left: 20, top: 40, width: 960, height: 540})};
  const document = {
    baseURI: 'http://localhost:8900/release/index.html',
    querySelector: () => canvas,
    body: {appendChild: child => children.push(child)},
    createElement(tag) {
      const element = {style: {}, listeners: {}, appendChild(child) {this.child = child;}, setAttribute() {},
        addEventListener(name, callback) {this.listeners[name] = callback;}, remove() {this.removed = true;}};
      if (tag === 'iframe') element.contentWindow = {eval: script => evaluated.push(script)};
      return element;
    }
  };
  const context = vm.createContext({document, URL, Map, Promise, TextEncoder, Atomics, Int32Array, Uint8Array,
    HEAP8: new Int8Array(buffer), BufferOffset: 0, FlagOffset: 65536, Size: 65536,
    setInterval: callback => intervals.push(callback), setTimeout: () => 1, clearTimeout() {}, console,
    fetch: async url => {requests.push(url.href); return {ok: true, text: async () => '<html><head><script src="app.js"></script></head><body></body></html>'};}
  });
  vm.runInContext('(function(){\n' + body + '\n})();', context);
  const api = context.ghsWasmHUD;
  api.apply({op: 'create', id: 1, url: 'Test/Content/GHSTwinUI/web/globe.html'});
  await new Promise(resolve => setImmediate(resolve));
  const frame = children[0].child;
  api.bind(1, frame.contentWindow);
  frame.listeners.load();
  return {api, frame, wrapper: children[0], requests, evaluated, intervals, buffer,
    read() {intervals[0](); return JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 0, 65536)).split('\0')[0]);}};
}

test('same-origin document installs the bridge before existing app scripts', async () => {
  const h = await harness();
  assert.equal(h.requests[0], 'http://localhost:8900/release/Test/Content/GHSTwinUI/web/globe.html');
  assert.match(h.frame.srcdoc, /<head><base href="http:\/\/localhost:8900\/release\/Test\/Content\/GHSTwinUI\/web\/">/);
  assert.ok(h.frame.srcdoc.indexOf('parent.ghsWasmHUD.bind(1,window)') < h.frame.srcdoc.indexOf('src="app.js"'));
});

test('Chinese commands cross the atomic mailbox intact and acknowledge their Promise', async () => {
  const h = await harness();
  const value = JSON.stringify({action: 'select', id: '上海仓库🏭'});
  const promise = h.frame.contentWindow.ue.twin.command(value);
  const messages = h.read();
  assert.equal(messages[0].value, value);
  assert.equal(Atomics.load(new Int32Array(h.buffer, 65536, 1), 0), 1);
  h.api.apply({op: 'reply', id: 1, request: messages[0].request, value: ''});
  assert.equal(await promise, '');
});

test('state getter resolves actual game response and the producer respects an unread mailbox', async () => {
  const h = await harness();
  const first = h.frame.contentWindow.ue.twin.getstate();
  const message = h.read()[0];
  const second = h.frame.contentWindow.ue.twin.getsnapshot();
  assert.equal(h.read()[0].request, message.request);
  h.api.apply({op: 'reply', id: 1, request: message.request, value: '{"phase":"idle"}'});
  assert.equal(await first, '{"phase":"idle"}');
  Atomics.store(new Int32Array(h.buffer, 65536, 1), 0, 0);
  const next = h.read()[0];
  assert.equal(next.method, 'getsnapshot');
  h.api.apply({op: 'reply', id: 1, request: next.request, value: '{}'});
  await second;
});

test('Slate geometry maps through canvas scale with clipping and hidden state', async () => {
  const h = await harness();
  h.api.apply({op: 'layout', id: 1, visible: true, x: 100, y: 200, w: 480, h: 300,
    vw: 1920, vh: 1080, cl: 150, ct: 210, cr: 500, cb: 480, opacity: .75});
  assert.equal(h.wrapper.style.left, '95px'); assert.equal(h.wrapper.style.top, '145px');
  assert.equal(h.wrapper.style.width, '175px'); assert.equal(h.wrapper.style.height, '135px');
  assert.equal(h.frame.style.left, '-25px'); assert.equal(h.frame.style.width, '240px');
  h.api.apply({op: 'layout', id: 1, visible: false});
  assert.equal(h.wrapper.style.display, 'none');
});

test('script dispatch works after loading and teardown rejects pending calls', async () => {
  const h = await harness();
  h.api.apply({op: 'eval', id: 1, script: 'window.ghsGlobe.receive({phase:"idle"})'});
  assert.equal(h.evaluated.length, 1);
  const pending = h.frame.contentWindow.ue.twin.getstate();
  const rejection = assert.rejects(pending, /HUD closed/);
  h.api.apply({op: 'remove', id: 1});
  assert.equal(h.wrapper.removed, true); await rejection;
});
