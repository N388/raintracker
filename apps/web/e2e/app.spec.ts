import { expect, test } from "@playwright/test";

const API = process.env.E2E_API_URL ?? "http://localhost:8080/api/v1";

test.describe("منصة مطر — سيناريوهات قبول M3/M4", () => {
  test("الخريطة تُحمّل مع الطبقات واللوحات", async ({ page }) => {
    await page.goto("/#6/25.0/44.0");
    await expect(page.getByPlaceholder(/مدينة، واد/)).toBeVisible();
    await expect(page.getByText("الطبقات")).toBeVisible();
    await expect(page.getByText("مجموع المطر (مم)")).toBeVisible();
    await expect(page.getByRole("button", { name: /الوسم/ })).toBeVisible();
    // قماش الخريطة يوجد وبحجم كامل
    const canvas = page.locator("canvas");
    await expect(canvas).toBeVisible();
    const box = await canvas.boundingBox();
    expect(box!.height).toBeGreaterThan(600);
  });

  test("البحث عن واد ينتقل إليه", async ({ page }) => {
    await page.goto("/#6/25.0/44.0");
    const input = page.getByPlaceholder(/مدينة، واد/);
    await input.fill("وادي تريم");
    await expect(page.getByText("وادي تريم").first()).toBeVisible({ timeout: 10_000 });
  });

  test("الضغط على نقطة يعرض بطاقة المطر بصياغة خلية البيانات", async ({ page }) => {
    await page.goto("/#8/31.0/41.5");
    await page.waitForTimeout(6000);
    await page.mouse.click(700, 450);
    await expect(page.getByText("آخر مطر في خلية البيانات")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("الوسم 2025")).toBeVisible();
    await expect(page.getByText("الارتفاع:")).toBeVisible();
  });

  test("تبديل الطبقات يعمل", async ({ page }) => {
    await page.goto("/#6/25.0/44.0");
    const box = page.getByRole("checkbox", { name: "الأودية والمجاري" });
    await expect(box).toBeChecked();
    await box.uncheck();
    await expect(box).not.toBeChecked();
  });

  test("لوحة التحكم: دخول ولوحة قيادة وإعدادات", async ({ page }) => {
    await page.goto("/admin");
    await page.getByPlaceholder("البريد").fill("admin@example.com");
    await page.getByPlaceholder("كلمة المرور").fill("admin123");
    await page.getByRole("button", { name: "دخول" }).click();
    await expect(page.getByText("أيام المطر")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "الإعدادات" }).click();
    await expect(page.getByText("تاريخ البداية")).toBeVisible();
  });

  test("API: نقطة المطر تتضمن النوافذ والوسم", async ({ request }) => {
    const r = await request.get(`${API}/rain/point?lat=24.71&lon=46.68&source=both`);
    expect(r.ok()).toBeTruthy();
    const d = await r.json();
    expect(d.sources.imerg_v07.sums_mm).toHaveProperty("last_10d");
    expect(d.sources.chirps_v3.wasm).toHaveProperty("year");
    expect(d.sources.imerg_v07.disclaimer).toContain("خلية");
  });
});
