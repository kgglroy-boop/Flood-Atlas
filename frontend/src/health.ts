export async function probeHealth(url = '/api/v1/health', timeoutMs = 3000): Promise<void> {
  const response = await fetch(url, {
    cache: 'no-store',
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) throw new Error(`health response: ${response.status}`);
  const body: unknown = await response.json();
  if (typeof body !== 'object' || body === null ||
      !('status' in body) || body.status !== 'ok' || Object.keys(body).length !== 1) {
    throw new Error('invalid health response');
  }
}
