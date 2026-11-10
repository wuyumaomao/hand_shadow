'use strict';
const $ = id => document.getElementById(id);
const clone = value => structuredClone(value);
const ruleInfo = {
  count_preserve: ['数量保持', '整体状态弯曲数量相同，组合不同', 220],
  shift_one: ['单指循环右移', '整体状态只有一指伸直，循环右移一位', 5],
  shift_two: ['双指循环右移', '整体状态只有两指伸直，循环右移一位', 10],
  lighting_l1: ['光照 L1', '姿态不变；日光 X +30°，相机 X +30', 32],
  lighting_l2: ['光照 L2', '姿态不变；日光 X −30°，相机 X −30', 32],
  stretch: ['影子拉伸', '姿态不变；日光 Y = 60°，相机 Y = 75', 32]
};
let scene, presets, generationDefaults, revision = 0, previewRevision = -1;
let confirmedRevision = -1, confirmedJob = null, previewBusy = false, previewPending = false;
let previewTimer, activePreviewJob = null, generationJob = null, confirming = false, generationBusy = false;

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `请求失败 (${response.status})`);
  return value;
}
function error(message) { $('global-error').textContent = message || ''; $('global-error').hidden = !message; }
function badge(text, style = '') { $('preview-badge').textContent = text; $('preview-badge').className = `badge ${style}`; }
function pause(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
async function waitJob(id, progress) {
  while (true) {
    const job = await api(`/jobs/${id}`);
    if (progress) progress(job);
    if (job.status === 'succeeded') return job;
    if (job.status === 'failed') throw new Error(`${job.error || '渲染失败'}。日志：/jobs/${id}/files/render.log`);
    if (job.status === 'cancelled') throw new Error('任务已取消');
    await pause(500);
  }
}
function setAt(object, path, value) {
  const keys = path.split('.');
  for (const key of keys.slice(0, -1)) object = object[key] ??= {};
  object[keys.at(-1)] = value;
}
function at(object, path) { return path.split('.').reduce((o, k) => o?.[k], object); }
function vector(container, title, path, unit) {
  const group = document.createElement('div'); group.className = 'vector-group';
  const heading = document.createElement('div'); heading.className = 'vector-heading';
  const label = document.createElement('strong'); label.textContent = title;
  const hint = document.createElement('span'); hint.textContent = unit;
  heading.append(label, hint); group.append(heading);
  const axes = document.createElement('div'); axes.className = 'axes';
  for (const axis of 'xyz') {
    const wrap = document.createElement('label'); wrap.className = `axis ${axis}`;
    const name = document.createElement('span'); name.textContent = axis.toUpperCase();
    const input = document.createElement('input'); input.type = 'number'; input.step = 'any';
    input.value = Math.round((at(scene, `${path}.${axis}`) ?? 0) * 10000) / 10000;
    input.dataset.path = `${path}.${axis}`; input.required = true;
    input.setAttribute('aria-label', `${title} ${axis.toUpperCase()}`);
    input.addEventListener('input', () => {
      const number = input.valueAsNumber;
      if (Number.isFinite(number)) setAt(scene, input.dataset.path, number);
      changed();
    });
    wrap.append(name, input); axes.append(wrap);
  }
  group.append(axes); $(container).append(group);
}
function renderHand() {
  const hand = $('hand-picker').value, config = scene.hands[hand];
  $('hand-fields').replaceChildren(); $('finger-buttons').replaceChildren();
  $('hand-enabled').checked = config.enabled !== false;
  vector('hand-fields', '整体位置偏移', `hands.${hand}.translation`, '世界坐标 · 场景长度单位');
  vector('hand-fields', '整体旋转偏移', `hands.${hand}.rotation_degrees`, '世界轴 · 度');
  ['拇指', '食指', '中指', '无名指', '小指'].forEach((name, index) => {
    const button = document.createElement('button'); button.type = 'button';
    const bent = config.state[index] === 4;
    button.className = `finger-button ${bent ? 'bent' : ''}`;
    button.setAttribute('aria-label', `${name}：${bent ? '弯曲' : '伸直'}`);
    button.setAttribute('aria-pressed', String(bent));
    button.textContent = name;
    const small = document.createElement('small'); small.textContent = bent ? '弯曲' : '伸直';
    button.append(small); button.addEventListener('click', () => { config.state[index] = bent ? 0 : 4; renderHand(); changed(); });
    $('finger-buttons').append(button);
  });
}
function renderForm() {
  $('mode').value = scene.mode;
  $('hand-picker').querySelector('[value=right]').hidden = scene.mode === 'single';
  if (scene.mode === 'single') $('hand-picker').value = 'left';
  renderHand();
  $('camera-fields').replaceChildren(); $('light-fields').replaceChildren();
  vector('camera-fields', '相机位置', 'camera.position', '绝对世界坐标 · 场景长度单位');
  vector('camera-fields', '相机旋转', 'camera.rotation_degrees', '绝对 XYZ 欧拉角 · 度');
  vector('light-fields', '日光旋转', 'light.rotation_degrees', '绝对 XYZ 欧拉角 · 度');
  vector('light-fields', '日光位置', 'light.position', '仅改变光源对象位置，不改变投影');
  $('width').value = scene.render.resolution[0]; $('height').value = scene.render.resolution[1];
  $('samples').value = scene.render.samples;
  updateActiveHands();
}
function updateActiveHands() {
  const left = scene.hands.left?.enabled !== false;
  const right = scene.mode === 'multi' && scene.hands.right?.enabled !== false;
  for (const option of $('active-hands').options) {
    option.disabled = option.value === 'left' ? !left : option.value === 'right' ? !right : !(left && right);
  }
  if ($('active-hands').selectedOptions[0].disabled) {
    const first = [...$('active-hands').options].find(o => !o.disabled);
    $('active-hands').value = first?.value || 'left';
  }
  updateEstimate();
}
function syncButtons() {
  const fresh = previewRevision === revision;
  $('confirm-scene').disabled = !fresh || confirming;
  $('generate').disabled = confirmedRevision !== revision || !confirmedJob || generationBusy || !generationValid();
  $('generate-hint').textContent = confirmedRevision === revision ? '使用已确认的场景快照。生成期间可继续调整下一次实验。' : '请先确认第一阶段的场景。';
}
function changed() {
  revision++; confirmedJob = null; confirmedRevision = -1;
  $('scene-result').hidden = true; $('confirmation').textContent = '参数已修改，请重新预览并确认';
  badge('参数已修改'); syncButtons();
  clearTimeout(previewTimer);
  if ($('auto-preview').checked) previewTimer = setTimeout(updatePreview, 1000);
}
function currentConfig() {
  if (!$('scene-form').checkValidity()) throw new Error('请输入有效的场景参数，再更新预览。');
  const config = clone(scene); delete config.samples; delete config.save_scene;
  return config;
}
function previewResolution(resolution) {
  const gcd = (a,b) => b ? gcd(b,a%b) : a;
  const divisor = gcd(...resolution), ratio = resolution.map(v => v / divisor);
  const factor = Math.min(divisor, Math.max(Math.ceil(64 / Math.min(...ratio)), Math.floor(256 / Math.max(...ratio))));
  return ratio.map(v => v * factor);
}
async function updatePreview() {
  clearTimeout(previewTimer);
  if (previewBusy) { previewPending = true; return; }
  let config;
  try { config = currentConfig(); } catch (exc) { error(exc.message); return; }
  const requestedRevision = revision;
  config.render = {resolution: previewResolution(config.render.resolution), samples: 8};
  previewBusy = true; previewPending = false; error(''); badge('正在渲染');
  $('preview-overlay').hidden = false; $('preview-overlay-text').textContent = '正在渲染预览…';
  $('preview-message').textContent = 'Blender 正在生成真实影子预览，请稍候。';
  try {
    const job = await api('/jobs', {action: 'render', config}); activePreviewJob = job.id;
    await waitJob(job.id, state => { if (requestedRevision === revision) $('preview-overlay-text').textContent = state.status === 'queued' ? '等待前一个任务完成…' : '正在渲染预览…'; });
    if (requestedRevision !== revision) return;
    const url = `/jobs/${job.id}/files/image_00000.png`;
    await new Promise((resolve, reject) => { const image = new Image(); image.onload = resolve; image.onerror = () => reject(new Error('预览图片加载失败')); image.src = url; });
    if (requestedRevision !== revision) return;
    $('preview-image').src = url; $('preview-image').hidden = false; $('preview-placeholder').hidden = true;
    previewRevision = requestedRevision; badge('预览已更新', 'good');
    $('preview-message').textContent = `当前参数 · ${config.render.resolution.join(' × ')} 快速预览 · ${new Date().toLocaleTimeString('zh-CN')}`;
    $('confirmation').textContent = '构图满意后，确认并保存场景';
  } catch (exc) {
    if (requestedRevision === revision) { badge('预览失败', 'bad'); error(exc.message); $('preview-message').textContent = '请检查参数或渲染日志，再重试。'; }
  } finally {
    previewBusy = false; activePreviewJob = null; $('preview-overlay').hidden = true; syncButtons();
    if ((previewPending || requestedRevision !== revision) && $('auto-preview').checked) {
      previewPending = false; clearTimeout(previewTimer); previewTimer = setTimeout(updatePreview, 100);
    }
  }
}
function link(text, url, download = false) {
  const a = document.createElement('a'); a.textContent = text; a.href = url;
  if (download) a.download = ''; else { a.target = '_blank'; a.rel = 'noopener'; }
  return a;
}
async function confirmScene() {
  if (previewRevision !== revision) return;
  const requestedRevision = revision;
  let config;
  try { config = currentConfig(); } catch(exc) { return error(exc.message); }
  confirming = true; syncButtons(); error(''); $('confirmation').textContent = '正在保存场景…';
  try {
    const job = await api('/jobs', {action: 'configure', config});
    await waitJob(job.id);
    if (requestedRevision !== revision) { $('confirmation').textContent = '保存期间参数已改变，请重新确认'; return; }
    confirmedJob = job.id; confirmedRevision = revision;
    $('confirmation').textContent = '场景已确认，可以生成数据';
    $('scene-result').replaceChildren(link('下载已配置场景 .blend', `/jobs/${job.id}/files/scene_00000.blend`, true), link('查看配置记录', `/jobs/${job.id}/files/config.json`));
    $('scene-result').hidden = false;
  } catch(exc) { error(exc.message); $('confirmation').textContent = '保存失败，请重试'; }
  finally { confirming = false; syncButtons(); }
}
function renderRules() {
  for (const [name, [title, description, capacity]] of Object.entries(ruleInfo)) {
    const rule = generationDefaults.rules.find(r => r.type === name);
    const row = document.createElement('div'); row.className = 'rule-row'; row.dataset.rule = name;
    row.innerHTML = `<label class="rule-title"><input type="checkbox" class="rule-enabled" ${rule ? 'checked' : ''}><span><strong>${title}</strong><small>${description}</small></span></label><input class="rule-count" type="number" min="1" max="10000" step="1" aria-label="${title}生成数量" value="${rule && rule.pair_count !== 'all' ? rule.pair_count : capacity}"><label class="checkbox"><input type="checkbox" class="rule-all" ${!rule || rule.pair_count === 'all' ? 'checked' : ''}>全部</label>`;
    row.querySelector('.rule-count').disabled = row.querySelector('.rule-all').checked;
    row.addEventListener('input', () => { row.querySelector('.rule-count').disabled = row.querySelector('.rule-all').checked; updateEstimate(); });
    $('rule-rows').append(row);
  }
}
function readGeneration() {
  const active = $('active-hands').value;
  const rules = [...document.querySelectorAll('.rule-row')].filter(r => r.querySelector('.rule-enabled').checked).map(row => ({
    type: row.dataset.rule, pair_count: row.querySelector('.rule-all').checked ? 'all' : row.querySelector('.rule-count').valueAsNumber
  }));
  return {active_hands: active === 'both' ? ['left', 'right'] : [active], seed: $('seed').valueAsNumber, rules, render: {}, pair_layout: {gap: 24}};
}
function binomial(n, k) {
  if (k < 0 || k > n) return 0;
  k = Math.min(k, n - k); let value = 1;
  for (let i = 1; i <= k; i++) value = value * (n - k + i) / i;
  return Math.round(value);
}
function ruleCapacity(type, handCount) {
  const width = 5 * handCount;
  if (type === 'shift_one') return width;
  if (type === 'shift_two') return binomial(width, 2);
  if (type === 'count_preserve') {
    let total = 0;
    for (let k = 0; k <= width; k++) { const n = binomial(width, k); total += n * (n - 1); }
    return total;
  }
  return 1 << width;
}
function estimate() {
  const config = readGeneration(); let total = 0;
  if (!$('seed').checkValidity() || !Number.isInteger(config.seed)) throw new Error('随机种子需要是有效整数');
  if (!config.rules.length) throw new Error('请至少选择一条规则');
  if ($('active-hands').selectedOptions[0].disabled) throw new Error('请先启用一只手');
  for (const rule of config.rules) {
    const capacity = ruleCapacity(rule.type, config.active_hands.length);
    const count = rule.pair_count === 'all' ? capacity : rule.pair_count;
    if (!Number.isInteger(count) || count < 1 || count > capacity) throw new Error(`${ruleInfo[rule.type][0]}最多 ${capacity} 个独立对`);
    total += count;
  }
  if (total > 10000) throw new Error('单批最多 10000 对，请关闭“全部”并设置较小数量');
  return total;
}
function generationValid() { try { estimate(); return true; } catch { return false; } }
function updateEstimate() {
  try { $('pair-estimate').textContent = `预计生成 ${estimate().toLocaleString('zh-CN')} 对`; }
  catch(exc) { $('pair-estimate').textContent = exc.message; }
  syncButtons();
}
async function generate() {
  if (!confirmedJob || confirmedRevision !== revision || generationBusy) return;
  const sceneJob = confirmedJob, config = readGeneration();
  try { estimate(); } catch(exc) { return error(exc.message); }
  generationBusy = true; syncButtons(); error('');
  $('generation-progress').hidden = false; $('generation-result').hidden = true;
  $('pair-gallery').replaceChildren(); $('cancel-generation').hidden = false; $('progress-bar').value = 0;
  try {
    const job = await api('/jobs', {action: 'pairs', scene_job_id: sceneJob, config}); generationJob = job.id;
    const result = await waitJob(job.id, state => {
      $('progress-bar').max = state.total_images; $('progress-bar').value = state.completed_images;
      $('progress-message').textContent = state.status === 'queued' ? '任务已提交，等待渲染…' : `原图渲染 ${state.completed_images} / ${state.total_images}，完成后自动拼接输入输出对。`;
    });
    const index = await api(`/jobs/${job.id}/files/pairs.json`);
    $('progress-message').textContent = `已完成：${index.pair_count} 对，复用 ${result.total_images} 张原图。`;
    const box = $('generation-result'); box.replaceChildren();
    const heading = document.createElement('strong'); heading.textContent = `结果保存到：${result.output_directory}`;
    const note = document.createElement('p'); note.textContent = '每对图片左边为输入，右边为输出。下方展示前 6 对。';
    box.append(heading, note, link('下载配对索引 JSON', `/jobs/${job.id}/files/pairs.json`, true), link('查看渲染参数', `/jobs/${job.id}/files/render_manifest.json`)); box.hidden = false;
    for (const pair of index.pairs.slice(0, 6)) {
      const figure = document.createElement('figure'); const a = link('', `/jobs/${job.id}/files/${pair.pair_image}`);
      const image = document.createElement('img'); image.src = a.href; image.alt = `${ruleInfo[pair.rule][0]}输入输出对 ${pair.pair_id}`; a.append(image);
      const caption = document.createElement('figcaption'); caption.textContent = `${ruleInfo[pair.rule][0]} · ${pair.pair_id + 1}`;
      figure.append(a, caption); $('pair-gallery').append(figure);
    }
  } catch(exc) { error(exc.message); $('progress-message').textContent = exc.message; }
  finally { generationBusy = false; generationJob = null; $('cancel-generation').hidden = true; syncButtons(); }
}
function downloadJSON(value, name) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function bind() {
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-tab]').forEach(b => { const selected = b === button; b.classList.toggle('active', selected); b.setAttribute('aria-selected', String(selected)); $(`panel-${b.dataset.tab}`).hidden = !selected; });
  }));
  $('scene-form').addEventListener('submit', event => event.preventDefault());
  $('mode').addEventListener('change', () => { scene = clone(presets[$('mode').value]); renderForm(); changed(); });
  $('reset-scene').addEventListener('click', () => { scene = clone(presets[scene.mode]); renderForm(); changed(); });
  $('hand-picker').addEventListener('change', renderHand);
  $('hand-enabled').addEventListener('change', () => { scene.hands[$('hand-picker').value].enabled = $('hand-enabled').checked; updateActiveHands(); changed(); });
  for (const [id, state] of [['open-hand', 0], ['close-hand', 4]]) $(id).addEventListener('click', () => { scene.hands[$('hand-picker').value].state = Array(5).fill(state); renderHand(); changed(); });
  for (const id of ['width', 'height', 'samples']) $(id).addEventListener('input', () => {
    scene.render = {resolution: [$('width').valueAsNumber, $('height').valueAsNumber], samples: $('samples').valueAsNumber}; changed();
  });
  $('auto-preview').addEventListener('change', () => { if ($('auto-preview').checked && previewRevision !== revision) updatePreview(); else clearTimeout(previewTimer); });
  $('refresh-preview').addEventListener('click', updatePreview); $('confirm-scene').addEventListener('click', confirmScene);
  $('active-hands').addEventListener('change', updateEstimate); $('seed').addEventListener('input', updateEstimate);
  $('generate').addEventListener('click', generate);
  $('cancel-generation').addEventListener('click', async () => { if (generationJob) { try { await api(`/jobs/${generationJob}/cancel`, {}); } catch(exc) { error(exc.message); } } });
  $('export-scene').addEventListener('click', () => { try { downloadJSON(currentConfig(), 'scene_config.json'); } catch(exc) { error(exc.message); } });
  $('export-generation').addEventListener('click', () => { try { estimate(); downloadJSON(readGeneration(), 'generation_config.json'); } catch(exc) { error(exc.message); } });
  $('import-scene').addEventListener('click', () => $('scene-file').click());
  $('scene-file').addEventListener('change', async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      const config = JSON.parse(await file.text());
      const response = await api('/ui/validate-scene', {config});
      const merge = (a,b) => { const out = clone(a); for (const [k,v] of Object.entries(b)) out[k] = v && typeof v === 'object' && !Array.isArray(v) && out[k] && typeof out[k] === 'object' ? merge(out[k],v) : clone(v); return out; };
      scene = merge(presets[response.config.mode], response.config); delete scene.samples; delete scene.save_scene;
      renderForm(); changed(); error('');
    } catch(exc) { error(`导入失败：${exc.message}`); }
    event.target.value = '';
  });
}
async function main() {
  try {
    const data = await api('/ui/bootstrap'); presets = data.presets; scene = data.scene; generationDefaults = data.generation;
    renderRules(); bind(); renderForm(); $('seed').value = generationDefaults.seed;
    const initialHands = generationDefaults.active_hands || ['left']; $('active-hands').value = initialHands.length === 2 ? 'both' : initialHands[0];
    updateActiveHands(); $('connection').textContent = '本地 Blender 服务已连接 · Camera.001';
    await updatePreview();
  } catch(exc) { error(`初始化失败：${exc.message}`); $('connection').textContent = '服务连接失败'; }
}
main();
