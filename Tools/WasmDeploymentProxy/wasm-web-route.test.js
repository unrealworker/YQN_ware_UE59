'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const { once } = require('node:events');
const { test } = require('node:test');
const { createWasmWebHandler } = require('./wasm-web-route');

async function listen(server) { server.listen(0, '127.0.0.1'); await once(server, 'listening'); return server.address().port; }
async function close(server) { if (!server.listening) return; const done = once(server, 'close'); server.close(); server.closeAllConnections(); await done; }
function request(port, path, { method = 'GET', headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, path, method, headers, agent: false }, res => {
      const chunks = []; res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
      res.on('error', reject);
    });
    req.on('error', reject); req.end();
  });
}
async function fixture(t, upstreamHandler, handlerOptions = {}) {
  const upstream = http.createServer(upstreamHandler);
  const upstreamPort = await listen(upstream);
  const handler = createWasmWebHandler({ upstreamPort, ...handlerOptions });
  const server = http.createServer((req, res) => {
    if (handler(req, res)) return;
    res.writeHead(200, { 'Content-Type': 'text/plain' }); res.end('legacy:' + req.url);
  });
  const port = await listen(server);
  t.after(async () => { await close(server); await close(upstream); });
  return { port, upstream, upstreamPort };
}

test('legacy routes stay unchanged and /web redirects with its query', async t => {
  let upstreamRequests = 0;
  const { port } = await fixture(t, (_req, res) => { upstreamRequests++; res.end('asset'); });
  for (const route of ['/', '/health', '/api/session', '/ws', '/web-other', '/website']) {
    const result = await request(port, route);
    assert.equal(result.body.toString(), 'legacy:' + route);
  }
  const redirect = await request(port, '/web?tier=forward');
  assert.equal(redirect.status, 308); assert.equal(redirect.headers.location, '/web/?tier=forward');
  assert.equal(upstreamRequests, 0);
  const index = await request(port, '/web/');
  assert.equal(index.body.toString(), 'asset');
});

test('strips prefix, preserves Range/Brotli/isolation, and removes sensitive and connection headers', async t => {
  let received;
  const data = Buffer.from([0, 97, 115, 109]);
  const { port, upstreamPort } = await fixture(t, (req, res) => {
    received = { url: req.url, headers: req.headers };
    res.writeHead(206, {
      'Content-Type': 'application/wasm', 'Content-Length': data.length,
      'Content-Range': 'bytes 0-3/100', 'Accept-Ranges': 'bytes', 'Content-Encoding': 'br',
      'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp',
      'Cross-Origin-Resource-Policy': 'same-origin', 'Cache-Control': 'no-cache',
      'Set-Cookie': 'upstream-only=1', Connection: 'x-private, close', 'X-Private': 'remove-me',
    });
    res.end(data);
  });
  const result = await request(port, '/web/Test/game.wasm?key=value', {
    headers: { Host: 'warehouse-sim.iyunquna.com', Range: 'bytes=0-3', 'Accept-Encoding': 'br',
      Cookie: 'shared-site-session=secret', Authorization: 'Bearer secret',
      'Proxy-Authorization': 'Basic secret', Connection: 'cache-control, close', 'Cache-Control': 'no-cache' },
  });
  assert.equal(received.url, '/Test/game.wasm?key=value');
  assert.equal(received.headers.host, '127.0.0.1:' + upstreamPort);
  assert.equal(received.headers.range, 'bytes=0-3'); assert.equal(received.headers['accept-encoding'], 'br');
  for (const header of ['cookie', 'authorization', 'proxy-authorization', 'cache-control']) assert.equal(received.headers[header], undefined);
  assert.equal(result.status, 206); assert.deepEqual(result.body, data);
  assert.equal(result.headers['content-type'], 'application/wasm');
  assert.equal(result.headers['content-range'], 'bytes 0-3/100'); assert.equal(result.headers['content-encoding'], 'br');
  assert.equal(result.headers['cross-origin-opener-policy'], 'same-origin');
  assert.equal(result.headers['cross-origin-embedder-policy'], 'require-corp');
  assert.equal(result.headers['cross-origin-resource-policy'], 'same-origin');
  assert.equal(result.headers['cache-control'], 'no-cache');
  for (const header of ['set-cookie', 'x-private']) assert.equal(result.headers[header], undefined);
});

test('HEAD and upstream status are preserved', async t => {
  const { port } = await fixture(t, (req, res) => {
    if (req.url === '/missing') { res.writeHead(404, { 'Content-Type': 'text/plain' }); res.end('missing'); return; }
    assert.equal(req.method, 'HEAD'); res.writeHead(200, { 'Content-Type': 'text/css', 'Content-Length': 123 }); res.end();
  });
  const head = await request(port, '/web/style.css', { method: 'HEAD' });
  assert.equal(head.status, 200); assert.equal(head.headers['content-length'], '123'); assert.equal(head.body.length, 0);
  const missing = await request(port, '/web/missing');
  assert.equal(missing.status, 404); assert.equal(missing.body.toString(), 'missing');
});

test('write methods and unsafe paths never reach the upstream', async t => {
  let reached = false;
  const { port } = await fixture(t, (_req, res) => { reached = true; res.end(); });
  for (const method of ['POST', 'PUT', 'DELETE']) {
    const result = await request(port, '/web/file', { method });
    assert.equal(result.status, 405); assert.equal(result.headers.allow, 'GET, HEAD');
  }
  for (const route of ['/web/../private', '/web/%2e%2e/private', '/web/./private', '/web/%5cprivate', '/web/%00file', '/web/%zz', '/web//example.com/file']) {
    assert.equal((await request(port, route)).status, 400, route);
  }
  assert.equal(reached, false);
});

test('unavailable and stalled upstreams return controlled errors', async t => {
  const gone = await fixture(t, (_req, res) => res.end());
  await close(gone.upstream);
  assert.equal((await request(gone.port, '/web/')).status, 502);
  const stalled = await fixture(t, () => {}, { upstreamTimeoutMs: 40 });
  assert.equal((await request(stalled.port, '/web/')).status, 504);
});

test('a disconnected client cancels its upstream download', async t => {
  let finishAbort;
  const aborted = new Promise(resolve => { finishAbort = resolve; });
  const { port } = await fixture(t, (_req, res) => {
    const timer = setInterval(() => res.write(Buffer.alloc(1024)), 5);
    res.on('close', () => { clearInterval(timer); finishAbort(); });
  });
  await new Promise((resolve, reject) => {
    const req = http.get({ hostname: '127.0.0.1', port, path: '/web/large', agent: false }, res => {
      res.once('data', () => { res.destroy(); req.destroy(); resolve(); });
    });
    req.on('error', reject);
  });
  await Promise.race([aborted, new Promise((_, reject) => { const timer = setTimeout(() => reject(Error('Upstream kept downloading')), 1000); timer.unref(); })]);
});
