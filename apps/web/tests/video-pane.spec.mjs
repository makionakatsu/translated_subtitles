import { test, expect } from '@playwright/test';

// All API traffic uses synthetic data; no backend is required.
test('editor renders its video and keeps working across navigation and reload', async ({ page }) => {
  const errors = [];
  const patches = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const segment = { id: 1, start: 0, end: 1, text: 'Hello subtitle', original_text: null,
    words: [], speaker: null, locked: false, avg_logprob: null, updated_at: '2026-01-01T00:00:00Z' };
  const data = { job_id: 'fixture', source_language: 'en', target_language: 'ja', width: 320, height: 180, segments: [segment] };
  const job = { id: 'fixture', status: 'completed', error: null, last_stage: 'write', last_pct: 100, last_msg: 'done', outputs: {} };
  await page.routeWebSocket('**/*', (socket) => socket.close());
  await page.route('**/*', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (url.origin !== 'http://127.0.0.1:47929') return route.abort();
    if (url.pathname.startsWith('/sse/')) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: end\ndata: {}\n\n' });
    if (url.pathname.startsWith('/ws/')) return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    if (url.pathname.endsWith('/media')) return route.fulfill({ status: 204, body: '' });
    if (url.pathname.endsWith('/ass')) return route.fulfill({ status: 200, contentType: 'text/plain', body: '[Script Info]\nScriptType: v4.00+\n' });
    let body = {};
    if (url.pathname === '/api/jobs') body = [job];
    else if (url.pathname === '/api/jobs/fixture/segments') {
      if (req.method() === 'PATCH') patches.push(req.postDataJSON());
      body = data;
    } else if (url.pathname === '/api/jobs/fixture') body = job;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto('/');
  await page.getByRole('link', { name: 'fixture', exact: true }).click();
  await expect(page.locator('video')).toHaveCount(1);
  await expect(page.locator('video + canvas')).toHaveCount(1);
  const field = page.locator('textarea').first();
  await expect(field).toHaveValue('Hello subtitle');
  await field.fill('Edited subtitle');
  await field.blur();
  const mod = process.platform === 'darwin' ? 'Meta' : 'Control';
  await page.keyboard.press(`${mod}+z`);
  await expect(field).toHaveValue('Hello subtitle');
  await page.keyboard.press(`${mod}+Shift+z`);
  await expect(field).toHaveValue('Edited subtitle');
  await expect.poll(() => patches.some((p) => p.edits?.['1']?.text === 'Edited subtitle')).toBe(true);
  await page.goto('/');
  await expect(page.locator('video')).toHaveCount(0);
  await page.getByRole('link', { name: 'fixture', exact: true }).click();
  await expect(page.locator('video + canvas')).toHaveCount(1);
  await page.reload();
  await expect(page.locator('video')).toHaveCount(1);
  await expect(page.locator('textarea').first()).toHaveValue('Hello subtitle');
  expect(errors).toEqual([]);
});
