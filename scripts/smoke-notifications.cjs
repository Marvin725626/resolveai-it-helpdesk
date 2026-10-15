const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { createRequire } = require('node:module');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const requireFrontend = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = process.env.PLAYWRIGHT_MODULE ? require(process.env.PLAYWRIGHT_MODULE) : requireFrontend('playwright');
const webUrl = process.env.RESOLVEAI_URL || 'http://127.0.0.1:5185';
const apiUrl = process.env.RESOLVEAI_API_URL || 'http://127.0.0.1:8115/api/v1';
(async () => {
  const suffix = Date.now().toString(36);
  const password = randomBytes(16).toString('hex') + 'Aa1!';
  const ownerEmail = `notice-owner-${suffix}@example.com`;
  const agentEmail = `notice-agent-${suffix}@example.com`;
  async function api(route, method = 'GET', body, token) {
    const response = await fetch(apiUrl + route, {method, headers: {'Content-Type':'application/json', ...(token ? {Authorization: 'Bearer ' + token} : {})}, ...(body ? {body:JSON.stringify(body)} : {})});
    assert(response.ok, `${method} ${route}: ${response.status}`);
    return response.json();
  }
  const owner = await api('/auth/register','POST',{email:ownerEmail,password,full_name:'演示管理员',tenant_name:'通知闭环演示',tenant_slug:'notice-'+suffix});
  const invite = await api('/auth/invitations','POST',{email:agentEmail},owner.access_token);
  const agent = await api('/auth/invitations/accept','POST',{token:invite.token,email:agentEmail,password,full_name:'演示支持专员'});
  const run = await api('/helpdesk/runs','POST',{request_id:crypto.randomUUID(),question:'VPN 认证超时，请转人工处理'},owner.access_token);
  assert(run.ticket_id);
  const browser = await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || undefined});
  const errors=[];
  const ownerContext = await browser.newContext({viewport:{width:1440,height:1050},locale:'zh-CN'});
  const agentContext = await browser.newContext({viewport:{width:1440,height:1050},locale:'zh-CN'});
  const ownerPage=await ownerContext.newPage();const agentPage=await agentContext.newPage();
  for(const page of [ownerPage,agentPage]) page.on('pageerror',error=>errors.push(error.message));
  async function login(page,email){ await page.goto(webUrl);await page.getByLabel('工作邮箱').fill(email);await page.getByLabel('密码',{exact:true}).fill(password);await page.getByRole('button',{name:'进入工作台'}).click();await page.getByRole('button',{name:'工单队列'}).waitFor(); }
  try {
    await login(ownerPage,ownerEmail);
    await ownerPage.getByRole('button',{name:'工单队列'}).click();
    const card=ownerPage.locator('.ticket-card').filter({hasText:run.ticket_id.slice(0,8)});
    await card.locator('summary').first().click();
    await card.locator(`#assignee-${run.ticket_id}`).selectOption(agent.user.id);
    await card.getByLabel('交接原因').fill('请跟进本次 VPN 工单');
    await card.getByRole('button',{name:'保存交接'}).click();
    await card.getByText('接手人变更：未分派 → 演示支持专员',{exact:true}).waitFor();
    await login(agentPage,agentEmail);
    await agentPage.getByRole('button',{name:/个人通知/}).click();
    await agentPage.getByRole('heading',{name:/我的通知/}).waitFor();
    await agentPage.locator('.notification-item.unread').waitFor();
    assert.equal(await agentPage.locator('.notification-item').count(),1);
    await agentPage.screenshot({path:process.env.RESOLVEAI_SCREENSHOT || path.join(root,'docs/resolveai-notifications.png'),fullPage:true});
    await agentPage.getByRole('button',{name:'打开工单',exact:true}).click();
    const focused=agentPage.getByRole('article',{name:'通知关联工单'});
    await focused.getByRole('button',{name:'接手处理',exact:true}).waitFor();
    await focused.getByRole('button',{name:'接手处理',exact:true}).click();
    await focused.getByRole('button',{name:'标记解决',exact:true}).waitFor();
    assert(await focused.locator('details.ticket-ops').evaluate(el=>el.open));
    assert.equal(await agentPage.locator(`#note-${run.ticket_id}`).count(),1);
    assert.equal((await api('/helpdesk/notifications', 'GET', undefined, agent.access_token)).unread_count,0);
    const fresh=await api(`/helpdesk/tickets/${run.ticket_id}`,'GET',undefined,agent.access_token);
    assert.equal(fresh.ticket.status,'IN_PROGRESS');
    await agentPage.getByRole('button',{name:/个人通知/}).click();
    await agentPage.getByText('已读',{exact:true}).waitFor();
    await agentPage.setViewportSize({width:390,height:844});
    assert(await agentPage.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,workflow:'manager assignment → recipient inbox → open exact ticket → mark read → recipient changes status',mobile_width:390,page_errors:errors.length,ticket_id:run.ticket_id}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
