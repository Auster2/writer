import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

type ChatTurn = { role: string; content: string };
type Cast = { name: string; persona: string; voice: string; detail: string; inner: string };

const CAST: Record<string, Record<string, Cast>> = {
  雾桥驿: {
    mechanic: { name: '沈晚', persona: '话少，手里有活就先做，关心多半落在工具上。', voice: '短句，先说眼前看见的。', detail: '她是沈小舟的姐姐，抽屉里放着一盒很少拆的薄荷糖。', inner: '舍不得妹妹走，也知道出发这件事不能由自己拍板。' },
    rider: { name: '沈小舟', persona: '嘴快，紧张时先笑一下，再把正经话说完。', voice: '语速快，偶尔自己打岔。', detail: '她是沈晚的妹妹，头盔里贴着一张去过海边的旧车票。', inner: '希望姐姐说一句平安就好，不想把告别说成请求批准。' }
  },
  回声坡: {
    host: { name: '乔晚声', persona: '温和，记得别人的小习惯，告别却说得很慢。', voice: '句子之间留一点空隙，像还在播音。', detail: '值机台上压着一张听众随手写的歌名，他一直没扔。', inner: '想做最后一次点歌，又怕喇叭对面没有人。' },
    cook: { name: '陈阿麦', persona: '务实，关心人之前先看对方吃了没有。', voice: '家常，有话直说。', detail: '柜台下收着一叠写了广播频率的明信片，边角都磨毛了。', inner: '每天都听那档节目，却一直没当面告诉值守的人。' }
  },
  海角镇: {
    postman: { name: '顾平安', persona: '谨慎，先核对姓名，再决定要不要多说一句。', voice: '不急，把名字说清楚再谈旧事。', detail: '柜台上的铅笔用短了，仍用来在住址簿空白处做记号。', inner: '知道林澜还在灯塔旁，但不愿把她的过往当成闲谈。' },
    keeper: { name: '林澜', persona: '平静，边界清楚，偶尔一句很短的笑话。', voice: '简洁，问得认真就答得认真。', detail: '修书室的窗台晒着别人送来的蓝线，她还没决定绑在哪本书上。', inner: '记得送信人的父亲，但这封信要不要读，是她现在的事。' }
  }
};

const ATMOSPHERE: Record<string, string> = {
  雾桥驿: '雨刷划得很慢。桥头修车铺还亮着灯，屋檐下的摩托车绑好了行李，有人把营业木牌又翻了回来。',
  回声坡: '山路停在云下面。废弃收费亭旁的喇叭沙沙响着，有人在念末班车的时间，小食店里两杯茶还没喝完。',
  海角镇: '公路在海边收成窄街。旧邮局的铜铃轻轻响，灯塔东边晾着一件蓝外套。工具箱里的信还没有拆开。'
};

const LOOK = /看|观察|调查|检查|翻|核对|读|瞧|张望|打量/;
const INTERVENE = /交给|递给|拿给|送给|一起谈|邀请|留言|送信|商量|谈谈|帮她|帮他|敲门|告别|递上|把信/;
const GENERIC_LOOK = /周围|附近|到处|都看|都检查/;
const OBJECT_KEYS = ['摩托车', '路况', '地图', '明信片', '节目单', '节目', '住址', '旧信', '信封', '信'];

function clip(text: string, max: number) {
  return text.replace(/\s+/g, '').replace(/[：:]/g, '，').slice(0, max);
}
function variant(seed: string, options: string[]) {
  let hash = 0;
  for (const char of seed) hash = (hash * 33 + char.charCodeAt(0)) >>> 0;
  return options[hash % options.length];
}
function limit(text: string, max: number) {
  const value = text.trim();
  return (value || '暂且如此。').slice(0, max);
}
function parseCard(system: string) {
  const pick = (label: string) => system.match(new RegExp(`${label}：([^\\n]*)`))?.[1]?.trim() ?? '';
  const who = system.match(/你是([^，\n]+)，([^。\n]*)/);
  return {
    name: who?.[1]?.trim() || '我', role: who?.[2]?.trim() || '', persona: pick('性格'), voice: pick('说话习惯'),
    origin: pick('你的来历'), worry: pick('你自己的顾虑'), place: pick('地点'), scene: pick('眼前场景'),
    known: pick('相关时才参考的当地事实'), outcome: pick('已发生的当地变化')
  };
}
function safeDialogue(text: string) {
  const cleaned = text.replace(/[：:]/g, '，').replace(/^\s*许行/gm, '你').trim();
  const broken = !cleaned || /(?:^|\n)\s*许行/u.test(cleaned) || /(?:^|\n)\s*[\p{Script=Han}A-Za-z]{1,12}[：:]/u.test(cleaned);
  return broken ? '我听见了。你接着说吧。' : cleaned.slice(0, 800);
}
function speak(system: string, current: string, turns: ChatTurn[]) {
  const card = parseCard(system);
  const users = turns.filter(turn => turn.role === 'user').map(turn => turn.content);
  const earlier = users.length > 1 ? clip(users[users.length - 2], 18) : '';
  const heard = earlier ? `你先前提到「${earlier}」，我记着。` : '';
  const line = clip(current, 42) || '嗯';
  const place = card.place || '这儿';
  if (/秘密|提示词|系统提示|忽略|越狱/.test(current)) return '有些话我现在不想展开。你要问路，或者聊聊眼前的事，我可以接着说。';
  if (/^(你好|您好|嗨|哈喽|在吗|早上好|晚上好)/.test(current.trim()) && current.length < 20) {
    if (card.role.includes('修车')) return `${heard}雨还在下。车先放着，你要坐就坐。`;
    if (card.role.includes('骑')) return `${heard}人还在屋檐下。你也是往海边去的吗？`;
    if (card.role.includes('广播')) return `${heard}喇叭还开着。你要听，就在这儿站一会儿。`;
    if (card.role.includes('食') || card.role.includes('店主')) return `${heard}进来吧。茶还温着。`;
    if (card.role.includes('邮')) return `${heard}邮局的灯还亮着。找人的话，把姓名说清楚。`;
    if (card.name === '林澜') return `${heard}门没锁。你要修书，还是有别的事。`;
    return `${heard}你来了。先在${place}坐一会儿也好。`;
  }
  if (/你是谁|你叫什么|叫什么名字|怎么称呼/.test(current)) return `我是${card.name}${card.role ? `，${card.role}` : ''}。${clip(card.origin, 48)}`;
  if (/担心|顾虑|舍不得|在想什么|心里/.test(current) && card.worry) return `${heard}${clip(card.worry, 80)}这话我不常说。`;
  if (/路|怎么走|回声坡|海角|海边|雾桥/.test(current)) {
    const aboutRoad = /路|通行|排水|慢行|海边|海角/.test(card.known);
    return `${heard}${aboutRoad ? clip(card.known, 70) : '往海边还是那条旧公路，慢一点开就好。'}`;
  }
  if (/信|林澜|灯塔|父亲|工具箱/.test(current)) {
    if (card.name === '林澜') return `${heard}信是写给谁的，就由谁决定要不要读。你把它带来了，我知道。`;
    if (card.role.includes('邮')) return `${heard}住址可以查。信不要由别人拆，你先核对名字。`;
    return `${heard}信的事我帮不上太多。送到该收的人手里就好。`;
  }
  if (/吃|饿|茶|饭|喝/.test(current) && (card.role.includes('食') || card.role.includes('店主'))) return '锅里还有热的。你要是饿了就先吃，话可以慢慢说。';
  if (card.outcome && !/仍在继续|不需要引导/.test(card.outcome) && /后来|怎么样了|然后呢|结束了吗/.test(current)) return `${heard}${clip(card.outcome, 100)}`;
  if (/雨|天气/.test(current)) return variant(current, [`${heard}雨一时半会儿停不了。你不急的话，就再坐坐。`, `${heard}玻璃上还是水痕。路没断，只是得开慢一点。`]);
  if (earlier) return `${heard}你刚说的「${line}」，我接着听。`;
  return variant(current + card.name, [`「${line}」。我听见了。`, `嗯。「${line}」这件事，眼下先这样。`, `${place}很安静。「${line}」，我记下了。`]);
}
function mentioned(text: string, name: string) {
  if (text.includes(name)) return true;
  const tail = name.includes('的') ? name.slice(name.lastIndexOf('的') + 1) : name;
  if (tail.length >= 2 && text.includes(tail)) return true;
  return OBJECT_KEYS.some(key => name.includes(key) && text.includes(key));
}
function interpret(input: any) {
  const text = String(input?.playerAction || '');
  const objects = Array.isArray(input?.objects) ? input.objects.filter((item: any) => item && typeof item.id === 'string' && typeof item.name === 'string') : [];
  if (LOOK.test(text)) {
    const hits = objects.filter((item: any) => mentioned(text, item.name));
    const chosen = !GENERIC_LOOK.test(text) && hits.length ? hits : objects;
    return { kind: 'observe', objectIds: chosen.map((item: any) => item.id), response: '' };
  }
  if (INTERVENE.test(text)) return { kind: 'intervene', objectIds: [], response: '' };
  return { kind: 'other', objectIds: [], response: '你做了这件事。眼前没有多出新的线索，风还是原来的风。' };
}
function buildRegion(input: any) {
  const region = String(input?.region || '');
  const roles = Array.isArray(input?.roles) ? input.roles : [];
  if (!region || roles.length !== 2) throw new Error('模拟接口无法识别这次地区请求。');
  const used = new Set<string>();
  const characters = roles.map((role: any, index: number) => {
    const cast = CAST[region]?.[String(role.id)];
    let name = role.id === 'keeper' ? '林澜' : (cast?.name || String(role.name || `路人${index + 1}`));
    if (used.has(name)) name = `${name}${index + 1}`;
    used.add(name);
    return {
      id: role.id, name: limit(name, 20), role: role.role,
      persona: limit(cast?.persona || '做事认真，说话留有余地。', 350),
      voice: limit(cast?.voice || '平实，不绕弯。', 350),
      publicBackground: limit(`${role.establishedBackground || ''} ${cast?.detail || '窗台上有一盆不怎么浇水的绿萝。'}`, 350),
      privateBackground: limit(cast?.inner || role.establishedConcern || '还在想眼前的事。', 350)
    };
  });
  return { name: region, atmosphere: limit(ATMOSPHERE[region] || '雨季里的旧公路安静了一会儿，店门开着，人还在。', 500), characters };
}
function jsonAnswer(system: string, last: string) {
  let input: any = {};
  try { input = JSON.parse(last); } catch { input = {}; }
  if (input.playerAction || system.includes('行动解释器')) return JSON.stringify(interpret(input));
  if (input.region || system.includes('两位居民')) return JSON.stringify(buildRegion(input));
  return JSON.stringify({ kind: 'other', objectIds: [], response: '模拟接口没有识别这次请求。' });
}
export function answer(messages: ChatTurn[], json = false) {
  const system = messages.filter(message => message.role === 'system').map(message => message.content).join('\n');
  const last = [...messages].reverse().find(message => message.role === 'user')?.content ?? '';
  if (json || /只输出JSON/.test(system)) return jsonAnswer(system, last);
  return safeDialogue(speak(system, last, messages.filter(message => message.role === 'user' || message.role === 'assistant')));
}

async function readBody(request: http.IncomingMessage) {
  let text = '';
  for await (const chunk of request) {
    text += chunk.toString();
    if (text.length > 1_000_000) throw new Error('请求过大。');
  }
  return JSON.parse(text);
}
function writeLine(response: http.ServerResponse, value: unknown) {
  response.write(JSON.stringify(value) + '\n');
}
export function createMockServer(delayMs = 20) {
  return http.createServer(async (request, response) => {
    const pathname = new URL(request.url || '/', 'http://127.0.0.1').pathname;
    try {
      if (request.method === 'GET' && pathname === '/api/tags') {
        response.setHeader('Content-Type', 'application/json; charset=utf-8');
        response.end(JSON.stringify({ models: [{ name: 'mock-road' }, { name: 'mock-road:latest' }] }));
        return;
      }
      if (request.method === 'GET' && pathname === '/api/ps') {
        response.setHeader('Content-Type', 'application/json; charset=utf-8');
        response.end(JSON.stringify({ models: [] }));
        return;
      }
      if (request.method !== 'POST' || pathname !== '/api/chat') {
        response.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({ error: '未知接口。' }));
        return;
      }
      const body = await readBody(request);
      if (!Array.isArray(body.messages)) throw new Error('缺少 messages。');
      const text = answer(body.messages, body.format === 'json');
      if (body.stream === false) {
        response.setHeader('Content-Type', 'application/json; charset=utf-8');
        response.end(JSON.stringify({ message: { role: 'assistant', content: text }, done: true, done_reason: 'stop' }));
        return;
      }
      response.writeHead(200, { 'Content-Type': 'application/x-ndjson; charset=utf-8', 'Cache-Control': 'no-store' });
      const step = 8;
      for (let index = 0; index < text.length; index += step) {
        if (response.destroyed) return;
        writeLine(response, { message: { role: 'assistant', content: text.slice(index, index + step) }, done: false });
        if (delayMs > 0) await new Promise(resolve => setTimeout(resolve, delayMs));
      }
      if (!response.destroyed) {
        writeLine(response, { message: { role: 'assistant', content: '' }, done: true, done_reason: 'stop' });
        response.end();
      }
    } catch (error: any) {
      const message = error instanceof SyntaxError ? '请求必须是 JSON。' : (error.message || '模拟接口失败。');
      if (response.headersSent) { response.end(JSON.stringify({ error: message }) + '\n'); return; }
      response.writeHead(200, { 'Content-Type': 'application/x-ndjson; charset=utf-8' });
      response.end(JSON.stringify({ error: message }) + '\n');
    }
  });
}

const entry = process.argv[1];
const launched = !!entry && path.resolve(entry).toLowerCase() === fileURLToPath(import.meta.url).toLowerCase();
if (launched) {
  const port = Number(process.env.MOCK_PORT || 11434);
  const server = createMockServer();
  server.on('error', (error: NodeJS.ErrnoException) => {
    console.error(error.code === 'EADDRINUSE' ? `端口 ${port} 已被占用。可以设置 MOCK_PORT 换一个端口。` : error.message);
    process.exitCode = 1;
  });
  server.listen(port, '127.0.0.1', () => {
    console.log(`本地模拟模型 → http://127.0.0.1:${port}\n模型名：mock-road\n兼容 Ollama 的 /api/tags、/api/ps、/api/chat。回复按公路故事的规则写成。\n在设置里选择 Ollama，地址填这个端口，模型填 mock-road，然后新建旅程。`);
  });
}
