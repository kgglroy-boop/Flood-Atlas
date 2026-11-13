// Run in a disposable frontend container; never stop the project's backend.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';

const marker = `PHASE5_PROXY_${crypto.randomUUID()}`;
const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5180', '--strictPort'], {
  cwd: '/app', env: { ...process.env, API_PROXY_TARGET: 'http://127.0.0.1:1', NO_COLOR: '1' },
  stdio: ['ignore', 'pipe', 'pipe'],
});
let output = '';
child.stdout.on('data', data => { output += data.toString(); });
child.stderr.on('data', data => { output += data.toString(); });
const closed = new Promise(resolve => child.once('close', resolve));
try {
  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error('Isolated Vite exited before readiness.');
    try {
      const response = await fetch('http://127.0.0.1:5180/', { signal: AbortSignal.timeout(500) });
      if (response.ok) { ready = true; break; }
    } catch { /* startup only; no diagnostic payload is printed */ }
    await delay(100);
  }
  assert.ok(ready, 'Isolated Vite did not become ready.');
  const response = await fetch(`http://127.0.0.1:5180/api/v1/analysis/summary?step_id=${marker}%3BSELECT%201`, { signal: AbortSignal.timeout(3000) });
  assert.equal(response.status, 502, 'Actual upstream failure must remain an HTTP failure.');
  const body = await response.text();
  await delay(200);
  assert.ok(!output.includes(marker), 'Raw analysis query leaked into Vite proxy error logs.');
  assert.ok(!body.includes(marker), 'Raw analysis query leaked into proxy response.');
  assert.ok(output.includes('API proxy unavailable'), 'Sanitized proxy diagnostic was lost.');
  console.log('PASS: isolated real Vite upstream failure is502 with sanitized logs');
} finally {
  child.kill('SIGTERM');
  await closed;
}
