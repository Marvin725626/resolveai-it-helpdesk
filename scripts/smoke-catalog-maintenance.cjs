const assert = require("node:assert/strict");
const { randomBytes, randomUUID } = require("node:crypto");
const { createRequire } = require("node:module");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const { chromium } = process.env.PLAYWRIGHT_MODULE
  ? require(process.env.PLAYWRIGHT_MODULE)
  : createRequire(path.join(root, "frontend/package.json"))("playwright");
const web = process.env.RESOLVEAI_URL || "http://127.0.0.1:5174";
assert.equal(process.env.RESOLVEAI_ALLOW_SYNTHETIC_WRITES, "1");
assert(["localhost", "127.0.0.1"].includes(new URL(web).hostname));
(async () => {
  const suffix = randomBytes(7).toString("hex"),
    password = randomBytes(20).toString("hex") + "Aa1!",
    email = `maintenance-${suffix}@example.com`;
  async function api(route, method = "GET", body, token) {
    const r = await fetch(web + "/api/v1" + route, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: "Bearer " + token } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    assert(r.ok, `${method} ${route}: ${r.status}`);
    return r.json();
  }
  const owner = await api("/auth/register", "POST", {
    email,
    password,
    full_name: "目录验收管理员",
    tenant_name: "目录维护验收",
    tenant_slug: "maintenance-" + suffix,
  });
  const token = owner.access_token,
    endpoint = "/helpdesk/service-catalog-admin";
  const title = "设备接入 " + suffix,
    code = "device-" + suffix;
  const content = {
    code,
    title,
    summary: "合成设备申请原始模板",
    category: "hardware",
    status: "published",
    fields: [
      { key: "device_name", label: "设备名称", type: "text", required: true },
    ],
  };
  const item = (
    await api(endpoint, "POST", { ...content, request_id: randomUUID() }, token)
  ).item;
  const submission = await api(
    "/helpdesk/service-catalog/" + item.id + "/submit",
    "POST",
    {
      request_id: randomUUID(),
      expected_version: 1,
      answers: { device_name: "Synthetic Laptop" },
    },
    token,
  );
  const snapshot = (
    await api(
      "/helpdesk/my-tickets/" + submission.ticket_id,
      "GET",
      undefined,
      token,
    )
  ).ticket.request.service;
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined,
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const sent = [];
  page.on("request", (r) => {
    if (
      ["POST", "PUT"].includes(r.method()) &&
      r.url().includes("/service-catalog-admin")
    )
      sent.push({ method: r.method(), body: r.postDataJSON() });
  });
  try {
    await page.goto(web);
    await page.getByLabel("工作邮箱").fill(email);
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByRole("button", { name: "进入工作台" }).click();
    await page
      .getByRole("button", { name: "服务目录管理", exact: true })
      .click();
    await page.getByLabel("服务名称").fill(title + " 新版");
    await page.getByLabel("显示名称").fill("电脑名称");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    const history = page.locator('[aria-label="服务修订历史"]');
    await history.locator("summary").filter({ hasText: /^v2\s/ }).waitFor();
    assert.deepEqual(
      Object.keys(sent.find((x) => x.method === "PUT").body).sort(),
      [
        "code",
        "title",
        "summary",
        "category",
        "fields",
        "status",
        "expected_version",
      ].sort(),
    );
    let saved = (await api(endpoint, "GET", undefined, token)).items.find(
      (x) => x.id === item.id,
    );
    assert.equal(saved.version, 2);
    assert.equal(saved.fields[0].label, "电脑名称");
    // Historical content remains readable and compares against the saved template.
    const first = history
      .locator("details")
      .filter({ has: page.locator("summary").filter({ hasText: /^v1\s/ }) });
    await first.locator("summary").click();
    await first.getByText("设备名称", { exact: true }).first().waitFor();
    await page.getByLabel("状态").selectOption("archived");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await history.locator("summary").filter({ hasText: /^v3\s/ }).waitFor();
    const old = history
      .locator("details")
      .filter({ has: page.locator("summary").filter({ hasText: /^v1\s/ }) });
    if ((await old.getAttribute("open")) === null)
      await old.locator("summary").click();
    await old
      .getByRole("button", { name: "恢复到编辑器", exact: true })
      .click();
    assert.equal(await page.getByLabel("服务名称").inputValue(), title);
    assert.equal(await page.getByLabel("状态").inputValue(), "archived");
    assert.equal(
      (await api(endpoint, "GET", undefined, token)).items.find(
        (x) => x.id === item.id,
      ).version,
      3,
      "Loading history must not write",
    );
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await history.locator("summary").filter({ hasText: /^v4\s/ }).waitFor();
    assert.deepEqual(
      (
        await api(
          "/helpdesk/my-tickets/" + submission.ticket_id,
          "GET",
          undefined,
          token,
        )
      ).ticket.request.service,
      snapshot,
    );
    // A stale save preserves edits, and a refresh requires an explicit discard.
    saved = (await api(endpoint, "GET", undefined, token)).items.find(
      (x) => x.id === item.id,
    );
    await page.getByLabel("简介").fill("本地未保存编辑");
    await api(
      endpoint + "/" + item.id,
      "PUT",
      {
        ...content,
        status: "archived",
        title: "其他管理员更新",
        expected_version: saved.version,
      },
      token,
    );
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await page
      .getByRole("alert")
      .filter({ hasText: /冲突|更新/ })
      .waitFor();
    assert.equal(await page.getByLabel("简介").inputValue(), "本地未保存编辑");
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await page.getByRole("button", { name: "保留编辑", exact: true }).click();
    assert.equal(await page.getByLabel("简介").inputValue(), "本地未保存编辑");
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await page
      .getByRole("button", { name: "放弃更改并继续", exact: true })
      .click();
    await page.waitForFunction(() =>
      Array.from(document.querySelectorAll("input")).some(
        (e) => e.value === "其他管理员更新",
      ),
    );
    await page
      .getByRole("button", { name: "复制为新草稿", exact: true })
      .click();
    assert.equal(await page.getByLabel("服务代码").inputValue(), "");
    assert.equal(await page.getByLabel("状态").inputValue(), "draft");
    await page.getByLabel("服务代码").fill("copy-" + suffix);
    // Abort only the response after the backend has committed. Retry must replay.
    let interrupted = false;
    await page.route(
      "**/api/v1/helpdesk/service-catalog-admin",
      async (route) => {
        if (route.request().method() === "POST" && !interrupted) {
          interrupted = true;
          await route.fetch();
          await route.abort("failed");
        } else await route.continue();
      },
    );
    await page.getByRole("button", { name: "创建服务", exact: true }).click();
    await page.getByRole("alert").waitFor();
    await page.getByRole("button", { name: "创建服务", exact: true }).click();
    await history.locator("summary").filter({ hasText: /^v1\s/ }).waitFor();
    const creates = sent.filter((x) => x.method === "POST");
    assert.equal(creates.length, 2);
    assert.equal(creates[0].body.request_id, creates[1].body.request_id);
    const items = (await api(endpoint, "GET", undefined, token)).items;
    assert.equal(items.length, 2);
    const copy = items.find((x) => x.code === "copy-" + suffix);
    assert(copy);
    assert.equal(copy.status, "draft");
    assert.notEqual(copy.id, item.id);
    assert.equal(
      (await api("/helpdesk/service-catalog", "GET", undefined, token)).items
        .length,
      0,
      "Archived original and draft copy remain private",
    );
    // An older service history response must not replace the selected copy history.
    let releaseHistory;
    const historyGate = new Promise((resolve) => {
      releaseHistory = resolve;
    });
    let sawHistory;
    const historySeen = new Promise((resolve) => {
      sawHistory = resolve;
    });
    let historyFulfilled;
    const historyDone = new Promise((resolve) => {
      historyFulfilled = resolve;
    });
    const oldHistoryUrl =
      "**/api/v1/helpdesk/service-catalog-admin/" + item.id + "/revisions";
    await page.route(oldHistoryUrl, async (route) => {
      const response = await route.fetch();
      sawHistory();
      await historyGate;
      await route.fulfill({ response });
      historyFulfilled();
    });
    await page
      .locator(".catalog-list button")
      .filter({ hasText: code })
      .click();
    await historySeen;
    await page
      .locator(".catalog-list button")
      .filter({ hasText: "copy-" + suffix })
      .click();
    await history.locator("summary").filter({ hasText: /^v1\s/ }).waitFor();
    releaseHistory();
    await historyDone;
    await page.unroute(oldHistoryUrl);
    // Drain a frame after the delayed response has settled before inspecting state.
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    assert.equal(await history.locator("summary").count(), 1);
    let failedHistory = false;
    const copyHistoryUrl =
      "**/api/v1/helpdesk/service-catalog-admin/" + copy.id + "/revisions";
    await page.route(copyHistoryUrl, async (route) => {
      if (!failedHistory) {
        failedHistory = true;
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: '{"detail":"Synthetic history outage"}',
        });
      } else await route.continue();
    });
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await page.getByRole("button", { name: "重试历史", exact: true }).click();
    await history.locator("summary").filter({ hasText: /^v1\s/ }).waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    assert.deepEqual(errors, []);
    if (process.env.RESOLVEAI_QA_SCREENSHOTS === "1")
      await page.screenshot({
        path: path.join(root, ".local/catalog-maintenance-qa.png"),
        fullPage: true,
      });
    console.log(
      JSON.stringify({
        passed: true,
        ui_edit_publish: true,
        history_refresh: true,
        restore_is_draft_until_save: true,
        archived_status_preserved: true,
        old_ticket_snapshot_unchanged: true,
        conflict_preserves_input: true,
        discard_is_explicit: true,
        copy_independent_draft: true,
        history_failure_retry: true,
        late_history_isolated: true,
        interrupted_create_retries_same_id: true,
        mobile_width: 390,
        page_errors: 0,
      }),
    );
  } catch (e) {
    await page
      .screenshot({
        path: path.join(root, ".local/catalog-maintenance-failure.png"),
        fullPage: true,
      })
      .catch(() => {});
    throw e;
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
