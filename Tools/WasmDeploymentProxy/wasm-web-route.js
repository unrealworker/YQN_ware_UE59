'use strict';

const http = require('node:http');

const HOP_HEADERS = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade', 'proxy-connection',
]);
const ASSET_REQUEST_HEADERS = new Set([
  'accept', 'accept-encoding', 'accept-language', 'range', 'if-range',
  'if-none-match', 'if-modified-since', 'cache-control', 'pragma',
]);

function connectionHeaders(headers) {
  return new Set(String(headers.connection || '').split(',').map(value => value.trim().toLowerCase()).filter(Boolean));
}

function reply(res, status, message, extraHeaders = {}) {
  const body = Buffer.from(message + '\n');
  res.writeHead(status, {
    'Content-Type': 'text/plain; charset=utf-8',
    'Content-Length': body.length,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    ...extraHeaders,
  });
  res.end(body);
}

/** Only /web and /web/* are handled. All other requests remain with Pixel Streaming. */
function createWasmWebHandler({ upstreamPort = 8800, upstreamTimeoutMs = 300000 } = {}) {
  if (!Number.isInteger(upstreamPort) || upstreamPort < 1 || upstreamPort > 65535) throw new TypeError('Invalid upstream port');
  if (!Number.isFinite(upstreamTimeoutMs) || upstreamTimeoutMs <= 0) throw new TypeError('Invalid upstream timeout');

  return function handleWasmWeb(req, res) {
    // Inspect the raw origin-form path: URL normalization must not erase traversal.
    const target = req.url || '';
    const queryAt = target.indexOf('?');
    const pathname = queryAt < 0 ? target : target.slice(0, queryAt);
    if (pathname !== '/web' && !pathname.startsWith('/web/')) return false;

    if (req.method !== 'GET' && req.method !== 'HEAD') {
      reply(res, 405, 'Only GET and HEAD are supported.', { Allow: 'GET, HEAD' });
      req.resume();
      return true;
    }
    if (pathname === '/web') {
      res.writeHead(308, { Location: '/web/' + (queryAt < 0 ? '' : target.slice(queryAt)), 'Content-Length': 0, 'Cache-Control': 'no-cache' });
      res.end();
      req.resume();
      return true;
    }

    let decoded;
    try { decoded = decodeURIComponent(pathname.slice(4)); }
    catch { reply(res, 400, 'Invalid path.'); req.resume(); return true; }
    if (decoded.includes('\\') || /[\x00-\x1f\x7f]/.test(decoded) || decoded.startsWith('//') ||
        decoded.split('/').some(part => part === '.' || part === '..')) {
      reply(res, 400, 'Invalid path.');
      req.resume();
      return true;
    }

    const excludedRequestHeaders = connectionHeaders(req.headers);
    const headers = { host: '127.0.0.1:' + upstreamPort };
    for (const [name, value] of Object.entries(req.headers)) {
      if (ASSET_REQUEST_HEADERS.has(name) && !excludedRequestHeaders.has(name)) headers[name] = value;
    }

    let upstreamResponse;
    let timedOut = false;
    const upstream = http.request({
      hostname: '127.0.0.1', port: upstreamPort, method: req.method,
      path: target.slice(4), headers, agent: false,
    }, incoming => {
      upstreamResponse = incoming;
      if (res.destroyed) { incoming.destroy(); return; }
      const excluded = connectionHeaders(incoming.headers);
      const responseHeaders = {};
      for (const [name, value] of Object.entries(incoming.headers)) {
        // The upstream is a static site; it must not establish cookies on the shared origin.
        if (!HOP_HEADERS.has(name) && !excluded.has(name) && name !== 'set-cookie') responseHeaders[name] = value;
      }
      res.writeHead(incoming.statusCode || 502, responseHeaders);
      incoming.once('error', () => res.destroy());
      incoming.once('aborted', () => res.destroy());
      incoming.pipe(res);
    });

    const abort = () => { upstreamResponse?.destroy(); upstream.destroy(); };
    req.once('aborted', abort);
    res.once('close', () => { if (!res.writableEnded) abort(); });
    upstream.setTimeout(upstreamTimeoutMs, () => { timedOut = true; upstream.destroy(new Error('Upstream timeout')); });
    upstream.once('error', () => {
      if (res.destroyed) return;
      if (res.headersSent) { res.destroy(); return; }
      reply(res, timedOut ? 504 : 502, 'The warehouse web service is temporarily unavailable.');
    });
    upstream.end();
    // GET/HEAD request bodies are never forwarded to the static server.
    req.resume();
    return true;
  };
}

const handleWasmWeb = createWasmWebHandler();
module.exports = { createWasmWebHandler, handleWasmWeb };
