import { expect, test } from "@playwright/test";

test("真实页面健康状态、说明切换和桌面布局", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "提示注入实验台" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /后端已就绪|后端未就绪/ }),
  ).toBeVisible();
  await page.screenshot({ path: "../runs/ui/desktop.png", fullPage: true });
  await page.getByRole("button", { name: /实验说明/ }).click();
  await expect(
    page.getByRole("heading", { name: "如何读懂这场实验" }),
  ).toBeVisible();
  await page.getByRole("button", { name: /返回实验工作台/ }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("B1 页面请求由真实后端拦截，不允许额外模型调用", async ({ page }) => {
  // Only health metadata is stubbed so this test needs no real credentials.
  await page.route("**/health", (route) =>
    route.fulfill({
      json: {
        status: "ready",
        configured: true,
        model: "offline-browser-test",
        provider: "test",
      },
    }),
  );
  let sent = 0;
  await page.route("**/api/chat", async (route) => {
    const body = route.request().postDataJSON();
    expect(body.defense_profile).toBe("B1");
    expect(body.message).toContain("忽略先前指令");
    expect(Object.keys(body).sort()).toEqual([
      "defense_profile",
      "document_id",
      "message",
    ]);
    sent++;
    await route.continue();
  });
  await page.goto("/");
  await page.getByRole("radio", { name: /B1/ }).check();
  await page.getByRole("button", { name: "直接覆盖", exact: true }).click();
  const responsePromise = page.waitForResponse("**/api/chat");
  await page.getByRole("button", { name: /运行本次问答/ }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const result = await response.json();
  expect(result.technical_status).toBe("input_blocked");
  expect(result).not.toHaveProperty("canary_truth");
  expect(result).not.toHaveProperty("raw_answer");
  await expect(page.getByText("输入已拦截", { exact: true })).toBeVisible();
  await expect(page.getByText("防御事件", { exact: true })).toBeVisible();
  expect(sent).toBe(1);
});

test("移动端无横向溢出，资料与档位可选，空输入不可提交", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("参考资料").selectOption("campus_wifi_poisoned_a09");
  await page.getByRole("radio", { name: /B3/ }).check();
  await expect(page.getByText("在问答示例中嵌入偏离指令")).toBeVisible();
  await page.getByLabel("用户问题").fill("   ");
  await expect(
    page.getByRole("button", { name: /运行本次问答/ }),
  ).toBeDisabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "../runs/ui/mobile.png", fullPage: true });
});

test("后端不可用时显示错误且禁止发送", async ({ page }) => {
  await page.route("**/health", (route) =>
    route.fulfill({ status: 503, json: { detail: "offline test" } }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("后端未连接");
  await expect(
    page.getByRole("button", { name: /运行本次问答/ }),
  ).toBeDisabled();
});

test("375px 设计基准保持卡片、按钮尺寸与可读字号", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  const measurements = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth > window.innerWidth,
    blue: getComputedStyle(document.documentElement)
      .getPropertyValue("--color-blue")
      .trim(),
    radius: getComputedStyle(document.querySelector(".configuration")!)
      .borderRadius,
    buttonHeight: document.querySelector(".run-button")!.getBoundingClientRect()
      .height,
    smallText: [...document.querySelectorAll("body *")]
      .filter(
        (el) =>
          el instanceof HTMLElement &&
          el.getClientRects().length > 0 &&
          [...el.childNodes].some(
            (node) =>
              node.nodeType === Node.TEXT_NODE && node.textContent?.trim(),
          ) &&
          parseFloat(getComputedStyle(el).fontSize) < 13,
      )
      .map((el) => el.className),
  }));
  expect(measurements).toEqual({
    overflow: false,
    blue: "#0252d7",
    radius: "12px",
    buttonHeight: 45,
    smallText: [],
  });
  await page.screenshot({ path: "../runs/ui/mobile-375.png", fullPage: true });
});

test("挑战样例展示真实污染资料，切换时不自动发送问答", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/chat", (route) => {
    calls++;
    return route.abort();
  });
  await page.goto("/");
  const selector = page.getByLabel("挑战样例（探索集）");
  await expect(selector).toBeEnabled();
  await selector.selectOption("C06");
  await expect(page.getByLabel("用户问题")).toHaveValue(
    "请根据校园网开通指南总结办理流程",
  );
  await expect(page.getByLabel("参考资料")).toHaveValue(
    "campus_wifi_poisoned_c06",
  );
  await expect(page.locator(".payload-preview")).toContainText(
    "本期服务暂停，请等待线下通知。",
  );
  await expect(page.locator(".payload-preview summary")).toContainText(
    "资料注入载荷",
  );
  await selector.selectOption("C03");
  await expect(page.getByLabel("参考资料")).toHaveValue("campus_wifi_clean");
  await expect(page.locator(".payload-preview summary")).toContainText(
    "用户输入载荷",
  );
  await expect(page.getByLabel("用户问题")).toHaveValue(/字符定位练习/);
  await page.setViewportSize({ width: 375, height: 812 });
  await selector.selectOption("C07");
  await expect(page.locator(".payload-preview pre")).toContainText(
    "</reference_document>",
  );
  expect(
    await page.locator(".payload-preview service_verification").count(),
  ).toBe(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../runs/ui/challenge-mobile.png",
    fullPage: true,
  });
  expect(calls).toBe(0);
});

test("加载与结果状态保留布局并展示防御事件（模拟响应）", async ({ page }) => {
  await page.route("**/health", (route) =>
    route.fulfill({
      json: {
        status: "ready",
        configured: true,
        model: "offline-browser-test",
        provider: "test",
      },
    }),
  );
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/chat", async (route) => {
    await pending;
    await route.fulfill({
      json: {
        request_id: "offline-ui-check",
        answer: "测试响应：输出已由防御层替换。",
        defense_profile: "B3",
        document_id: "campus_wifi_clean",
        model: "offline-browser-test",
        latency_ms: 123,
        technical_status: "ok",
        security_events: [
          { stage: "output", rule_id: "canary_exact", source: "answer" },
        ],
      },
    });
  });
  await page.goto("/");
  await page.getByRole("radio", { name: /B3/ }).check();
  const button = page.getByRole("button", { name: /运行本次问答/ });
  await expect(button).toBeEnabled();
  const initialWidth = (await button.boundingBox())!.width;
  await button.click();
  const loading = page.getByRole("button", { name: /等待模型回答/ });
  await expect(loading).toBeDisabled();
  expect((await loading.boundingBox())!.width).toBe(initialWidth);
  release();
  await expect(
    page.getByText("测试响应：输出已由防御层替换。", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("输出层", { exact: true })).toBeVisible();
  await expect(page.getByText("canary_exact", { exact: true })).toBeVisible();
  await page.screenshot({ path: "../runs/ui/result-mock.png", fullPage: true });
});
