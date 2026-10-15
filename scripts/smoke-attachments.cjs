const assert = require('node:assert/strict');
const { randomBytes, createHash } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const requireFrontend = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = process.env.PLAYWRIGHT_MODULE ? require(process.env.PLAYWRIGHT_MODULE) : requireFrontend('playwright');
const webUrl = process.env.RESOLVEAI_URL || 'http://127.0.0.1:5298';
const apiUrl = process.env.RESOLVEAI_API_URL || 'http://127.0.0.1:8198/api/v1';
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==','base64');
const log = Buffer.from('support diagnostic fixture: service reachable\n');
const hash = body => createHash('sha256').update(body).digest('hex');
(async () => {
  const suffix = Date.now().toString(36);
  const password = randomBytes(16).toString('hex') + 'Aa1!';
  const ownerEmail = `attachment-owner-${suffix}@example.com`;
  const supportEmail = `attachment-support-${suffix}@example.com`;
  async function api(route, method = 'GET', body, token) {
    const response = await fetch(apiUrl + route, {method, headers: {'Content-Type':'application/json', ...(token ? {Authorization: 'Bearer ' + token} : {})}, ...(body ? {body:JSON.stringify(body)} : {})});
    assert(response.ok, `${method} ${route}: ${response.status}`); return response.json();
  }
  const owner = await api('/auth/register','POST',{email:ownerEmail,password,full_name:'演示报障人',tenant_name:'私有附件演示',tenant_slug:'attachment-'+suffix});
  const invite = await api('/auth/invitations','POST',{email:supportEmail},owner.access_token);
  const support = await api('/auth/invitations/accept','POST',{token:invite.token,email:supportEmail,password,full_name:'演示支持专员'});
  const run = await api('/helpdesk/runs','POST',{request_id:crypto.randomUUID(),question:'VPN 认证超时，请转人工处理'},owner.access_token);
  const ticketId=run.ticket_id; assert(ticketId);
  const detail=await api(`/helpdesk/tickets/${ticketId}`,'GET',undefined,owner.access_token);
  await api(`/helpdesk/tickets/${ticketId}/assignment`,'POST',{request_id:crypto.randomUUID(),agent_id:support.user.id,reason:'请检查截图与日志',expected_updated_at:detail.ticket.updated_at},owner.access_token);
  const browser = await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || undefined});
  const requesterContext = await browser.newContext({viewport:{width:1440,height:1100},locale:'zh-CN',acceptDownloads:true});
  const supportContext = await browser.newContext({viewport:{width:1440,height:1100},locale:'zh-CN',acceptDownloads:true});
  const requesterPage=await requesterContext.newPage(), supportPage=await supportContext.newPage();
  const errors=[]; for(const page of [requesterPage,supportPage]) page.on('pageerror',error=>errors.push(error.message));
  async function login(page,email){ await page.goto(webUrl);await page.getByLabel('工作邮箱').fill(email);await page.getByLabel('密码',{exact:true}).fill(password);await page.getByRole('button',{name:'进入工作台'}).click();await page.getByRole('button',{name:'我的报障',exact:true}).waitFor(); }
  async function upload(region,name,body,mime) {
    await region.getByLabel('选择附件',{exact:true}).setInputFiles({name,mimeType:mime,buffer:body});
    await region.getByRole('button',{name:'上传附件',exact:true}).click();
    await region.getByText(name,{exact:true}).waitFor();
  }
  async function download(page,region,name,expected) {
    const waiting=page.waitForEvent('download');
    await region.getByRole('button',{name:`下载 ${name}`,exact:true}).click();
    const saved=await waiting;
    assert.equal(saved.suggestedFilename(),name);
    assert.equal(hash(readFileSync(await saved.path())),hash(expected));
  }
  try {
    await login(requesterPage,ownerEmail);
    await requesterPage.getByRole('button',{name:'我的报障',exact:true}).click();
    const mine=requesterPage.getByRole('region',{name:'私有工单附件',exact:true});
    await mine.getByLabel('选择附件',{exact:true}).waitFor();
    await upload(mine,'网络截图.png',png,'image/png');
    await upload(mine,'排查信息.txt',Buffer.from('演示环境：公司无线网络，VPN认证超时。'),'text/plain');
    // Immediately submit a public follow-up to prove attachment success refreshed the parent's CAS version.
    await requesterPage.getByLabel('补充资料',{exact:true}).fill('已附上截图和排查信息。');
    await requesterPage.getByRole('button',{name:'发送补充',exact:true}).click();
    await requesterPage.getByText('已附上截图和排查信息。',{exact:true}).waitFor();
    await login(supportPage,supportEmail);
    await supportPage.getByRole('button',{name:/^工单队列/}).click();
    const card=supportPage.locator('.ticket-card').filter({hasText:ticketId.slice(0,8)});
    await card.locator('summary').first().click();
    const team=card.getByRole('region',{name:'私有工单附件',exact:true});
    await team.getByText('网络截图.png',{exact:true}).waitFor();
    await download(supportPage,team,'网络截图.png',png);
    assert.equal(await team.getByRole('button',{name:'删除 网络截图.png',exact:true}).count(),0);
    await upload(team,'支持排查.log',log,'text/plain');
    await card.getByLabel('公开回复',{exact:true}).fill('已回传支持侧排查日志，请查收。');
    await card.getByRole('button',{name:'发送公开回复',exact:true}).click();
    await card.getByText('已回传支持侧排查日志，请查收。',{exact:true}).waitFor();
    await requesterPage.getByRole('button',{name:'刷新进度',exact:true}).click();
    await mine.getByText('支持排查.log',{exact:true}).waitFor();
    await download(requesterPage,mine,'支持排查.log',log);
    await requesterPage.setViewportSize({width:390,height:844});
    assert(await requesterPage.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await requesterPage.screenshot({path:process.env.RESOLVEAI_SCREENSHOT || path.join(root,'docs/resolveai-ticket-attachments.png'),fullPage:true});
    await mine.getByRole('button',{name:'删除 网络截图.png',exact:true}).click();
    await mine.getByText('网络截图.png',{exact:true}).waitFor({state:'detached'});
    const personal=await api(`/helpdesk/my-tickets/${ticketId}/attachments`,'GET',undefined,owner.access_token);
    assert(!personal.items.some(item=>item.filename==='网络截图.png'));
    await mine.getByRole('button',{name:'删除 排查信息.txt',exact:true}).click();
    await mine.getByText('排查信息.txt',{exact:true}).waitFor({state:'detached'});
    await supportPage.getByRole('button',{name:'刷新列表',exact:true}).click();
    await team.getByRole('button',{name:'删除 支持排查.log',exact:true}).click();
    await team.getByText('支持排查.log',{exact:true}).waitFor({state:'detached'});
    assert.equal((await api(`/helpdesk/tickets/${ticketId}/attachments`,'GET',undefined,support.access_token)).items.length,0);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,workflow:'requester PNG/TXT → support authenticated download SHA check → support LOG → requester authenticated download SHA check → UI deletes',immediate_public_replies:true,mobile_width:390,page_errors:errors.length}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
