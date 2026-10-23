// Optional real-model acceptance check. Writes only to ignored data/live-check-*.
import { Game } from '../server/game.ts';
import { Store } from '../server/store.ts';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const url = process.env.ROADTRIP_OLLAMA_URL;
if (!url) throw new Error('Set ROADTRIP_OLLAMA_URL to your Ollama URL.');
const dir = fileURLToPath(new URL('../data/live-check-' + Date.now(), import.meta.url));
const store = new Store(dir);
await store.write('settings', { url, model: process.env.ROADTRIP_MODEL || 'qwen2.5:7b', mode: 'ollama', context: 4096, timeout: 240 });
const game = new Game(store);
async function act(type: any, data: any = {}) {
  const current = await store.journey();
  let last = 0;
  const started = Date.now();
  const state = await game.act({ type, requestId: randomUUID(), expectedVersion: current?.version ?? 0, ...data }, new AbortController().signal, e => {
    if (e.type === 'status' && Date.now() - last > 8000) { console.log(type, e.text); last = Date.now(); }
  });
  console.log(JSON.stringify({ action: type, seconds: ((Date.now() - started) / 1000).toFixed(1), region: state?.region, version: state?.version, completed: state?.completed }));
  return state;
}
console.log('Live acceptance output:', path.basename(dir));
let state = await act('new');
await act('talk', { target: state!.regions.mist.characters[0].id, text: '你好，我想沿旧路去海边，可以先在这里歇一会儿吗？' });
await act('inspect', { target: 'bike' }); await act('inspect', { target: 'map' }); await act('resolve');
await act('travel', { target: 'echo' }); await act('inspect', { target: 'cards' }); await act('inspect', { target: 'schedule' }); await act('resolve');
await act('travel', { target: 'cape' }); await act('inspect', { target: 'directory' }); await act('inspect', { target: 'letter' }); await act('resolve');
state = await act('end');
if (!state?.completed || state.visitedCount !== 3) throw new Error('Three-stop acceptance failed.');
console.log('LIVE THREE-STOP CHECK PASSED');
