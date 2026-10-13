const path = require('node:path');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');

const root = process.env.RESOLVEAI_ROOT || path.resolve(__dirname, '..');
const fs = require('node:fs/promises');
const requireFrontend = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = process.env.PLAYWRIGHT_MODULE
  ? require(process.env.PLAYWRIGHT_MODULE)
  : requireFrontend('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width: 1280, height: 980 }, locale: 'zh-CN' });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  async function api(endpoint) {
    return page.evaluate(async (path) => {
      const response = await fetch('/api/v1' + path, { headers: { Authorization: 'Bearer ' + localStorage.getItem('resolveai_token') } });
      if (!response.ok) throw new Error(`GET ${path} failed: ${response.status}`);
      return response.json();
    }, endpoint);
  }
  try {
    await page.goto(process.env.RESOLVEAI_URL || 'http://127.0.0.1:5174');
    await page.getByLabel('工作邮箱').fill(process.env.RESOLVEAI_EMAIL || 'demo@resolveai.example.com');
    await page.getByLabel('密码', { exact: true }).fill(process.env.RESOLVEAI_PASSWORD || 'ResolveAI123!');
    await page.getByRole('button', { name: '进入工作台' }).click();
    await page.getByRole('heading', { name: '让 IT 问题更快得到响应' }).waitFor();

    const question = `VPN 连不上，提示认证超时，怎么排查？ v1.4 浏览器验收 ${Date.now()}`;
    await page.getByLabel('描述 IT 问题').fill(question);
    await page.getByRole('button', { name: '开始诊断' }).click();
    await page.getByRole('heading', { name: '诊断结果', exact: true }).waitFor({ timeout: 120000 });
    const history = await api('/helpdesk/runs');
    const run = history.find((item) => item.question === question);
    assert(run?.result?.ticket_id, 'The real UI diagnosis did not create its demo ticket.');
    const ticket = await api(`/helpdesk/tickets/${run.result.ticket_id}`);
    const ticketId = run.result.ticket_id;
    assert.equal(ticket.ticket.assigned_agent_id, null, 'The newly created smoke ticket should begin unassigned.');
    const roster = await api('/helpdesk/assignees');
    const target = roster.items[0];
    assert(target, 'No alternate active workspace support member is available.');
    const initialDetail = ticket;

    await page.getByRole('button', { name: /^工单队列/ }).click();
    await page.getByLabel('搜索问题 / 原因 / ID').fill(ticketId.slice(0, 8));
    await page.locator('.ticket-card').first().waitFor();
    const card = page.locator('.ticket-card').filter({ hasText: ticketId.slice(0, 8) }).first();
    await card.locator('.ticket-ops > summary').click();
    await page.getByLabel('搜索工作区支持成员').fill(target.name);
    await page.getByLabel('分派给').selectOption(target.id);
    await page.getByLabel('交接原因').fill('浏览器验收：演示工单临时转交后释放');

    let lostResponse = true;
    let completeFirstRequest;
    const firstRequestCompleted = new Promise((resolve) => { completeFirstRequest = resolve; });
    await page.route('**/api/v1/helpdesk/tickets/*/assignment', async (route) => {
      if (route.request().method() === 'POST' && lostResponse) {
        lostResponse = false;
        const response = await route.fetch();
        assert(response.ok(), `First assignment request failed before response loss: ${response.status()}`);
        await route.abort('failed');
        completeFirstRequest();
      } else {
        await route.continue();
      }
    });
    await page.getByRole('button', { name: '保存交接', exact: true }).click();
    await firstRequestCompleted;
    await page.getByRole('button', { name: '重试原请求', exact: true }).waitFor();
    await page.waitForFunction(() => {
      const button = Array.from(document.querySelectorAll('button')).find((item) => item.textContent.includes('重试原请求'));
      return Boolean(button && !button.disabled);
    });
    let assigned = await api(`/helpdesk/tickets/${ticketId}`);
    assert.equal(assigned.ticket.assigned_agent_id, target.id, 'The first request should persist despite the lost response.');
    const eventId = assigned.events.find((event) => event.type === 'assignment_changed')?.id;
    assert(eventId, 'The assignment event must be persisted with the ticket update.');
    await page.getByRole('button', { name: '重试原请求', exact: true }).click();
    await page.getByText('接手人变更：', { exact: false }).waitFor();
    assigned = await api(`/helpdesk/tickets/${ticketId}`);
    assert.equal(assigned.ticket.status, initialDetail.ticket.status);
    assert.equal(assigned.events.filter((event) => event.type === 'assignment_changed').length, 1, 'Retry must not duplicate the assignment event.');
    assert.equal(assigned.event_count, initialDetail.event_count + 1);
    await page.screenshot({ path: path.join(root, 'docs/resolveai-assignment.png'), fullPage: true });

    await page.getByLabel('搜索工作区支持成员').fill('');
    await page.getByLabel('分派给').selectOption('');
    await page.getByLabel('交接原因').fill('浏览器验收：完成后释放演示工单');
    await page.getByRole('button', { name: '保存交接', exact: true }).click();
    await page.waitForFunction(async (id) => {
      const response = await fetch(`/api/v1/helpdesk/tickets/${id}`, { headers: { Authorization: 'Bearer ' + localStorage.getItem('resolveai_token') } });
      return response.ok && (await response.json()).ticket.assigned_agent_id === null;
    }, ticketId);
    await page.getByText('接手人变更：', { exact: false }).waitFor();
    const released = await api(`/helpdesk/tickets/${ticketId}`);
    assert.equal(released.ticket.assigned_agent_id, null);
    assert.equal(released.ticket.status, initialDetail.ticket.status);
    assert.equal(released.events.filter((event) => event.type === 'assignment_changed').length, 2);
    assert.equal(released.event_count, initialDetail.event_count + 2);
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Assignment detail should fit a 390px viewport.');
    await page.screenshot({ path: path.join(root, 'docs/resolveai-assignment-mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: true, ticket_id: ticketId, target: target.name, checks: ['new real demo ticket via UI diagnosis', 'real UI assignment', 'committed request with simulated lost response', 'same-request retry without duplicate event', 'real UI release', 'status preserved', '390px assignment layout'] }, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
