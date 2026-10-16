const assert = require('node:assert/strict');
const { randomBytes, randomUUID, createHash } = require('node:crypto');
const { createRequire } = require('node:module');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const { chromium } = process.env.PLAYWRIGHT_MODULE ? require(process.env.PLAYWRIGHT_MODULE) : createRequire(path.join(root, 'frontend/package.json'))('playwright');
const web = process.env.RESOLVEAI_URL || 'http://127.0.0.1:5184';
assert(process.env.RESOLVEAI_ALLOW_SYNTHETIC_WRITES === '1', 'Explicitly allow synthetic fixture writes first.');
assert(['127.0.0.1', 'localhost'].includes(new URL(web).hostname), 'This demonstration smoke check is loopback-only.');
(async () => {
  const suffix = randomBytes(8).toString('hex');
  const password = randomBytes(24).toString('hex') + 'Aa1!';
  const email = `manual-${suffix}@example.com`;
  async function api(route, method = 'GET', body, token) {
    const r = await fetch(web + '/api/v1' + route, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    assert(r.ok, `${method} ${route}: ${r.status}`); return r.json();
  }
  const owner = await api('/auth/register', 'POST', { email, password, full_name: '合成报障人', tenant_name: '主动报障验收', tenant_slug: 'manual-' + suffix });
  const supportEmail = `support-${suffix}@example.com`;
  const invite = await api('/auth/invitations', 'POST', { email: supportEmail }, owner.access_token);
  const support = await api('/auth/invitations/accept', 'POST', { token: invite.token, email: supportEmail, password, full_name: '合成支持人员' });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' });
  const page = await context.newPage(); const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto(web);
    await page.getByLabel('工作邮箱').fill(email);
    await page.getByLabel('密码', { exact: true }).fill(password);
    await page.getByRole('button', { name: '进入工作台' }).click();
    await page.getByRole('button', { name: '我的报障', exact: true }).click();
    await page.getByRole('button', { name: '新建报障', exact: true }).click();
    const subject = '合成电脑无法联网 ' + suffix;
    await page.getByLabel('报障标题', { exact: true }).fill(subject);
    await page.getByLabel('问题类别', { exact: true }).selectOption('network');
    await page.getByLabel('问题描述', { exact: true }).fill('仅用于功能验收的模拟故障，重启后仍无法连接办公网络。');
    let interrupted = false; const ids = [];
    await page.route('**/api/v1/helpdesk/my-tickets', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      ids.push(route.request().postDataJSON().request_id);
      if (!interrupted) { const r = await route.fetch(); assert.equal(r.status(), 201); interrupted = true; await route.abort('failed'); }
      else await route.continue();
    });
    await page.getByRole('button', { name: '提交报障', exact: true }).click();
    await page.getByRole('alert').first().waitFor();
    await page.getByRole('button', { name: /提交报障|重试原提交|重试提交/ }).click();
    await page.getByRole('heading', { name: subject, exact: true }).waitFor();
    assert.equal(ids.length, 2); assert.equal(ids[0], ids[1]);
    const list = await api('/helpdesk/my-tickets', 'GET', undefined, owner.access_token);
    assert.equal(list.total, 1); const id = list.items[0].id;
    const mine = '/helpdesk/my-tickets/' + id, ops = '/helpdesk/tickets/' + id;
    assert.equal((await api('/helpdesk/runs', 'GET', undefined, owner.access_token)).length, 0);
    const bytes = Buffer.from('Synthetic manual ticket attachment. No real accounts or system logs.');
    await page.getByLabel('选择附件', { exact: true }).setInputFiles({ name: 'manual-demo.txt', mimeType: 'text/plain', buffer: bytes });
    await page.getByRole('button', { name: '上传附件', exact: true }).click();
    await page.getByText('附件已上传。', { exact: true }).waitFor();
    const attachments = await api(mine + '/attachments', 'GET', undefined, owner.access_token);
    assert.equal(attachments.items.length, 1);
    const blob = await fetch(web + '/api/v1' + mine + '/attachments/' + attachments.items[0].id + '/download', { headers: { Authorization: 'Bearer ' + owner.access_token } });
    assert(blob.ok); assert.equal(createHash('sha256').update(Buffer.from(await blob.arrayBuffer())).digest('hex'), createHash('sha256').update(bytes).digest('hex'));
    const ticket = async () => (await api(ops, 'GET', undefined, support.access_token)).ticket;
    await api(ops + '/claim', 'POST', { expected_updated_at: (await ticket()).updated_at }, support.access_token);
    await api(ops + '/replies', 'POST', { request_id: randomUUID(), expected_updated_at: (await ticket()).updated_at, body: '模拟处理：已检查网络配置，请确认恢复。' }, support.access_token);
    const solved = await api(ops + '/resolve', 'POST', { request_id: randomUUID(), expected_updated_at: (await ticket()).updated_at, category: 'configuration', summary: '模拟网络配置已恢复。', steps: '检查模拟网络配置并确认连接。' }, support.access_token);
    assert(solved.resolution.id);
    const notices = await api('/helpdesk/notifications', 'GET', undefined, owner.access_token);
    assert(notices.items.some(n => n.ticket_id === id && n.kind === 'support_reply'));
    await page.getByRole('button', { name: '刷新进度', exact: true }).click();
    await page.getByText('模拟处理：已检查网络配置，请确认恢复。', { exact: true }).waitFor();
    await page.getByRole('button', { name: '确认解决并关闭', exact: true }).click();
    await page.getByLabel('本轮满意度').selectOption('5');
    await Promise.all([page.waitForResponse(r => r.url().endsWith(mine + '/satisfaction') && r.status() === 201), page.getByRole('button', { name: '提交本轮评价', exact: true }).click()]);
    await page.reload(); await page.getByRole('button', { name: '我的报障', exact: true }).click();
    await page.getByRole('heading', { name: subject, exact: true }).waitFor();
    const result = await api(mine + '/resolution', 'GET', undefined, owner.access_token);
    assert.equal(result.satisfaction.rating, 5); assert.equal((await api(mine, 'GET', undefined, owner.access_token)).ticket.status, 'CLOSED');
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: true, synthetic_tenant: true, interrupted_response_retry_same_id: true, ticket_count: 1, attachment_sha256_match: true, support_reply_notification: true, confirmed_closed_rating: 5, reload_persisted: true, mobile_width: 390, page_errors: 0 }));
  } catch (error) {
    const state = await api('/helpdesk/my-tickets', 'GET', undefined, owner.access_token);
    const latest = state.items[0];
    const resolution = latest ? await api('/helpdesk/my-tickets/' + latest.id + '/resolution', 'GET', undefined, owner.access_token) : null;
    console.error(JSON.stringify({ alerts: await page.getByRole('alert').allTextContents(), status: latest?.status, resolution_current: resolution?.current, satisfaction_present: !!resolution?.satisfaction, browser_resolution_sections: await page.locator('.ticket-resolution').allTextContents() }));
    throw error;
  } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
