const assert = require("node:assert/strict");
const { randomBytes } = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");
const { createRequire } = require("node:module");

const root = process.env.RESOLVEAI_ROOT || path.resolve(__dirname, "..");
const requireFrontend = createRequire(path.join(root, "frontend/package.json"));
const { chromium } = process.env.PLAYWRIGHT_MODULE
  ? require(process.env.PLAYWRIGHT_MODULE)
  : requireFrontend("playwright");
const baseUrl = process.env.RESOLVEAI_URL || "http://127.0.0.1:5174";
assert.equal(
  process.env.RESOLVEAI_ALLOW_SYNTHETIC_WRITES,
  "1",
  "Set RESOLVEAI_ALLOW_SYNTHETIC_WRITES=1 to allow disposable smoke fixtures.",
);
assert(
  ["127.0.0.1", "localhost", "::1"].includes(new URL(baseUrl).hostname),
  "This smoke check only writes to a loopback ResolveAI instance.",
);
const suffix = randomBytes(8).toString("hex");
const ownerEmail = `portal-owner-${suffix}@example.com`;
const ownerPassword = `${randomBytes(20).toString("hex")}Aa1!`;
const inviteEmail = `portal-${suffix.toLowerCase()}@example.com`;
const serviceCode = `smoke-${suffix}`;
const serviceTitle = `员工门户验收 ${suffix}`;
const fieldLabel = "设备名称";
const fieldAnswer = `Laptop-${suffix}`;
const forbidden =
  /\/api\/v1\/helpdesk\/(?:overview(?:\?|$)|runs(?:\/|\?|$)|runbooks(?:\?|$)|readiness(?:\?|$)|analytics(?:\/|\?|$)|team(?:\/|\?|$))/;

async function signIn(page, email, password) {
  await page.goto(baseUrl);
  await page.getByLabel("工作邮箱").fill(email);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "进入工作台" }).click();
  await page
    .locator(".page-heading")
    .getByRole("heading", { name: "让 IT 问题更快得到响应" })
    .waitFor();
}

async function api(page, endpoint, method = "GET", body) {
  return page.evaluate(
    async ({ endpoint, method, body }) => {
      const response = await fetch(`/api/v1${endpoint}`, {
        method,
        headers: {
          Authorization: `Bearer ${localStorage.getItem("resolveai_token")}`,
          "Content-Type": "application/json",
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(
          `${method} ${endpoint} failed (${response.status}): ${JSON.stringify(data)}`,
        );
      return data;
    },
    { endpoint, method, body },
  );
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined,
  });
  const ownerContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
  });
  const owner = await ownerContext.newPage();
  const requesterContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
  });
  const employee = await requesterContext.newPage();
  const pageErrors = [];
  const employeeRequests = [];
  owner.on("pageerror", (error) => pageErrors.push(`owner: ${error.message}`));
  employee.on("pageerror", (error) =>
    pageErrors.push(`employee: ${error.message}`),
  );
  employee.on("request", (request) => employeeRequests.push(request.url()));
  try {
    const registerResponse = await fetch(`${baseUrl}/api/v1/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: ownerEmail,
        password: ownerPassword,
        full_name: `Portal owner ${suffix}`,
        tenant_name: `Portal smoke ${suffix}`,
        tenant_slug: `portal-smoke-${suffix}`,
      }),
    });
    const registrationBody = await registerResponse.json().catch(() => ({}));
    assert.equal(
      registerResponse.status,
      201,
      `Synthetic owner registration failed (${registerResponse.status}): ${JSON.stringify(registrationBody.detail || registrationBody)}.`,
    );
    await signIn(owner, ownerEmail, ownerPassword);

    // Create and publish a random service through the catalog UI.
    await owner
      .getByRole("button", { name: "服务目录管理", exact: true })
      .click();
    await owner
      .locator(".page-heading")
      .getByRole("heading", { name: "服务目录管理", exact: true })
      .waitFor();
    await owner.getByRole("button", { name: "新增服务", exact: true }).click();
    await owner.getByLabel("服务代码").fill(serviceCode);
    await owner.getByLabel("服务名称").fill(serviceTitle);
    await owner.getByLabel("分类").selectOption("hardware");
    await owner.getByLabel("状态").selectOption("published");
    await owner.getByLabel("简介").fill("用于验收员工门户的随机设备申请模板。");
    await owner.getByRole("button", { name: "添加字段", exact: true }).click();
    const field = owner.locator("fieldset.catalog-field").last();
    const fieldKey = field.getByLabel("字段标识");
    await fieldKey.focus();
    await owner.keyboard.type("device_name");
    assert.equal(
      await fieldKey.inputValue(),
      "device_name",
      "Field identifier typing should keep focus across React updates.",
    );
    assert.equal(
      await fieldKey.evaluate((element) => element === document.activeElement),
      true,
    );
    await field.getByLabel("显示名称").fill(fieldLabel);
    await field.getByLabel("必填").check();
    await owner.getByRole("button", { name: "创建服务", exact: true }).click();
    await owner
      .getByRole("status")
      .filter({ hasText: "服务目录项已创建" })
      .waitFor();
    await owner.locator(".catalog-list").getByText(serviceCode).waitFor();
    if (process.env.RESOLVEAI_QA_SCREENSHOTS === "1") {
      await fs.mkdir(path.join(root, ".local"), { recursive: true });
      await owner.screenshot({
        path: path.join(root, ".local", "v2-catalog-qa.png"),
        fullPage: true,
      });
    }

    // Invite a requester from the team UI; the app shows a share link and sends no email.
    await owner.getByRole("button", { name: "团队管理", exact: true }).click();
    await owner
      .getByRole("heading", { name: "邀请工作区成员", exact: true })
      .waitFor();
    await owner.getByLabel("工作邮箱").fill(inviteEmail);
    await owner.getByLabel("邀请角色").selectOption("REQUESTER");
    await owner.getByRole("button", { name: "创建邀请", exact: true }).click();
    const inviteUrl = await owner.locator("#new-invite-link").inputValue();
    assert(
      inviteUrl.includes("/invite#"),
      "The invitation link should be shown for manual sharing.",
    );

    // Accept the invite in an isolated browser context.
    await employee.goto(inviteUrl);
    await employee.getByRole("heading", { name: "创建你的账号" }).waitFor();
    await employee.getByLabel("受邀邮箱").fill(inviteEmail);
    await employee.getByLabel("显示姓名").fill(`Employee ${suffix}`);
    await employee.getByLabel("设置密码").fill("PortalSmoke!A1");
    await employee
      .getByRole("button", { name: "接受邀请并进入工作台" })
      .click();
    await employee
      .locator(".page-heading")
      .getByRole("heading", { name: "服务大厅" })
      .waitFor();
    const navItems = await employee
      .locator('nav[aria-label="工作台导航"] button')
      .allTextContents();
    assert.deepEqual(
      navItems.map((value) => value.trim()),
      ["服务大厅", "个人通知", "我的报障"],
    );
    await employee
      .getByRole("navigation", { name: "账号操作" })
      .getByRole("button", { name: "退出登录" })
      .waitFor();
    assert(
      (await employee.locator(".portal-stat").count()) === 3,
      "Requester sees only personal request counts.",
    );
    if (process.env.RESOLVEAI_QA_SCREENSHOTS === "1") {
      await fs.mkdir(path.join(root, ".local"), { recursive: true });
      await employee.screenshot({
        path: path.join(root, ".local", "v2-portal-qa.png"),
        fullPage: true,
      });
    }

    await employee.getByLabel("搜索服务").fill(serviceTitle);
    await employee
      .getByRole("heading", { name: serviceTitle, exact: true })
      .waitFor();
    await employee.getByRole("button", { name: "查看并申请" }).click();
    await employee.getByLabel(`服务申请-${fieldLabel}`).fill(fieldAnswer);
    await employee.getByRole("button", { name: "提交服务申请" }).click();
    await employee.locator('[aria-label="服务申请快照"]').waitFor();
    await employee
      .locator('[aria-label="服务申请快照"]')
      .getByRole("heading", { name: `服务申请 · ${serviceTitle}` })
      .waitFor();
    await employee
      .locator('[aria-label="服务申请快照"]')
      .getByText(fieldLabel)
      .waitFor();
    await employee
      .locator('[aria-label="服务申请快照"]')
      .getByText(fieldAnswer)
      .waitFor();
    const overview = await api(employee, "/helpdesk/portal/overview");
    assert.equal(
      overview.total,
      1,
      "The synthetic employee should own one request.",
    );
    const requestDetail = await api(
      employee,
      `/helpdesk/my-tickets/${overview.latest[0].id}`,
    );
    assert.deepEqual(requestDetail.ticket.request.service, {
      item_id: requestDetail.ticket.request.service.item_id,
      code: serviceCode,
      title: serviceTitle,
      version: 1,
      fields: [{ key: "device_name", label: fieldLabel, answer: fieldAnswer }],
    });

    // Verify the employee only requested private portal, published catalog and personal inbox data.
    const observed = employeeRequests.map(
      (url) => new URL(url).pathname + new URL(url).search,
    );
    assert(observed.some((url) => url.includes("/helpdesk/portal/overview")));
    assert(observed.some((url) => url.includes("/helpdesk/service-catalog")));
    assert(
      !observed.some((url) => forbidden.test(url)),
      `Requester called a staff endpoint: ${observed.filter((url) => forbidden.test(url)).join(", ")}`,
    );

    await employee.setViewportSize({ width: 390, height: 844 });
    await employee
      .getByRole("button", { name: "服务大厅", exact: true })
      .click();
    await employee.getByLabel("搜索服务").fill(serviceTitle);
    await employee.getByRole("button", { name: "查看并申请" }).click();
    await employee.getByLabel(`服务申请-${fieldLabel}`).waitFor();
    assert(
      await employee.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      "Portal should fit a 390px viewport without horizontal overflow.",
    );
    assert.deepEqual(pageErrors, []);
    console.log(
      JSON.stringify(
        {
          passed: true,
          tenant: "synthetic random tenant",
          serviceCode,
          checks: [
            "random owner account and tenant",
            "owner created and published a unique catalog service in the UI",
            "REQUESTER invitation role and manual link flow",
            "requester has role-scoped navigation",
            "employee submitted service request and sees an immutable snapshot",
            "employee session used no staff-only endpoint",
            "390px service form has no horizontal overflow",
            "no page errors",
          ],
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
