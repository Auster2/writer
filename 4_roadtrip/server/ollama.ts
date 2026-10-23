import type { Settings, Model, Emit } from '../shared/types.ts';

export class Ollama implements Model {
  settings: Settings;
  constructor(settings: Settings) { this.settings = settings; }
  async generate(system: string, input: unknown, json: boolean, signal: AbortSignal, emit: Emit) {
    const combined = AbortSignal.any([signal, AbortSignal.timeout(this.settings.timeout * 1000)]);
    emit({ type: 'status', text: '正在连接模型，首次加载可能较慢…' });
    const timer = setInterval(() => emit({ type: 'status', text: '模型仍在处理，正在等待响应…' }), 8000);
    try {
      const response = await fetch(this.settings.url + '/api/chat', {
        method: 'POST', signal: combined, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: this.settings.model, stream: true, think: false,
          ...(json ? { format: 'json' } : {}),
          messages: [{ role: 'system', content: system }, { role: 'user', content: JSON.stringify(input) }],
          options: { num_ctx: this.settings.context, num_predict: json ? 2300 : 600, temperature: json ? 0.35 : 0.75 } })
      });
      if (!response.ok || !response.body) throw new Error(`Ollama HTTP ${response.status}：${(await response.text()).slice(0, 180)}`);
      let buffer = '', text = '', done = false;
      const decoder = new TextDecoder();
      const accept = (line: string) => {
        if (!line.trim()) return;
        const item = JSON.parse(line);
        if (item.error) throw new Error(String(item.error));
        const chunk = item.message?.content || '';
        text += chunk;
        if (text.length > 18000) throw new Error('模型输出过长，请缩短回答或更换模型。');
        if (chunk) emit(json ? { type: 'status', text: `正在构建地区，已收到 ${text.length} 字…` } : { type: 'delta', text: chunk });
        if (item.done) {
          if (item.done_reason === 'length') throw new Error('输出达到上限，未保存；请重试或选择更适合结构化输出的模型。');
          done = true;
        }
      };
      for await (const chunk of response.body) {
        buffer += decoder.decode(chunk, { stream: true });
        let index;
        while ((index = buffer.indexOf('\n')) !== -1) {
          accept(buffer.slice(0, index)); buffer = buffer.slice(index + 1);
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) accept(buffer);
      if (!done || !text.trim()) throw new Error('模型响应不完整，世界状态未修改。');
      return text.trim();
    } catch (error: any) {
      if (combined.aborted) throw new Error(signal.aborted ? '已取消，未提交本次行动。' : '模型响应超时，未修改存档。可增大超时或使用较小模型。');
      throw new Error(`模型请求失败：${error.message}`);
    } finally { clearInterval(timer); }
  }
}

export async function testConnection(settings: Settings) {
  const signal = AbortSignal.timeout(10000);
  const response = await fetch(settings.url + '/api/tags', { signal });
  if (!response.ok) throw new Error(`连接失败：HTTP ${response.status}`);
  const data: any = await response.json();
  const models = (data.models || []).map((m: any) => String(m.name));
  let processors: any[] = [];
  try {
    const ps = await fetch(settings.url + '/api/ps', { signal });
    if (ps.ok) { const info: any = await ps.json(); processors = (info.models || []).map((m: any) => ({ name: m.name, size: m.size, sizeVram: m.size_vram })); }
  } catch { /* 旧版没有状态接口时，模型列表仍然可用。 */ }
  return { models, processors, selectedAvailable: models.includes(settings.model) || models.includes(settings.model + ':latest') };
}
