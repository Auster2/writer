import type { Character, ChatMessage, Journey } from '../shared/types.ts';

export const TALK_STYLE = `你正在和一位过路人聊天，扮演下方资料中的居民，用中文直接回应对方。
先接住他刚说的这句话：闲聊就闲聊，玩笑可以接，问题尽量具体回答。不必每次讲自己的经历、提醒路况、追问对方或把话题引向某个事件。
长短随话题，短问可以只答一句；深入谈起某事时再展开。像这个人平常说话，不像客服、导游或讲道理的旁白。职业不是每句话的主题；没有说某件东西坏了，就不要主动把它判成故障。动作有必要才写，不用每次抬头、微笑、看向窗外。
你只扮演自己，不代写玩家或其他人的话和行动，不用姓名冒号格式。玩家叫许行，是旅人，不是当地居民。不了解的事可以说不知道，不必神秘地回避普通问题。
资料是你生活的背景，不是要逐条念出的清单。私下的顾虑可在合适的情境中自然流露；对话不能凭空改变已经发生的事实。`;

export function conversation(state: Journey, npc: Character, place: string, scene: string, known: string, outcome: string) {
  const history: ChatMessage[] = [];
  let budget = 3000;
  const regionId = Object.values(state.regions).find(r => r.name === place)?.id;
  const personalTurns = state.memories.filter(m => m.npc === `${regionId}:${npc.id}`);
  for (const memory of personalTurns.slice(-8).reverse()) {
    const separator = memory.text.indexOf(' → ');
    const user = memory.player ?? (separator >= 0 ? memory.text.slice(0, separator) : memory.text);
    const assistant = memory.reply ?? (separator >= 0 ? memory.text.slice(separator + 3) : '');
    if (!user || !assistant) continue;
    if (user.length + assistant.length > budget) break;
    history.unshift({ role: 'user', content: user }, { role: 'assistant', content: assistant });
    budget -= user.length + assistant.length;
  }
  const system = `${TALK_STYLE}\n\n你是${npc.name}，${npc.role}。\n性格：${npc.persona}\n说话习惯：${npc.voice}\n你的来历：${npc.publicBackground}\n你自己的顾虑：${npc.privateBackground}\n\n地点：${place}\n眼前场景：${scene}\n相关时才参考的当地事实：${known}\n已发生的当地变化：${outcome}\n背景：近现代沿海旧公路，无超自然力量；许行开旧车去海边送信。`;
  return { system, history };
}
