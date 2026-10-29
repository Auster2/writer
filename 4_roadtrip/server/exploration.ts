import type { Emit, Model, Settings } from '../shared/types.ts';

type ObjectInfo = { id: string; name: string; description: string; clue: string };
export type Exploration = { kind: 'observe' | 'intervene' | 'other'; objectIds: string[]; response: string };
const SYSTEM = `你是文字冒险的行动解释器，玩家会自由描述想做什么。根据当前地点解释动作，不替玩家作其他决定。
只输出JSON：{"kind":"observe或intervene或other","objectIds":["物件ID"],"response":"一两句中文反馈"}。
observe：玩家明确想看、检查、询查物件，填写实际涉及的ID；泛指看看周围可包含所有可见物件。只说自己已经知道某事不等于完成调查。
intervene：玩家明确想实施提供的localEvent所描述的介入；不要把换袜子、修自己的车、普通聊天等都当作解决当地事件。
other：其他小动作、无法理解或当前不支持的事，只回应直接可见的结果，不宣称新增证据、物品或解决了事件。
所有ID必须来自objects。response不能泄露未调查的物件内容、隐藏人物背景或声称任务成功；观察和介入的实际结果由程序核实与保存。`;
export async function exploration(text: string, objects: readonly ObjectInfo[], localEvent: string, settings: Settings,
  model: Model, signal: AbortSignal, emit: Emit): Promise<Exploration> {
  if (settings.mode === 'demo') {
    if (/看|观察|调查|检查|翻|核对/.test(text)) return { kind: 'observe', objectIds: objects.map(o => o.id), response: '' };
    if (/交给|递给|一起谈|邀请|留言|送信|商量|谈谈|帮她|帮他/.test(text)) return { kind: 'intervene', objectIds: [], response: '' };
    return { kind: 'other', objectIds: [], response: '离线示例不能理解任意行动。可以描述观察周围，或在设置中启用 Ollama 体验自由输入。' };
  }
  const raw = await model.generate(SYSTEM, { playerAction: text, objects: objects.map(o => ({ id: o.id, name: o.name })), localEvent }, true, signal, emit);
  const result = JSON.parse(raw);
  if (!['observe', 'intervene', 'other'].includes(result.kind) || !Array.isArray(result.objectIds) ||
      result.objectIds.length > objects.length || result.objectIds.some((id: unknown) => !objects.some(o => o.id === id)) ||
      typeof result.response !== 'string' || result.response.length > 600) throw new Error('行动识别结果无效，尚未改变世界，请换种说法。');
  if (result.kind === 'observe' && !result.objectIds.length) return { kind: 'other', objectIds: [], response: result.response || '你想仔细看什么？可以描述眼前的物件。' };
  return { ...result, objectIds: [...new Set<string>(result.objectIds)] };
}
