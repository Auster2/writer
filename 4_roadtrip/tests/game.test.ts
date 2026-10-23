import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import http from 'node:http';
import { Store, validateSettings } from '../server/store.ts';
import { Game, publicState } from '../server/game.ts';
import { Ollama, testConnection } from '../server/ollama.ts';
import { STOPS } from '../presets/world.ts';
import type { Action, Model, Settings } from '../shared/types.ts';

async function setup(t: any, factory?: (s: Settings) => Model) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'rain-road-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const store = new Store(dir); const game = new Game(store, factory);
  async function act(type: Action['type'], data: any = {}) {
    const current = await store.journey();
    return game.act({ type, requestId: randomUUID(), expectedVersion: current?.version ?? 0, ...data }, new AbortController().signal, () => {});
  }
  return { dir, store, game, act };
}

test('three stops: investigate, resolve, revisit, end and restore', async t => {
  const { store, act } = await setup(t);
  let state = await act('new');
  assert.equal(state?.region, 0);
  await act('talk', { target: 'mechanic', text: '去海边怎么走？' });
  await act('inspect', { target: 'bike' }); await act('inspect', { target: 'map' });
  state = await act('resolve'); assert.equal(state?.resolved, true);
  await act('travel', { target: 'echo' }); await act('inspect', { target: 'cards' }); await act('inspect', { target: 'schedule' }); await act('resolve');
  await act('travel', { target: 'mist' });
  assert.equal((await store.journey())?.resolved.includes('mist'), true);
  assert.match((await store.journey())!.entries.at(-1)!.text, /上次留下的改变/);
  await act('travel', { target: 'echo' }); await act('travel', { target: 'cape' });
  await act('inspect', { target: 'directory' }); await act('inspect', { target: 'letter' }); await act('resolve');
  state = await act('end'); assert.equal(state?.completed, true); assert.equal(state?.visitedCount, 3);
  assert.match(state!.entries.at(-1)!.text, /信已经交到/);
  assert.equal((await new Store(store.dir).journey())?.completed, true);
  await assert.rejects(act('talk', { target: 'keeper', text: '你好' }), /已经结束/);
});

test('unfinished local stories never lock travel or invent delivery', async t => {
  const { act } = await setup(t);
  await act('new'); await act('travel', { target: 'echo' }); await act('travel', { target: 'cape' });
  const state = await act('end');
  assert.equal(state?.completed, true); assert.match(state!.entries.at(-1)!.text, /没有把信交出去/);
});

test('action validation, stale writes and idempotent retries', async t => {
  const { game, store, act } = await setup(t);
  await act('new');
  await assert.rejects(act('resolve'), /先确认/);
  await assert.rejects(act('travel', { target: 'cape' }), /先沿/);
  await assert.rejects(act('talk', { target: 'keeper', text: '你好' }), /不在/);
  const action = { type: 'inspect', target: 'bike', requestId: randomUUID(), expectedVersion: 1 } as Action;
  const result = await game.act(action, new AbortController().signal, () => {});
  const duplicate = await game.act(action, new AbortController().signal, () => {});
  assert.equal(duplicate?.version, result?.version);
  await assert.rejects(act('inspect', { target: 'map', expectedVersion: 1 }), /已更新/);
  assert.equal((await store.journey())?.clues.length, 1);
});

test('public snapshots exclude secrets and personal conversation memory', async t => {
  const { store, act } = await setup(t);
  await act('new'); await act('talk', { target: 'mechanic', text: '只告诉你一句话' });
  const stored = (await store.journey())!;
  const snapshot = JSON.stringify(publicState(stored));
  assert.ok(stored.regions.mist.characters[0].privateBackground);
  assert.ok(!snapshot.includes('privateBackground'));
  assert.ok(!snapshot.includes(stored.regions.mist.characters[0].privateBackground));
  assert.ok(!Object.hasOwn(publicState(stored)!, 'memories'));
});

test('model region generation, speaker-only memory and revisits', async t => {
  const inputs: any[] = [];
  let generations = 0;
  const model: Model = { async generate(system, input: any, json) {
    inputs.push(input);
    if (json) {
      generations++;
      const stop = STOPS.find(s => s.name === input.region)!;
      return JSON.stringify({ name: stop.name, atmosphere: '一场细雨落在旧公路。', characters: stop.roles.map(c => ({ ...c, publicBackground: c.publicBackground + ' 喜欢修旧钟。' })) });
    }
    return '我记得你说过的话，但你还没有做出这个选择。';
  }};
  const { store, act } = await setup(t, () => model);
  await store.write('settings', { ...(await store.settings()), mode: 'ollama' });
  await act('new');
  await act('talk', { target: 'mechanic', text: '这是我私下告诉你的' });
  await act('talk', { target: 'rider', text: '你好' });
  assert.equal(inputs.at(-1).personalMemory.length, 0);
  assert.ok(!JSON.stringify(inputs.at(-1)).includes('这是我私下告诉你的'));
  await act('travel', { target: 'echo' }); await act('travel', { target: 'mist' });
  assert.equal(generations, 2);
  assert.match((await store.journey())!.regions.mist.characters[0].publicBackground, /旧钟/);
});

test('generation failure, cancellation, concurrent writes leave save unchanged', async t => {
  const { store, act, game } = await setup(t, () => ({ async generate() { throw new Error('offline'); } }));
  await act('new'); const before = JSON.stringify(await store.journey());
  await store.write('settings', { ...(await store.settings()), mode: 'ollama' });
  await assert.rejects(act('new'), /offline/);
  assert.equal(JSON.stringify(await store.journey()), before);
  await store.write('settings', { ...(await store.settings()), mode: 'demo' });
  const controller = new AbortController(); controller.abort();
  await assert.rejects(game.act({ type: 'inspect', target: 'bike', requestId: randomUUID(), expectedVersion: 1 }, controller.signal, () => {}));
  assert.equal(JSON.stringify(await store.journey()), before);
  game.busy = true;
  await assert.rejects(act('inspect', { target: 'bike' }), /已有行动/);
});

test('backup recovery and settings validation', async t => {
  const { store, dir } = await setup(t);
  await store.write('sample', { version: 1 }); await store.write('sample', { version: 2 });
  await writeFile(path.join(dir, 'sample.json'), '{bad');
  assert.deepEqual(await store.read('sample'), { version: 1 });
  assert.deepEqual(JSON.parse(await readFile(path.join(dir, 'sample.json'), 'utf8')), { version: 1 });
  assert.throws(() => validateSettings({ mode: 'demo', url: 'file:///etc/passwd' }), /地址/);
  const settings = await store.settings();
  assert.equal(validateSettings({ ...settings, url: 'http://172.30.234.17:11434/' }).url, 'http://172.30.234.17:11434');
});

test('real HTTP adapter parses fragmented NDJSON and tests model listing', async t => {
  const fake = http.createServer(async (req, res) => {
    if (req.url === '/api/tags') { res.end(JSON.stringify({ models: [{ name: 'test:latest' }] })); return; }
    if (req.url === '/api/ps') { res.end(JSON.stringify({ models: [] })); return; }
    let body = ''; for await (const chunk of req) body += chunk;
    const input = JSON.parse(body);
    assert.equal(input.stream, true); assert.equal(input.think, false);
    res.setHeader('Content-Type', 'application/x-ndjson');
    res.write('{"message":{"content":"你');
    res.write('好"},"done":false}\n');
    res.end('{"message":{"content":"，旅人。"},"done":true,"done_reason":"stop"}\n');
  });
  await new Promise<void>(resolve => fake.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise<void>(resolve => fake.close(() => resolve())));
  const address = fake.address() as any;
  const settings: Settings = { url: `http://127.0.0.1:${address.port}`, model: 'test', mode: 'ollama', context: 4096, timeout: 15 };
  const events: any[] = [];
  assert.equal(await new Ollama(settings).generate('role', {}, false, new AbortController().signal, e => events.push(e)), '你好，旅人。');
  assert.equal(events.filter(e => e.type === 'delta').length, 2);
  assert.equal((await testConnection(settings)).selectedAvailable, true);
});

test('script-style multiple-speaker answers are retried and never committed', async t => {
  let replies = 0;
  const model: Model = { async generate(_system, input: any, structured) {
    if (structured) { const stop = STOPS.find(s => s.name === input.region)!; return JSON.stringify({ name: stop.name, atmosphere: '雨中的修车铺。', characters: stop.roles }); }
    replies++;
    assert.equal(input.player.name, '许行');
    return replies === 1 ? '程禾：你好。\n许行：我会留下。' : '程禾放下扳手。“可以，先坐一会儿，雨一时半会儿停不了。”';
  }};
  const { store, act } = await setup(t, () => model);
  await store.write('settings', { ...(await store.settings()), mode: 'ollama' });
  await act('new'); await act('talk', { target: 'mechanic', text: '可以歇一会儿吗？' });
  assert.equal(replies, 2);
  const save = (await store.journey())!;
  assert.ok(!JSON.stringify(save.entries).includes('我会留下'));
  assert.match(save.entries.at(-1)!.text, /先坐一会儿/);
});
