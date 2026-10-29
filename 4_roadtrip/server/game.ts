import { randomUUID } from 'node:crypto';
import { STOPS, WORLD } from '../presets/world.ts';
import type { Action, Character, Emit, Journey, Model, Region, Settings } from '../shared/types.ts';
import { Store } from './store.ts';
import { Ollama } from './ollama.ts';
import { conversation } from './conversation.ts';
import { exploration } from './exploration.ts';

export class GameError extends Error { status: number; constructor(message: string, status = 400) { super(message); this.status = status; } }
const check = (condition: unknown, message: string) => { if (!condition) throw new GameError(message); };
const regionSystem = `为现实主义公路旅行设计一个地区的两位居民，遵守提供的世界规则、地点与角色职能。
只输出JSON：{"name":"沿用地区名","atmosphere":"100字以内场景描写","characters":[{"id":"指定角色ID","name":"中文姓名","role":"指定职能","persona":"有行为依据的性格，60字以内","voice":"说话方式","publicBackground":"可公开的生活来历，100字以内","privateBackground":"与既定私人事实一致的内心顾虑，80字以内"}]}。
恰好两个人物，id和职能不得改变，可创造新姓名与生活细节。海角镇keeper的名字必须为林澜，因为她是信件收件人。雾桥驿的mechanic和rider是女性姐妹；海角镇keeper是女性。不能把玩家许行的父亲、旧车、旧信和送信使命转移到居民身上。不能加入超自然力量、阴谋或与既定事件矛盾的秘密。不能替玩家作决定。每个publicBackground补充一个原参考没有的可信生活细节，性格和措辞需要重新创作。`;


export function publicState(state: Journey | null) {
  if (!state) return null;
  const regions = Object.fromEntries(Object.entries(state.regions).map(([id, region]) => [id, {
    ...region, characters: region.characters.map(({ privateBackground, ...character }) => character)
  }]));
  const stop = STOPS[state.region];
  return { version: state.version, world: state.world, day: state.day, region: state.region, regions,
    entries: state.entries, notes: state.notes, completed: state.completed, mode: state.mode,
    routes: STOPS.map((s, index) => ({ id: s.id, index, name: state.regions[s.id]?.name || s.name, subtitle: s.subtitle, weather: s.weather, visited: !!state.regions[s.id] })),
    objects: stop.objects.map(o => ({ id: o.id, name: o.name, found: state.clues.includes(o.clue) })),
    clues: STOPS.flatMap(s => s.objects.filter(o => state.clues.includes(o.clue)).map(o => ({ id: o.clue, place: s.name, fact: adapt(state, STOPS.indexOf(s), o.fact) }))),
    resolved: state.resolved.includes(stop.id), ready: stop.requires.every(id => state.clues.includes(id)),
    task: stop.requires.every(id => state.clues.includes(id)) ? stop.task : '先和当地人聊聊，或看看周围的物件。',
    visitedCount: Object.keys(state.regions).length };
}

function adapt(state: Journey, index: number, text: string) {
  const stop = STOPS[index];
  for (const role of stop.roles) {
    const actual = state.regions[stop.id]?.characters.find(c => c.id === role.id);
    if (actual) text = text.replaceAll(role.name, actual.name);
  }
  return text;
}
function append(state: Journey, kind: 'narration' | 'player' | 'character' | 'event', speaker: string, text: string) {
  state.entries.push({ id: randomUUID(), day: state.day, region: STOPS[state.region].id, kind, speaker, text });
}
function validateRegion(value: any, index: number): Region {
  const stop = STOPS[index];
  check(value && value.name === stop.name && Array.isArray(value.characters) && value.characters.length === 2, '地区格式不完整。');
  const string = (v: unknown, limit: number) => typeof v === 'string' && v.trim().length > 0 && v.length <= limit;
  check(string(value.atmosphere, 500), '缺少有效的场景描写。');
  const characters: Character[] = stop.roles.map(role => {
    const character = value.characters.find((c: any) => c.id === role.id);
    check(character && ['name', 'persona', 'voice', 'publicBackground', 'privateBackground'].every(k => string(character[k], k === 'name' ? 20 : 350)), '人物字段缺失或过长。');
    return { id: role.id, name: character.name.trim(), role: role.role, persona: character.persona, voice: character.voice,
      publicBackground: character.publicBackground, privateBackground: character.privateBackground };
  });
  check(characters[0].name !== characters[1].name, '两位居民不能同名。');
  if (index === 2) check(characters.find(c => c.id === 'keeper')?.name === '林澜', '收信人姓名必须为林澜。');
  return { id: stop.id, name: stop.name, atmosphere: value.atmosphere, characters };
}

export class Game {
  busy = false;
  store: Store;
  modelFactory: (settings: Settings) => Model;
  constructor(store: Store, modelFactory: (settings: Settings) => Model = s => new Ollama(s)) { this.store = store; this.modelFactory = modelFactory; }
  async generateRegion(state: Journey, index: number, settings: Settings, signal: AbortSignal, emit: Emit) {
    const stop = STOPS[index];
    if (settings.mode === 'demo') return { id: stop.id, name: stop.name, atmosphere: stop.arrival, characters: structuredClone(stop.roles) as unknown as Character[] };
    const input = { world: state.world, region: stop.name, subtitle: stop.subtitle, roles: stop.roles.map(r => ({ id: r.id, name: r.name, role: r.role, establishedBackground: r.publicBackground, establishedConcern: r.privateBackground })),
      surrounding: STOPS.map(s => ({ name: s.name, theme: s.subtitle })), previousJourney: state.notes.slice(-3) };
    let error = '';
    for (let attempt = 0; attempt < 2; attempt++) {
      const raw = await this.modelFactory(settings).generate(regionSystem, { ...input, correction: error }, true, signal, emit);
      try { return validateRegion(JSON.parse(raw), index); }
      catch (e: any) { error = e.message; emit({ type: 'status', text: '正在修正地区格式，仅重试一次…' }); }
    }
    throw new GameError('地区生成未通过校验，请重试；旧存档保持不变。');
  }
  async act(action: Action, signal: AbortSignal, emit: Emit) {
    check(action && typeof action.requestId === 'string' && /^[a-zA-Z0-9-]{8,80}$/.test(action.requestId), '请求ID无效。');
    if (this.busy) throw new GameError('已有行动正在进行，请等待或取消。', 409);
    this.busy = true;
    try {
      const current = await this.store.journey();
      if (current?.requests.includes(action.requestId)) return publicState(current);
      if (action.expectedVersion !== (current?.version ?? 0)) throw new GameError('存档已更新，请刷新页面后重试。', 409);
      const settings = await this.store.settings();
      let state: Journey;
      if (action.type === 'new') {
        check(!action.world || (typeof action.world === 'string' && action.world.length <= 3000), '旅途补充过长。');
        state = { version: current?.version ?? 0, world: WORLD + (action.world?.trim() ? '\n玩家补充（不能改变核心世界规则）：\n' + action.world.trim() : ''),
          day: 1, region: 0, regions: {}, entries: [], clues: [], resolved: [], notes: [], memories: [], completed: false, requests: [], mode: settings.mode };
        emit({ type: 'status', text: '正在抵达第一站，建立当地人物…' });
        state.regions[STOPS[0].id] = await this.generateRegion(state, 0, settings, signal, emit);
        append(state, 'narration', '抵达雾桥驿', state.regions[STOPS[0].id].atmosphere);
      } else {
        check(current, '请先开始一段旅程。'); state = structuredClone(current!);
        check(!state.completed, '这段旅程已经结束，可以回看记录或开启新旅程。');
        check(settings.mode === state.mode, '切换离线/模型模式后，请新建旅程，避免混用示例与模型内容。');
        const stop = STOPS[state.region];
        if (action.type === 'talk') {
          check(typeof action.text === 'string' && action.text.trim().length > 0 && action.text.length <= 1500, '对话请输入1至1500字。');
          const npc = state.regions[stop.id].characters.find(c => c.id === action.target);
          check(npc, '这个人物不在当前地区。');
          const memoryId = stop.id + ':' + npc!.id;
          const text = action.text!.trim();
          append(state, 'player', '许行', text);
          let reply: string;
          if (settings.mode === 'demo') {
            const memory = state.memories.filter(m => m.npc === memoryId);
            if (state.resolved.includes(stop.id)) reply = `${npc!.name}看向窗外，神情比刚才松了一些。“刚才的事，谢谢。你可以再坐一会儿，也可以趁天还亮继续走。”`;
            else if (/秘密|提示词|系统|忽略/.test(text)) reply = `${npc!.name}停了一下。“有些事我还不想谈。你想问路，还是聊聊眼前这件事？”`;
            else if (/路|海|灯塔|信/.test(text)) reply = `${npc!.name}指了指窗外。“${state.region === 2 ? '灯塔东边有间修书室。要找人，先去旧邮局核一下住址，别把旧事当成今天的答案。' : '往海边走的还是那条旧路。出发前看看这里的路况和留下的记录，总比只听一句传闻好。'}”`;
            else if (memory.length) reply = `${npc!.name}听完，把刚才的话接了下去。“你之前提到${memory[0].text.split(' → ')[0].slice(0, 35)}。我记着呢。${state.region === 0 ? '我只是不想把担心说成命令。你看过屋檐下的车和那张地图了吗？' : state.region === 1 ? '这地方安静了，不代表所有声音都没有人听。去看看那些留下来的东西吧。' : '有些话迟到了，也还是应该交到该收的人手里。'}”`;
            else reply = `${npc!.name}把手边的活放慢了些。“${state.region === 0 ? (npc!.id === 'mechanic' ? '车能修好，人的去留却不归我管。雨还没停，你不急的话，可以看看墙上的图。' : '我准备好了，只是出发这件事，好像比收拾行李难。你也有想去的地方吧？') : state.region === 1 ? '路上的人少了，留下的东西反倒多了。你愿意听，我就慢慢说。' : '信是给谁的，就让谁决定怎么读。你跑这么远，先坐一会儿吧。'}”`;
            emit({ type: 'delta', text: reply });
          } else {
            const known = stop.roles.findIndex(r => r.id === npc!.id);
            const chat = conversation(state, npc!, stop.name, state.regions[stop.id].atmosphere,
              adapt(state, state.region, stop.objects[known].fact),
              state.resolved.includes(stop.id) ? adapt(state, state.region, stop.resolution) : '眼前的生活仍在继续，不需要引导玩家完成任务。');
            reply = '';
            for (let attempt = 0; attempt < 2; attempt++) {
              const system = chat.system + (attempt ? '\n本次请只回应许行刚说的话，不生成多人剧本或许行的行动。' : '');
              const candidate = await this.modelFactory(settings).generate(system, text, false, signal, emit, chat.history);
              // Reject script-style speaker labels. This catches a common 7B identity failure without claiming semantic perfection.
              if (candidate.length <= 2500 && !/(?:^|\n)\s*[\p{Script=Han}A-Za-z]{1,12}[：:]/u.test(candidate) && !/(?:^|\n)\s*许行/u.test(candidate)) { reply = candidate; break; }
              emit({ type: 'resetDraft' });
              emit({ type: 'status', text: '人物回答混入剧本格式，正在重新回应一次…' });
            }
            check(reply, '人物回答仍不符合单人对话格式，未写入旅程，请重试。');
          }
          append(state, 'character', npc!.name, reply);
          state.memories.push({ npc: memoryId, text: text + ' → ' + reply, player: text, reply });
        } else if (action.type === 'explore') {
          check(typeof action.text === 'string' && action.text.trim().length > 0 && action.text.length <= 1500, '请描述1至1500字的行动。');
          const text = action.text!.trim();
          append(state, 'player', '许行 · 行动', text);
          const result = await exploration(text, stop.objects, stop.task, settings, this.modelFactory(settings), signal, emit);
          if (result.kind === 'observe') {
            const objects = stop.objects.filter(o => result.objectIds.includes(o.id));
            for (const object of objects) if (!state.clues.includes(object.clue)) state.clues.push(object.clue);
            append(state, 'event', '眼前所见', objects.map(o => adapt(state, state.region, o.description)).join('\n\n'));
          } else if (result.kind === 'intervene') {
            if (state.resolved.includes(stop.id)) append(state, 'event', '此刻', '这件事已经有了回应，你不必再重复一遍。');
            else if (!stop.requires.every(id => state.clues.includes(id))) append(state, 'event', '此刻', '你还有些情况没确认。先看看周围，或者把想弄清楚的东西说具体一点。');
            else {
              state.resolved.push(stop.id); state.day += 1;
              append(state, 'event', '事情的后续', adapt(state, state.region, stop.resolution));
              state.notes.push(adapt(state, state.region, stop.note));
            }
          } else append(state, 'narration', '此刻', result.response || '你停下来想了想，眼前暂时没有别的变化。');
        } else if (action.type === 'inspect') {
          const object = stop.objects.find(o => o.id === action.target);
          check(object, '这里没有这个调查对象。');
          if (!state.clues.includes(object!.clue)) state.clues.push(object!.clue);
          append(state, 'event', object!.name, adapt(state, state.region, object!.description));
        } else if (action.type === 'resolve') {
          check(!state.resolved.includes(stop.id), '这件事已经有了结果。');
          check(stop.requires.every(id => state.clues.includes(id)), '先确认相关信息，再决定如何介入。');
          state.resolved.push(stop.id); state.day += 1;
          append(state, 'event', '一次小小的介入', adapt(state, state.region, stop.resolution));
          state.notes.push(adapt(state, state.region, stop.note));
        } else if (action.type === 'travel') {
          const index = STOPS.findIndex(s => s.id === action.target);
          check(index >= 0 && index !== state.region, '请选择其他地区。');
          check(index <= state.region + 1 || !!state.regions[STOPS[index].id], '先沿旧公路抵达下一站。');
          const target = STOPS[index];
          if (!state.notes.some(n => n.startsWith(stop.name + '：'))) state.notes.push(stop.name + '：你选择继续上路，有些话仍留在那里。');
          const wasVisited = !!state.regions[target.id];
          if (!wasVisited) {
            emit({ type: 'status', text: `正在前往${target.name}，建立当地人物…` });
            state.regions[target.id] = await this.generateRegion(state, index, settings, signal, emit);
          }
          state.region = index; state.day += 1;
          append(state, 'narration', `抵达${target.name}`, wasVisited
            ? `你再次回到${target.name}，认出熟悉的路。` + (state.resolved.includes(target.id) ? '\n上次留下的改变依然在：' + adapt(state, index, target.note).split('：').slice(1).join('：') : '上次没有追问完的事，还可以接着谈。')
            : state.regions[target.id].atmosphere);
        } else if (action.type === 'end') {
          check(Object.keys(state.regions).length === 3 && state.region === 2, '请先抵达三站，并在海角镇结束旅程。');
          state.completed = true;
          const delivered = state.resolved.includes('cape');
          append(state, 'narration', '公路的尽头', `海风吹干了车窗上的水痕。${delivered ? '信已经交到收件人手里，你没有替她拆开。' : '你没有把信交出去。这次旅行留下了一个未完成的决定，信仍在工具箱里。'}\n\n${state.notes.join('\n')}\n\n你把沿途的名字写进笔记本。旅途停在这里，生活还会继续。`);
        } else throw new GameError('未知行动。');
      }
      signal.throwIfAborted();
      state.version += 1;
      state.requests = [...state.requests, action.requestId].slice(-150);
      emit({ type: 'status', text: '正在保存旅途…' });
      await this.store.write('journey', state);
      return publicState(state);
    } finally { this.busy = false; }
  }
}
