import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { stripTypeScriptTypes } from 'node:module';
import { Store, validateSettings } from './store.ts';
import { Game, GameError, publicState } from './game.ts';
import { testConnection } from './ollama.ts';
import { WORLD } from '../presets/world.ts';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const store = new Store(process.env.ROADTRIP_DATA_DIR || path.join(root, 'data'));
const game = new Game(store);
const port = Number(process.env.PORT || 4317);
function json(response: http.ServerResponse, value: unknown, status = 200) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  response.end(JSON.stringify(value));
}
async function body(request: http.IncomingMessage) {
  let text = '';
  for await (const chunk of request) {
    text += chunk.toString();
    if (text.length > 20000) throw new GameError('请求过大。');
  }
  try { return JSON.parse(text); } catch { throw new GameError('请求必须是JSON。'); }
}
export const server = http.createServer(async (request, response) => {
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.setHeader('Referrer-Policy', 'no-referrer');
  response.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'");
  const pathname = new URL(request.url || '/', 'http://localhost').pathname;
  try {
    if (request.method === 'POST') {
      const origin = request.headers.origin;
      if (origin && new URL(origin).host !== request.headers.host) throw new GameError('拒绝跨站写入请求。', 403);
      if (!request.headers['content-type']?.includes('application/json')) throw new GameError('请使用JSON请求。', 415);
    }
    if (request.method === 'GET' && pathname === '/api/state') return json(response, { state: publicState(await store.journey()), settings: await store.settings(), world: WORLD });
    if (request.method === 'POST' && pathname === '/api/settings') {
      if (game.busy) throw new GameError('行动完成或取消后再修改设置。', 409);
      const settings = validateSettings(await body(request));
      await store.write('settings', settings); return json(response, { settings });
    }
    if (request.method === 'POST' && pathname === '/api/test') {
      const settings = validateSettings(await body(request));
      return json(response, await testConnection(settings));
    }
    if (request.method === 'POST' && pathname === '/api/action') {
      const action = await body(request);
      if (game.busy) throw new GameError('已有行动正在进行，请稍候。', 409);
      const controller = new AbortController();
      response.on('close', () => { if (!response.writableEnded) controller.abort(); });
      response.writeHead(200, { 'Content-Type': 'application/x-ndjson; charset=utf-8', 'Cache-Control': 'no-store' });
      response.flushHeaders();
      const emit = (event: any) => { if (!response.destroyed) response.write(JSON.stringify(event) + '\n'); };
      try { emit({ type: 'state', state: await game.act(action, controller.signal, emit) }); }
      catch (error: any) { emit({ type: 'error', message: error.message }); }
      response.end(); return;
    }
    const files: Record<string, [string, string]> = {
      '/': ['index.html', 'text/html'], '/style.css': ['style.css', 'text/css'], '/app.js': ['app.ts', 'text/javascript']
    };
    if (request.method === 'GET' && files[pathname]) {
      const [file, mime] = files[pathname];
      let text = await readFile(path.join(root, 'client', file), 'utf8');
      if (file.endsWith('.ts')) text = stripTypeScriptTypes(text);
      response.writeHead(200, { 'Content-Type': mime + '; charset=utf-8', 'Cache-Control': 'no-cache' });
      response.end(text); return;
    }
    json(response, { error: '页面不存在。' }, 404);
  } catch (error: any) {
    json(response, { error: error.message || '请求失败。' }, error.status || 400);
  }
});
server.listen(port, '127.0.0.1', () => console.log(`雨季旧公路 → http://127.0.0.1:${port}\n存档：${store.dir}\n关闭终端停止服务；存档在下次启动时恢复。`));
