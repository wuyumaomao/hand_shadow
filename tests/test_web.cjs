// Actual browser -> HTTP -> Blender integration. Run with the supplied Node runtime.
const { chromium } = require(process.env.RUNTIME_NODE_MODULES + '/playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const base = process.env.SHADOW_WEB_URL || 'http://127.0.0.1:8765';

(async () => {
  const out = path.join(root, 'outputs/web_qa'); await fs.mkdir(out, {recursive: true});
  const browser = await chromium.launch({headless: true, executablePath: process.env.SHADOW_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page = await browser.newPage({viewport: {width: 1440, height: 1080}});
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  async function ready(previous) {
    await page.waitForFunction(previous => {
      const image = document.getElementById('preview-image');
      return document.getElementById('preview-badge').textContent === '预览已更新' && image.getAttribute('src') !== previous && image.complete && image.naturalWidth > 0;
    }, previous || '', {timeout: 90000});
    return page.locator('#preview-image').getAttribute('src');
  }
  async function imageConfig() {
    const src = await page.locator('#preview-image').getAttribute('src');
    return (await page.request.get(base + src.replace('image_00000.png', 'config.json'))).json();
  }
  try {
    await page.goto(base); let image = await ready();
    await page.screenshot({path: path.join(out, '01-desktop.png'), fullPage: true});
    assert.equal(await page.locator('#generate').isDisabled(), true);
    // Rapid edits must render the last value, not display stale results.
    const move = page.getByRole('spinbutton', {name: '整体位置偏移 X', exact: true});
    await move.fill('1'); await move.fill('3');
    image = await ready(image);
    assert.equal((await imageConfig()).hands.left.translation.x, 3);
    await page.locator('[data-tab=camera]').click();
    await page.getByRole('spinbutton', {name: '相机位置 X', exact: true}).fill('8');
    image = await ready(image);
    assert.equal((await imageConfig()).camera.position.x, 8);
    await page.locator('[data-tab=light]').click();
    await page.getByRole('spinbutton', {name: '日光旋转 X', exact: true}).fill('2');
    image = await ready(image);
    assert.equal((await imageConfig()).light.rotation_degrees.x, 2);
    // Confirm a scene, then changing it must invalidate stage 2 immediately.
    await page.locator('#confirm-scene').click();
    await page.waitForFunction(() => document.getElementById('confirmation').textContent.includes('场景已确认'), {timeout: 60000});
    assert.equal(await page.locator('#generate').isEnabled(), true);
    await page.getByRole('spinbutton', {name: '日光旋转 X', exact: true}).fill('0');
    assert.equal(await page.locator('#generate').isDisabled(), true);
    image = await ready(image);
    // Both scene modes and initial finger state work through the same controller.
    await page.locator('#mode').selectOption('single'); image = await ready(image);
    assert.equal((await imageConfig()).mode, 'single');
    await page.locator('[data-tab=hands]').click();
    await page.getByRole('button', {name: '食指：伸直', exact: true}).click(); image = await ready(image);
    assert.equal((await imageConfig()).hands.left.state[1], 4);
    await page.locator('#mode').selectOption('multi'); image = await ready(image);
    await page.locator('.render-settings summary').click();
    await page.locator('#width').fill('128'); await page.locator('#height').fill('128');
    image = await ready(image);
    await page.locator('#confirm-scene').click();
    await page.waitForFunction(() => document.getElementById('confirmation').textContent.includes('场景已确认'), {timeout: 60000});
    // Verify the saved scene keeps formal resolution (not a forced preview setting).
    const configLink = await page.getByRole('link', {name: '查看配置记录'}).getAttribute('href');
    const saved = await (await page.request.get(base + configLink)).json();
    assert.deepEqual(saved.render.resolution, [128, 128]);
    for (const row of await page.locator('.rule-row').all()) {
      if (await row.getAttribute('data-rule') !== 'count_preserve') await row.locator('.rule-enabled').uncheck();
    }
    const row = page.locator('[data-rule=count_preserve]');
    await row.locator('.rule-all').uncheck(); await row.locator('.rule-count').fill('1');
    await page.locator('#generate').click();
    await page.locator('#generation-result').waitFor({state: 'visible', timeout: 90000});
    await page.waitForFunction(() => document.querySelector('#pair-gallery img')?.naturalWidth > 0);
    assert.equal(await page.locator('#pair-gallery figure').count(), 1);
    assert.match(await page.locator('#progress-message').textContent(), /已完成：1 对/);
    await page.screenshot({path: path.join(out, '02-result.png'), fullPage: true});
    // Config export is usable without editing Python.
    const downloadEvent = page.waitForEvent('download'); await page.locator('#export-scene').click();
    const download = await downloadEvent; await download.saveAs(path.join(out, 'exported-scene.json'));
    const exported = JSON.parse(await fs.readFile(path.join(out, 'exported-scene.json'), 'utf8'));
    assert.equal(exported.mode, 'multi'); assert.equal(exported.samples, undefined);
    // Validated import updates the form and auto-preview.
    exported.camera.position.x = 8;
    const imported = path.join(out, 'import-scene.json'); await fs.writeFile(imported, JSON.stringify(exported));
    await page.locator('#scene-file').setInputFiles(imported); image = await ready(image);
    assert.equal((await imageConfig()).camera.position.x, 8);
    await page.setViewportSize({width: 390, height: 844});
    await page.screenshot({path: path.join(out, '03-mobile.png'), fullPage: true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    assert.deepEqual(errors, []);
    console.log('WEB_CHECKS_PASSED: automatic preview, latest edits, camera/light/hand changes, modes, confirmation invalidation, generation, config import/export, mobile layout');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
