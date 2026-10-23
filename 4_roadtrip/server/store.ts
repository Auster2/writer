import { readFile, writeFile, rename, mkdir, copyFile } from 'node:fs/promises';
import path from 'node:path';
import type { Journey, Settings } from '../shared/types.ts';

export class Store {
  dir: string;
  constructor(dir: string) { this.dir = dir; }
  async read<T>(name: string): Promise<T | null> {
    const file = path.join(this.dir, name + '.json');
    try { return JSON.parse(await readFile(file, 'utf8')); }
    catch (error: any) {
      if (error.code === 'ENOENT') return null;
      try {
        const backup = await readFile(file + '.bak', 'utf8');
        const value = JSON.parse(backup);
        await writeFile(file + '.recover', backup, 'utf8');
        await rename(file + '.recover', file);
        return value;
      } catch { throw new Error(`${name} 存档无法读取，备份也无效；原文件已保留。`); }
    }
  }
  async write(name: string, value: unknown) {
    await mkdir(this.dir, { recursive: true });
    const file = path.join(this.dir, name + '.json');
    await writeFile(file + '.tmp', JSON.stringify(value, null, 2), 'utf8');
    try { await copyFile(file, file + '.bak'); } catch (e: any) { if (e.code !== 'ENOENT') throw e; }
    await rename(file + '.tmp', file);
  }
  journey() { return this.read<Journey>('journey'); }
  async settings(): Promise<Settings> {
    return (await this.read<Settings>('settings')) ?? {
      url: 'http://127.0.0.1:11434', model: 'qwen2.5:7b', mode: 'demo', context: 4096, timeout: 180
    };
  }
}

export function validateSettings(value: any): Settings {
  if (!value || !['demo', 'ollama'].includes(value.mode)) throw new Error('请选择离线示例或 Ollama 模式。');
  const url = new URL(String(value.url));
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || !['', '/'].includes(url.pathname)) throw new Error('模型地址应为 http(s)://主机:端口，不包含认证信息或路径。');
  if (typeof value.model !== 'string' || !value.model.trim() || value.model.length > 100) throw new Error('请填写模型名。');
  if (![4096, 8192, 16384].includes(Number(value.context))) throw new Error('上下文请选择 4096、8192 或 16384。');
  if (!Number.isInteger(Number(value.timeout)) || Number(value.timeout) < 15 || Number(value.timeout) > 600) throw new Error('超时应为15至600秒。');
  return { mode: value.mode, url: url.origin, model: value.model.trim(), context: Number(value.context), timeout: Number(value.timeout) };
}
