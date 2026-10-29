const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
let state: any = null;
let settings: any = null;
let defaultWorld = '';
let busy = false;
let inputMode = 'talk';
let selectedNpc = '';
let viewIndex: number | null = null;
let controller: AbortController | null = null;

function text(id: string, value: string) { $(id).textContent = value; }
function error(message = '') { text('error', message); $('error').hidden = !message; }
function button(label: string, callback: () => void, className = 'action-button') {
  const b = document.createElement('button'); b.type = 'button'; b.className = className; b.textContent = label; b.disabled = busy;
  b.onclick = callback; return b;
}
function empty(container: HTMLElement, hint: string) { const p = document.createElement('p'); p.className = 'muted'; p.textContent = hint; container.append(p); }
function viewedRegion() { return state?.completed ? (viewIndex ?? state.region) : state?.region; }
function currentRegion() { return state?.regions[state.routes[viewedRegion()].id]; }
function usingMock() { return settings?.model === 'mock-road' || settings?.model === 'mock-road:latest'; }
function render() {
  const ai = (state?.mode ?? settings?.mode) === 'ollama';
  text('mode-label', ai ? (usingMock() ? '本地模拟 · 规则生成' : 'Ollama · AI 生成') : '离线示例 · 非 AI');
  text('welcome-mode', settings?.mode === 'ollama'
    ? (usingMock() ? '当前连接本机模拟接口 mock-road。地区、人物和对话按故事规则生成，用来在没有 Ollama 时走完整条旅程。' : `当前使用 ${settings.model}。地区氛围、人物和对话由模型生成；第一次连接可能稍慢。`)
    : '当前为离线示例：无需模型即可体验三站；自由对话由示例规则回应。没有 Ollama 时，可运行 npm run mock，再在设置里连接。');
  text('route-count', `${String(state?.visitedCount || 0).padStart(2, '0')} / 03`);
  const routes = $('routes'); routes.replaceChildren();
  const routeInfo = state?.routes || [{ name: '雾桥驿', subtitle: '河谷 · 姐妹与修车铺' }, { name: '回声坡', subtitle: '山路 · 最后一场广播' }, { name: '海角镇', subtitle: '海边 · 迟到的信' }];
  for (const [index, route] of routeInfo.entries()) {
    const b = button('', () => {
      if (!state) return;
      if (state.completed && route.visited) { viewIndex = index; render(); return; }
      if (index === state.region) return;
      if (confirm(`前往${route.name}？你可以暂时放下未完成的事，之后再回来。`)) act('travel', { target: route.id });
    }, 'route-card' + (viewedRegion() === index ? ' active' : ''));
    const number = document.createElement('span'); number.className = 'route-number'; number.textContent = String(index + 1).padStart(2, '0');
    const name = document.createElement('strong'); name.textContent = route.name;
    const subtitle = document.createElement('small'); subtitle.textContent = route.visited ? '已抵达 · 可以回访' : route.subtitle;
    b.append(number, name, subtitle);
    b.disabled = busy || !state || (state.completed ? !route.visited : index === state.region || (!route.visited && index > state.region + 1));
    routes.append(b);
  }
  $('welcome').hidden = !!state; $('timeline').replaceChildren();
  $('action-panel').hidden = !state || state.completed;
  $('chat-form').hidden = !state || state.completed;
  $('ending').hidden = !state?.completed;
  text('save-status', state ? `✓ 已保存 · 第 ${state.version} 次记录` : '尚未出发');
  text('day-label', state ? `第 ${String(state.day).padStart(2, '0')} 天` : '启程之前');
  text('weather-label', state ? state.routes[viewedRegion()].weather : '雨季 · 沿海旧路');
  text('chapter-label', state ? `CHAPTER ${String(viewedRegion() + 1).padStart(2, '0')}` : 'PROLOGUE');
  text('place-title', state ? currentRegion().name : '出发之前');
  text('chapter-status', state?.completed ? '旅途已收束' : state?.resolved ? '这一站，有了回应' : '三站，一段旅程');
  if (state) {
    for (const entry of state.entries) {
      if (entry.region !== state.routes[viewedRegion()].id) continue;
      const article = document.createElement('article'); article.className = `entry ${entry.kind}`;
      const meta = document.createElement('div'); meta.className = 'entry-meta';
      const label = document.createElement('span'); label.textContent = entry.speaker;
      const day = document.createElement('i'); day.textContent = `DAY ${String(entry.day).padStart(2, '0')}`;
      meta.append(label, day);
      const p = document.createElement('p'); p.textContent = entry.text; article.append(meta, p); $('timeline').append(article);
    }
    const npcs = currentRegion().characters;
    if (!npcs.some((npc: any) => npc.id === selectedNpc)) selectedNpc = npcs[0].id;
    const select = $<HTMLSelectElement>('npc-select'); select.replaceChildren();
    for (const npc of npcs) { const option = document.createElement('option'); option.value = npc.id; option.textContent = npc.name; select.append(option); }
    select.value = selectedNpc; select.disabled = busy;
    const actions = $('actions'); actions.replaceChildren();
    if (state.region < 2) actions.append(button(`继续上路 → ${state.routes[state.region + 1].name}`, () => {
      if (confirm('继续上路？未完成的事情会保留，你也可以回来。')) act('travel', { target: state.routes[state.region + 1].id });
    }));
    else actions.append(button('在海边，结束这段旅程 ↗', () => { if (confirm(state.resolved ? '把这段旅程写成尾声？' : '信还没有送出，也要结束旅程吗？尾声会如实记录。')) act('end'); }));
    text('input-context', state.mode === 'demo' ? '离线示例只验证流程；要测试自然对话，请在设置里启用 Ollama 并新建旅程。' : usingMock() ? '正在使用本地模拟接口。可以闲聊，也可以描述行动。' : `正在使用 ${settings.model} · 可以闲聊，不必追着事件走。`);
    $<HTMLSelectElement>('input-mode').value = inputMode;
    $<HTMLSelectElement>('input-mode').disabled = busy;
    $('talk-target').hidden = inputMode !== 'talk';
    $<HTMLTextAreaElement>('message').placeholder = inputMode === 'talk' ? '想说什么，直接说就好…' : '描述你想做的事，例如：我看看墙上贴着什么。';
    $<HTMLTextAreaElement>('message').disabled = busy;
    $<HTMLButtonElement>('send-button').disabled = busy;
  }
  const people = $('people'); people.replaceChildren();
  const npcs = state ? currentRegion().characters : [];
  text('npc-count', String(npcs.length).padStart(2, '0'));
  for (const npc of npcs) {
    const card = document.createElement('div'); card.className = 'person-card';
    const avatar = document.createElement('span'); avatar.className = 'person-icon'; avatar.textContent = npc.name[0];
    const content = document.createElement('div'); const name = document.createElement('strong'); name.textContent = npc.name;
    const role = document.createElement('small'); role.textContent = npc.role;
    const info = document.createElement('p'); info.textContent = npc.publicBackground;
    content.append(name, role, info); card.append(avatar, content); people.append(card);
  }
  if (!npcs.length) empty(people, '上路之后，慢慢认识。');
  $('clues').replaceChildren();
  for (const clue of state?.clues || []) {
    const p = document.createElement('p'); p.className = 'clue'; p.textContent = clue.fact;
    const small = document.createElement('small'); small.textContent = clue.place + ' · 已确认'; p.append(small); $('clues').append(p);
  }
  if (!state?.clues.length) empty($('clues'), '留意物件，也留意别人的话。');
  $('notes').replaceChildren();
  for (const note of state?.notes || []) { const p = document.createElement('p'); p.className = 'journal-note'; p.textContent = note; $('notes').append(p); }
  if (!state?.notes.length) empty($('notes'), '此刻，还是一张白纸。');
  text('world-text', state?.world || defaultWorld);
  for (const id of ['new-button', 'start-button', 'settings-button', 'settings-top']) $<HTMLButtonElement>(id).disabled = busy;
}
async function api(url: string, value?: unknown) {
  const response = await fetch(url, value === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
  const data = await response.json(); if (!response.ok) throw new Error(data.error || '请求失败'); return data;
}
async function refresh() {
  const data = await api('/api/state'); state = data.state; settings = data.settings; defaultWorld = data.world; render();
}
async function act(type: string, input: any = {}) {
  if (busy) return;
  busy = true; error(); $('draft').hidden = true; text('draft-text', ''); $('status-bar').hidden = false; text('status-text', '正在准备…');
  controller = new AbortController(); render();
  let committed = false;
  try {
    const response = await fetch('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
      body: JSON.stringify({ ...input, type, requestId: crypto.randomUUID(), expectedVersion: state?.version || 0 }) });
    if (!response.ok) { const data = await response.json(); throw new Error(data.error || '行动失败'); }
    if (!response.body) throw new Error('浏览器不支持流式响应。');
    let buffer = ''; const decoder = new TextDecoder();
    const accept = (line: string) => {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.type === 'error') throw new Error(event.message);
      if (event.type === 'status') text('status-text', event.text);
      if (event.type === 'resetDraft') { text('draft-text', ''); $('draft').hidden = true; }
      if (event.type === 'delta') { $('draft').hidden = false; text('draft-text', $('draft-text').textContent + event.text); }
      if (event.type === 'state') { state = event.state; viewIndex = null; committed = true; }
    };
    const reader = response.body.getReader();
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index; while ((index = buffer.indexOf('\n')) !== -1) { accept(buffer.slice(0, index)); buffer = buffer.slice(index + 1); }
    }
    buffer += decoder.decode(); if (buffer.trim()) accept(buffer);
    if (!committed) throw new Error('连接结束但没有收到保存确认，请刷新确认进度。');
    if (type === 'talk' || type === 'explore') $<HTMLTextAreaElement>('message').value = '';
  } catch (e: any) {
    controller?.abort();
    error(e.name === 'AbortError' ? '已取消。未完成的内容不会计入旅程；正在同步最后保存的进度。' : e.message);
    // 若取消发生在保存完成之后，重新读取权威状态，而非假定回滚。
    try { await refresh(); } catch { /* 保留最近有效界面。 */ }
  } finally {
    busy = false; controller = null; $('status-bar').hidden = true; $('draft').hidden = true; render();
    if (committed) $('action-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}
function openSettings() {
  $<HTMLInputElement>('setting-url').value = settings.url;
  $<HTMLInputElement>('setting-model').value = settings.model;
  $<HTMLSelectElement>('setting-mode').value = settings.mode;
  $<HTMLSelectElement>('setting-context').value = settings.context;
  $<HTMLInputElement>('setting-timeout').value = settings.timeout;
  text('connection-result', ''); $<HTMLDialogElement>('settings-dialog').showModal();
}
function formSettings() { return { url: $<HTMLInputElement>('setting-url').value, model: $<HTMLInputElement>('setting-model').value, mode: $<HTMLSelectElement>('setting-mode').value,
  context: Number($<HTMLSelectElement>('setting-context').value), timeout: Number($<HTMLInputElement>('setting-timeout').value) }; }
$('settings-button').onclick = openSettings;
$('settings-top').onclick = openSettings;
$('world-button').onclick = () => $<HTMLDialogElement>('world-dialog').showModal();
$('world-top').onclick = () => $<HTMLDialogElement>('world-dialog').showModal();
$('new-button').onclick = () => $<HTMLDialogElement>('new-dialog').showModal();
$('start-button').onclick = () => act('new');
$('new-form').onsubmit = e => { e.preventDefault(); const world = $<HTMLTextAreaElement>('world-extra').value; $<HTMLDialogElement>('new-dialog').close(); act('new', { world }); };
$('input-mode').onchange = () => { inputMode = $<HTMLSelectElement>('input-mode').value; render(); $<HTMLTextAreaElement>('message').focus(); };
$('cancel-button').onclick = () => controller?.abort();
$('npc-select').onchange = () => { selectedNpc = $<HTMLSelectElement>('npc-select').value; };
$('chat-form').onsubmit = e => { e.preventDefault(); const value = $<HTMLTextAreaElement>('message').value.trim(); if (value) act(inputMode, { target: selectedNpc, text: value }); };
$('message').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $<HTMLFormElement>('chat-form').requestSubmit(); } };
$('settings-form').onsubmit = async e => {
  e.preventDefault();
  try { const result = await api('/api/settings', formSettings()); settings = result.settings; $<HTMLDialogElement>('settings-dialog').close(); render(); }
  catch (e: any) { text('connection-result', e.message); }
};
$('test-button').onclick = async () => {
  const b = $<HTMLButtonElement>('test-button'); b.disabled = true; text('connection-result', '正在直连 Ollama，最多等待10秒…');
  try {
    const result = await api('/api/test', formSettings());
    $('model-list').replaceChildren();
    for (const model of result.models) { const option = document.createElement('option'); option.value = model; $('model-list').append(option); }
    const loaded = result.processors.map((m: any) => `${m.name}：模型占用 ${(m.size / 1024 ** 3).toFixed(1)}GB，其中显存 ${(m.sizeVram / 1024 ** 3).toFixed(1)}GB`).join('\n');
    text('connection-result', `连接成功 · ${result.models.length} 个模型\n${result.selectedAvailable ? '已找到所选模型。' : '未找到所选模型，可从模型输入框下拉选择。'}\n${loaded || '当前没有已加载的模型；此测试不启动推理。'}`);
  } catch (e: any) { text('connection-result', `连接失败：${e.message}\n检查服务监听地址、端口与防火墙。`); }
  finally { b.disabled = false; }
};
for (const b of document.querySelectorAll<HTMLButtonElement>('[data-close]')) b.onclick = () => $<HTMLDialogElement>(b.dataset.close!).close();
refresh().catch(e => error('无法读取本地服务：' + e.message));
