const assert = require('node:assert/strict');
const { randomBytes, randomUUID } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const { chromium } = process.env.PLAYWRIGHT_MODULE ? require(process.env.PLAYWRIGHT_MODULE) : createRequire(path.join(root, 'frontend/package.json'))('playwright');
const web = process.env.RESOLVEAI_URL || 'http://127.0.0.1:5184';
assert(process.env.RESOLVEAI_ALLOW_SYNTHETIC_WRITES === '1', 'Explicitly allow synthetic fixture writes first.');
assert(['127.0.0.1', 'localhost'].includes(new URL(web).hostname), 'This smoke check is loopback-only.');
(async () => {
  const suffix = randomBytes(8).toString('hex'), password = randomBytes(24).toString('hex') + 'Aa1!';
  const email = `filters-${suffix}@example.com`;
  async function api(route, method = 'GET', body, token) {
    const r = await fetch(web + '/api/v1' + route, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    assert(r.ok, `${method} ${route}: ${r.status}`); return r.json();
  }
  const owner = await api('/auth/register', 'POST', { email, password, full_name: '合成检索用户', tenant_name: '来源筛选验收', tenant_slug: 'filters-' + suffix });
  const token = owner.access_token;
  for (let i = 0; i < 21; i++) await api('/helpdesk/my-tickets', 'POST', { request_id: randomUUID(), subject: '筛选演示 ' + String(i).padStart(2, '0') + (i === 0 ? ' 100%_回归' : ''), category: 'network', description: i === 0 ? '正文专属针叶：这是一条合成网络报障，重试后仍失败。' : '仅用于合成验收的网络问题，重试后仍无法连接测试服务。' }, token);
  await api('/helpdesk/runs', 'POST', { request_id: randomUUID(), question: 'VPN认证失败，需要人工处理来源演示。' }, token);
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, locale: 'zh-CN', acceptDownloads: true });
  const page = await context.newPage(), errors = []; page.on('pageerror', e => errors.push(e.message));
  const count = async n => page.waitForFunction(n => document.querySelectorAll('.my-requests-list .request-item').length === n, n);
  try {
    await page.goto(web); await page.getByLabel('工作邮箱').fill(email); await page.getByLabel('密码', { exact: true }).fill(password); await page.getByRole('button', { name: '进入工作台' }).click();
    await page.getByRole('button', { name: '我的报障', exact: true }).click();
    await page.getByLabel('报障来源筛选').selectOption('manual'); await count(20);
    await page.locator('.request-pagination').getByRole('button', { name: '下一页', exact: true }).click(); await count(1);
    await Promise.all([page.waitForResponse(r => { const u = new URL(r.url()); return u.pathname.endsWith('/my-tickets') && u.searchParams.get('q') === '正文专属针叶'; }), page.getByLabel('搜索我的报障').fill('正文专属针叶')]); await page.locator('.request-item', { hasText: '100%_回归' }).waitFor(); await count(1);
    await page.getByLabel('报障状态筛选').selectOption('ESCALATED'); await count(0);
    await page.getByRole('button', { name: '清除报障筛选', exact: true }).click(); await count(20);
    await page.getByLabel('报障来源筛选').selectOption('ai'); await count(1);
    await page.getByRole('button', { name: '新建报障', exact: true }).click(); await page.getByLabel('报障标题', { exact: true }).fill('尚未提交的草稿');
    await page.getByLabel('报障来源筛选').selectOption('manual'); await count(20); assert.equal(await page.getByLabel('报障标题', { exact: true }).inputValue(), '尚未提交的草稿');
    let release, signal; const gate = new Promise(r => { release = r; }), held = new Promise(r => { signal = r; }); let heldOnce = false;
    await page.route('**/api/v1/helpdesk/my-tickets**', async route => {
      const u = new URL(route.request().url());
      if (!heldOnce && route.request().method() === 'GET' && u.pathname.endsWith('/my-tickets') && u.searchParams.get('q') === '筛选演示') { heldOnce = true; const response = await route.fetch(); signal(); await gate; await route.fulfill({ response }); }
      else await route.continue();
    });
    await page.getByLabel('搜索我的报障').fill('筛选演示'); await held;
    await page.getByLabel('搜索我的报障').fill('%_'); await count(1);
    const delivered = page.waitForResponse(r => { const u = new URL(r.url()); return u.pathname.endsWith('/my-tickets') && u.searchParams.get('q') === '筛选演示'; });
    release(); await delivered; await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    assert.equal(await page.locator('.my-requests-list .request-item').count(), 1);
    await page.getByLabel('搜索我的报障').fill('%_ '); await count(1);
    await page.getByLabel('搜索我的报障').fill('%_x'); await page.getByLabel('搜索我的报障').fill('%_'); await count(1);
    await page.getByLabel('搜索我的报障').fill('没有匹配的查询'); await count(0);
    const newSubject = '创建后清除筛选 ' + suffix;
    await page.getByLabel('报障标题', { exact: true }).fill(newSubject); await page.getByLabel('问题描述', { exact: true }).fill('这是提交后应自动显示的新报障，用于验证筛选条件会清除。');
    await page.getByRole('button', { name: '提交报障', exact: true }).click(); await page.getByRole('heading', { name: newSubject, exact: true }).waitFor();
    assert.equal(await page.getByLabel('搜索我的报障').inputValue(), '');
    await page.getByRole('button', { name: /^工单队列/ }).click(); await page.getByLabel('工单来源筛选').selectOption('manual');
    const views = page.getByRole('region', { name: '个人筛选视图', exact: true }); await views.getByLabel('视图名称').fill('主动报障待处理');
    await views.getByRole('button', { name: '保存为新视图', exact: true }).click(); await views.getByText('个人筛选视图已保存。', { exact: true }).waitFor();
    const saved = (await api('/helpdesk/queue-views', 'GET', undefined, token)).items[0]; assert.equal(saved.filters.source, 'manual');
    await page.reload(); await page.getByRole('button', { name: /^工单队列/ }).click(); await views.locator('#saved-view-select').selectOption(saved.id); await views.getByRole('button', { name: '应用视图', exact: true }).click();
    assert.equal(await page.getByLabel('工单来源筛选').inputValue(), 'manual');
    const downloaded = page.waitForEvent('download'); await page.getByRole('button', { name: '导出筛选结果', exact: true }).click(); const download = await downloaded;
    const csv = readFileSync(await download.path(), 'utf8'); assert(csv.includes('来源')); assert(!csv.includes('VPN认证失败')); assert.equal(csv.split('\r\n').length, 23);
    await page.setViewportSize({ width: 390, height: 844 }); assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.getByRole('button', { name: '我的报障', exact: true }).click(); await page.getByLabel('搜索我的报障').waitFor(); assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: true, matching_pagination: true, personal_body_search: true, literal_wildcards: true, stale_response_ignored: true, draft_preserved: true, new_ticket_clears_filters: true, source_view_reload: true, exported_manual_rows: 22, mobile_width: 390, page_errors: 0 }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
