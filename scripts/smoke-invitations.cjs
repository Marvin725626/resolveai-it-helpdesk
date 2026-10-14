const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const path = require('node:path');
const { createRequire } = require('node:module');

const root = process.env.RESOLVEAI_ROOT || path.resolve(__dirname, '..');
const requireFrontend = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = process.env.PLAYWRIGHT_MODULE
  ? require(process.env.PLAYWRIGHT_MODULE)
  : requireFrontend('playwright');
const webUrl = process.env.RESOLVEAI_URL || 'http://127.0.0.1:5175';
const apiUrl = process.env.RESOLVEAI_API_URL || 'http://127.0.0.1:8105/api/v1';

(async () => {
  const suffix = Date.now().toString(36);
  const ownerPassword = randomBytes(12).toString('hex') + 'Aa1!';
  const agentPassword = randomBytes(12).toString('hex') + 'Aa1!';
  const email = `agent-${suffix}@example.com`;
  const fullName = `Smoke Agent ${suffix}`;
  const register = await fetch(`${apiUrl}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: `owner-${suffix}@example.com`,
      password: ownerPassword,
      full_name: `Smoke Owner ${suffix}`,
      tenant_name: `Invitation Smoke ${suffix}`,
      tenant_slug: `invite-smoke-${suffix}`,
    }),
  });
  assert.equal(register.status, 201, await register.text());

  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const ownerContext = await browser.newContext({ viewport: { width: 1440, height: 1050 }, locale: 'zh-CN' });
  const ownerPage = await ownerContext.newPage();
  const errors = [];
  ownerPage.on('pageerror', (error) => errors.push(error.message));
  try {
    await ownerPage.goto(webUrl);
    await ownerPage.getByLabel('工作邮箱').fill(`owner-${suffix}@example.com`);
    await ownerPage.getByLabel('密码', { exact: true }).fill(ownerPassword);
    await ownerPage.getByRole('button', { name: '进入工作台' }).click();
    await ownerPage.getByRole('button', { name: '团队管理' }).waitFor();
    await ownerPage.getByRole('button', { name: '团队管理' }).click();
    await ownerPage.getByRole('heading', { name: '邀请支持专员' }).waitFor();
    await ownerPage.locator('#invite-email').fill(email);
    await ownerPage.getByRole('button', { name: '创建邀请' }).click();
    const linkInput = ownerPage.getByLabel('新邀请链接（仅此时显示）');
    await linkInput.waitFor();
    const inviteUrl = await linkInput.inputValue();
    const token = new URL(inviteUrl).hash.slice(1);
    assert(token.length >= 32, 'Invitation token is missing from the URL fragment.');
    assert.equal(new URL(inviteUrl).search, '', 'Token must not be in the query string.');

    const inviteContext = await browser.newContext({ viewport: { width: 1280, height: 980 }, locale: 'zh-CN' });
    const invitePage = await inviteContext.newPage();
    const requestUrls = [];
    invitePage.on('request', (request) => requestUrls.push(request.url()));
    invitePage.on('pageerror', (error) => errors.push(error.message));
    await invitePage.goto(inviteUrl);
    await invitePage.getByRole('heading', { name: '创建你的账号' }).waitFor();
    assert.equal(new URL(invitePage.url()).hash, '', 'Invite page must scrub the token fragment.');
    assert(requestUrls.every((url) => !url.includes(token)), 'Token must not be sent in a request URL.');
    await invitePage.getByLabel('受邀邮箱').fill(email);
    await invitePage.getByLabel('显示姓名').fill(fullName);
    await invitePage.getByLabel('设置密码').fill(agentPassword);
    await invitePage.getByRole('button', { name: '接受邀请并进入工作台' }).click();
    await invitePage.getByRole('heading', { name: '让 IT 问题更快得到响应' }).waitFor();
    const memberToken = await invitePage.evaluate(() => localStorage.getItem('resolveai_token'));
    const member = await invitePage.evaluate(async (bearer) => {
      const response = await fetch('/api/v1/auth/me', { headers: { Authorization: `Bearer ${bearer}` } });
      if (!response.ok) throw new Error(`Member identity endpoint returned ${response.status}`);
      return response.json();
    }, memberToken);
    assert.equal(member.role, 'SUPPORT_AGENT');
    assert.equal(member.email, email);

    await ownerPage.getByRole('button', { name: '刷新成员' }).click();
    await ownerPage.getByRole('cell', { name: fullName }).waitFor();
    const ownerToken = await ownerPage.evaluate(() => localStorage.getItem('resolveai_token'));
    const roster = await ownerPage.evaluate(async (bearer) => {
      const response = await fetch('/api/v1/helpdesk/assignees', { headers: { Authorization: `Bearer ${bearer}` } });
      if (!response.ok) throw new Error(`Assignee endpoint returned ${response.status}`);
      return response.json();
    }, ownerToken);
    assert(roster.items.some((item) => item.name === fullName), 'Accepted member must appear as an assignable agent.');
    assert.deepEqual(errors, [], 'Browser encountered uncaught page errors.');

    if (process.env.RESOLVEAI_SCREENSHOT) {
      // The owner's page still holds the one-time link in component state;
      // never include a bearer credential in a committed screenshot.
      await ownerPage.locator('.invite-link-box').evaluate((element) => element.remove());
      await ownerPage.screenshot({ path: process.env.RESOLVEAI_SCREENSHOT, fullPage: true });
    }
    await ownerPage.setViewportSize({ width: 390, height: 844 });
    const mobileWidth = await ownerPage.evaluate(() => document.documentElement.scrollWidth);
    assert(mobileWidth <= 390, `Team page overflows the mobile viewport (${mobileWidth}px).`);
    if (process.env.RESOLVEAI_MOBILE_SCREENSHOT) {
      await ownerPage.screenshot({ path: process.env.RESOLVEAI_MOBILE_SCREENSHOT, fullPage: true });
    }
    console.log(JSON.stringify({ result: 'passed', role: 'SUPPORT_AGENT', assigned_member_visible: true }));
    await inviteContext.close();
  } finally {
    await ownerContext.close();
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
