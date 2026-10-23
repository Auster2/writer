export type Settings = { url: string; model: string; mode: 'demo' | 'ollama'; context: number; timeout: number };
export type Character = { id: string; name: string; role: string; persona: string; voice: string; publicBackground: string; privateBackground: string };
export type Region = { id: string; name: string; atmosphere: string; characters: Character[] };
export type Entry = { id: string; day: number; region: string; kind: 'narration' | 'player' | 'character' | 'event'; speaker: string; text: string };
export type Memory = { npc: string; text: string };
export type Journey = {
  version: number; world: string; region: number; day: number; regions: Record<string, Region>;
  entries: Entry[]; clues: string[]; resolved: string[]; notes: string[];
  memories: Memory[]; completed: boolean; requests: string[]; mode: Settings['mode'];
};
export type Action = { type: 'new' | 'talk' | 'inspect' | 'resolve' | 'travel' | 'end'; target?: string; text?: string; world?: string; requestId: string; expectedVersion: number };
export type Emit = (event: { type: string; [key: string]: unknown }) => void;
export type Model = { generate(system: string, input: unknown, json: boolean, signal: AbortSignal, emit: Emit): Promise<string> };
