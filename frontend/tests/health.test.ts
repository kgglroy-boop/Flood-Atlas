import assert from 'node:assert/strict';
import { createServer, type ServerResponse } from 'node:http';
import { after, test } from 'node:test';
import { probeHealth } from '../src/health.ts';

const servers: ReturnType<typeof createServer>[] = [];

async function endpoint(handler: (response: ServerResponse) => void): Promise<string> {
  const server = createServer((request, response) => {
    assert.equal(request.url, '/api/v1/health');
    handler(response);
  });
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  return `http://127.0.0.1:${address.port}/api/v1/health`;
}

after(async () => {
  await Promise.all(servers.map((server) => new Promise<void>((resolve) => {
    server.closeAllConnections();
    server.close(() => resolve());
  })));
});

test('accepts the successful health contract from a real HTTP server', async () => {
  const url = await endpoint((response) => {
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ status: 'ok' }));
  });
  await assert.doesNotReject(probeHealth(url));
});

test('rejects database-unavailable 503', async () => {
  const url = await endpoint((response) => {
    response.writeHead(503);
    response.end('{"detail":"database unavailable"}');
  });
  await assert.rejects(probeHealth(url), /503/);
});

test('rejects an HTML fallback with HTTP 200', async () => {
  const url = await endpoint((response) => response.end('<html>Vite fallback</html>'));
  await assert.rejects(probeHealth(url), SyntaxError);
});

test('rejects a 200 response that does not match the contract', async () => {
  const url = await endpoint((response) => response.end('{"status":"starting"}'));
  await assert.rejects(probeHealth(url), /invalid health response/);
});

test('times out an unresponsive server', async () => {
  const url = await endpoint(() => {});
  await assert.rejects(probeHealth(url, 30), { name: 'TimeoutError' });
});
