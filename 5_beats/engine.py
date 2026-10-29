"""五拍实验：先改账本，再写正文。标准库即可运行。"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import config

BASE = Path(__file__).resolve().parent
KINDS = ('relationship', 'resource', 'clock', 'flag', 'knowledge')
PROPOSE_SYSTEM = '''你是剧情编辑。根据当前账本提出下一拍，只发生一件不可撤回的变化。
换地点、重复吐槽、再商量一次，都不算变化。不能新增人物。
不能使用行动者还不知道的秘密。资源不能变成负数。同一项不能再次变成已经提交过的值。
资源的 before 和 after 用数字。知情变化的 before 必须是“不知道”，after 必须是“知道”，并写 who。
只输出JSON：
{"actor":"在场人物","action":"这一拍具体做了什么","present":["在场人物"],
"uses":["用到的秘密id，没有则空数组"],
"effect":{"kind":"relationship或resource或clock或flag或knowledge","id":"账本id","before":"当前值","after":"新值","who":"仅knowledge需要"},
"anchor":"正文必须原样出现的短句，2至20字"}。'''
WRITE_SYSTEM = '''你是小说作者。把已经确定的这一拍写成约300至500字。
第三人称有限视角，视角人物是这一拍的actor。对白可以用我和你。
正文必须原样包含这一拍的anchor，不能改字。
不要写这一拍以外的新变化，不要新角色，不要羞辱失落的人。
如有修改意见，只重写这一拍的正文。只输出正文，不输出标题或JSON。'''


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_text(path, text):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(text, encoding='utf-8')
    os.replace(temp, path)


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def load_cast(path=None):
    cast = read_json(path or BASE / 'cast.json')
    require(nonempty(cast.get('title')) and nonempty(cast.get('opening')), '人物卡缺少标题或开场')
    require(isinstance(cast.get('characters'), list) and cast['characters'], '人物卡缺少人物')
    names = [c['name'] for c in cast['characters']]
    require(len(names) == len(set(names)) and all(nonempty(n) for n in names), '人物姓名无效')
    for key in ('secrets', 'relationships', 'resources', 'clocks', 'flags', 'rules'):
        require(isinstance(cast.get(key), list), f'人物卡缺少{key}')
    return cast


def initial_state(cast):
    names = {c['name'] for c in cast['characters']}
    knowledge = {}
    for secret in cast['secrets']:
        require(secret['owner'] in names, '秘密的主人不在人物里')
        require(all(person in names for person in secret['known_by']), '知道秘密的人不在人物里')
        knowledge[secret['id']] = list(secret['known_by'])
    return {
        'version': 1, 'title': cast['title'], 'rules': list(cast['rules']), 'opening': cast['opening'],
        'characters': cast['characters'], 'secrets': cast['secrets'],
        'ledger': {
            'relationships': [dict(item) for item in cast['relationships']],
            'resources': [dict(item) for item in cast['resources']],
            'clocks': [dict(item) for item in cast['clocks']],
            'flags': [dict(item) for item in cast['flags']],
            'knowledge': knowledge,
        },
        'committed': [], 'accepted': [], 'status': 'writing',
    }


def _find(items, item_id):
    return next((item for item in items if item['id'] == item_id), None)


def _as_int(value):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError('资源必须是整数')
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        return int(value.strip())
    raise ValueError('资源必须是整数')


def signature(effect):
    who = effect.get('who') or ''
    return f"{effect['kind']}|{effect['id']}|{who}|{effect['after']}"


def normalize_beat(beat):
    require(isinstance(beat, dict), '节拍必须是对象')
    require(nonempty(beat.get('actor')) and nonempty(beat.get('action')), '缺少行动者或行动')
    present = beat.get('present')
    require(isinstance(present, list) and present and all(nonempty(x) for x in present), 'present必须是非空的人名数组')
    uses = beat.get('uses', [])
    require(isinstance(uses, list) and all(isinstance(x, str) for x in uses), 'uses必须是字符串数组')
    anchor = beat.get('anchor')
    require(isinstance(anchor, str) and 2 <= len(anchor.strip()) <= 40 and '\n' not in anchor, 'anchor须为2至40字且不含换行')
    effect = beat.get('effect')
    require(isinstance(effect, dict) and effect.get('kind') in KINDS, 'effect.kind无效')
    require(isinstance(effect.get('id'), str) and effect['id'].strip(), '缺少账本id')
    kind = effect['kind']
    if kind == 'knowledge':
        require(effect.get('before') == '不知道' and effect.get('after') == '知道', '知情变化只能从不知道变为知道')
        require(nonempty(effect.get('who')), 'knowledge必须写who')
        after = '知道'
        before = '不知道'
        who = effect['who'].strip()
    elif kind == 'resource':
        before = _as_int(effect.get('before'))
        after = _as_int(effect.get('after'))
        who = ''
        require(not effect.get('who'), '只有知情变化才写who')
    else:
        require(nonempty(effect.get('before')) and nonempty(effect.get('after')), '缺少变化前后的值')
        require(not effect.get('who'), '只有知情变化才写who')
        before = str(effect['before']).strip()
        after = str(effect['after']).strip()
        who = ''
    return {
        'actor': beat['actor'].strip(), 'action': beat['action'].strip(), 'present': [x.strip() for x in present],
        'uses': [x.strip() for x in uses], 'anchor': anchor.strip(),
        'effect': {'kind': kind, 'id': effect['id'].strip(), 'before': before, 'after': after, 'who': who},
    }


def knows(ledger, secret_id, person):
    return person in ledger['knowledge'].get(secret_id, [])


def validate_beat(beat, state):
    """返回拒绝原因；通过时返回空字符串。不修改账本。"""
    try:
        beat = normalize_beat(beat)
    except ValueError as exc:
        return str(exc)
    names = {c['name'] for c in state['characters']}
    secret_ids = {s['id'] for s in state['secrets']}
    ledger = state['ledger']
    effect = beat['effect']
    if beat['actor'] not in names or any(person not in names for person in beat['present']):
        return '不能新增人物。'
    if beat['actor'] not in beat['present']:
        return '行动者不在场。'
    for secret_id in beat['uses']:
        if secret_id not in secret_ids:
            return '用到了不存在的秘密。'
        if not knows(ledger, secret_id, beat['actor']):
            return '行动者还不知道这个秘密。'
    kind, item_id = effect['kind'], effect['id']
    if kind == 'relationship':
        item = _find(ledger['relationships'], item_id)
        current = None if item is None else item['status']
    elif kind == 'resource':
        item = _find(ledger['resources'], item_id)
        current = None if item is None else item['value']
    elif kind == 'clock':
        item = _find(ledger['clocks'], item_id)
        current = None if item is None else item['value']
    elif kind == 'flag':
        item = _find(ledger['flags'], item_id)
        current = None if item is None else item['value']
    else:
        if item_id not in secret_ids:
            return '没有这个秘密。'
        if not knows(ledger, item_id, beat['actor']):
            return '行动者还不知道这个秘密。'
        if effect['who'] not in beat['present']:
            return '得知的人不在场。'
        current = '知道' if knows(ledger, item_id, effect['who']) else '不知道'
        item = True
    if item is None:
        return '账本里没有这一项。'
    if effect['before'] != current:
        return '变化前的值与账本不符，已经完成的事不能再完成一次。'
    if effect['after'] == effect['before']:
        return '前后没有变化。'
    if kind == 'resource' and effect['after'] < 0:
        return '资源不足。'
    if signature(effect) in state['committed']:
        return '这项变化已经提交过。'
    return ''


def apply_beat(state, beat):
    beat = normalize_beat(beat)
    reason = validate_beat(beat, state)
    require(not reason, reason or '节拍不成立')
    ledger = json.loads(json.dumps(state['ledger']))
    effect = beat['effect']
    if effect['kind'] == 'relationship':
        _find(ledger['relationships'], effect['id'])['status'] = effect['after']
    elif effect['kind'] == 'resource':
        _find(ledger['resources'], effect['id'])['value'] = effect['after']
    elif effect['kind'] == 'clock':
        _find(ledger['clocks'], effect['id'])['value'] = effect['after']
    elif effect['kind'] == 'flag':
        _find(ledger['flags'], effect['id'])['value'] = effect['after']
    else:
        ledger['knowledge'][effect['id']].append(effect['who'])
    state['ledger'] = ledger
    state['committed'].append(signature(effect))
    return beat


def ledger_view(state):
    return json.loads(json.dumps(state['ledger']))


def save(state, folder):
    write_json(folder / 'state.json', state)
    sections = [f"《{state['title']}》", state['opening']]
    for scene in state['accepted']:
        sections.append(f"第{scene['number']}拍\n\n{scene['text']}")
    write_text(folder / 'manuscript.txt', '\n\n'.join(sections) + '\n')


def ask(client, folder, label, stage, system, context, structured, validator):
    error = ''
    for attempt in range(2):
        payload = dict(context, format_error=error) if error else context
        raw = client.complete(stage, system, payload, structured)
        write_text(folder / f'{label}_{attempt + 1}.txt', raw)
        try:
            value = json.loads(raw) if structured else raw
            if structured:
                require(isinstance(value, dict), 'JSON必须是对象')
            elif not nonempty(value):
                raise ValueError('正文为空')
            validator(value)
            return value
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            error = str(exc)
            if attempt:
                raise ValueError(error) from exc
            print(f'  格式不合格，重试一次：{exc}', flush=True)


class Ollama:
    def __init__(self, model, base_url, timeout, num_ctx=None):
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.num_ctx = num_ctx or config.STORY_NUM_CTX
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def complete(self, stage, system, context, structured=False):
        payload = {
            'model': self.model, 'stream': True, 'think': False,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}],
            'options': {'num_ctx': self.num_ctx, 'temperature': 0.3 if structured else 0.7,
                        'num_predict': 700 if structured else 1200},
        }
        if structured:
            payload['format'] = 'json'
        request = urllib.request.Request(self.base_url + '/api/chat', data=json.dumps(payload).encode('utf-8'),
                                          headers={'Content-Type': 'application/json'})
        print(f'  请求 {self.base_url}，模型 {self.model}，{stage}', flush=True)
        started, chunks = time.monotonic(), []
        with self.opener.open(request, timeout=self.timeout) as response:
            for line in response:
                if time.monotonic() - started > self.timeout:
                    raise TimeoutError('本次生成超过时间上限')
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get('error'):
                    raise RuntimeError(item['error'])
                chunks.append((item.get('message') or {}).get('content') or '')
                if item.get('done'):
                    if item.get('done_reason') == 'length':
                        raise RuntimeError('达到输出长度上限，内容可能不完整')
                    break
            else:
                raise RuntimeError('连接结束但未收到完成标记')
        text = ''.join(chunks).strip()
        require(bool(text), f'{stage}返回空内容')
        return text


def _propose_context(state, rejection):
    return {
        'rules': state['rules'], 'characters': state['characters'], 'secrets': state['secrets'],
        'ledger': ledger_view(state), 'opening': state['opening'],
        'accepted': [scene['text'] for scene in state['accepted']],
        'committed': list(state['committed']), 'rejection': rejection,
    }


def _write_context(state, beat, notes):
    return {
        'opening': state['opening'], 'accepted': [scene['text'] for scene in state['accepted']],
        'ledger': ledger_view(state), 'beat': beat, 'revision_notes': notes,
    }


def run(client, folder, cast=None, beats=5):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'state.json').exists():
        state = read_json(folder / 'state.json')
    else:
        require(cast, '缺少人物卡')
        state = initial_state(cast)
        save(state, folder)
    require(1 <= beats <= 12, '拍数须为1至12')
    while len(state['accepted']) < beats:
        number = len(state['accepted']) + 1
        rejection = ''
        beat = None
        for attempt in range(3):
            print(f'第{number}拍：提议变化 {attempt + 1}……', flush=True)
            try:
                raw = ask(client, folder, f'beat_{number}_propose_{attempt + 1}', 'propose', PROPOSE_SYSTEM,
                          _propose_context(state, rejection), True, normalize_beat)
                beat = normalize_beat(raw)
            except ValueError as exc:
                rejection = str(exc)
                beat = None
                continue
            rejection = validate_beat(beat, state)
            if not rejection:
                break
            print(f'  不成立：{rejection}', flush=True)
            beat = None
        if beat is None:
            state['status'] = 'stopped'
            save(state, folder)
            raise RuntimeError(f'第{number}拍没有提出成立的变化：{rejection}')
        notes = ''
        text = ''
        for attempt in range(3):
            print(f'第{number}拍：写作 {attempt + 1}……', flush=True)
            try:
                text = ask(client, folder, f'beat_{number}_prose_{attempt + 1}', 'write', WRITE_SYSTEM,
                           _write_context(state, beat, notes), False, lambda value: require(nonempty(value), '正文为空'))
            except ValueError as exc:
                notes = str(exc)
                text = ''
                continue
            if beat['anchor'] in text:
                break
            notes = f"正文必须原样包含这句：{beat['anchor']}"
            print(f'  {notes}', flush=True)
            text = ''
        if not text:
            state['status'] = 'stopped'
            save(state, folder)
            raise RuntimeError(f'第{number}拍的正文没有写上原句，账本未改。')
        apply_beat(state, beat)
        state['accepted'].append({'number': number, 'beat': beat, 'text': text})
        state['status'] = 'complete' if len(state['accepted']) == beats else 'writing'
        save(state, folder)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cast', type=Path, default=BASE / 'cast.json')
    parser.add_argument('--output', type=Path, help='新建输出目录，必须不存在')
    parser.add_argument('--beats', type=int, default=5)
    parser.add_argument('--model', default=config.LLM_MODEL)
    parser.add_argument('--base-url', default=config.OLLAMA_BASE_URL)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    require(args.timeout > 0, '超时必须为正')
    folder = args.output or ROOT / 'runs' / ('beats_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    if folder.exists():
        raise SystemExit('输出目录已存在，请换一个目录。')
    client = Ollama(args.model, args.base_url, args.timeout)
    print(f'输出目录：{folder}', flush=True)
    try:
        state = run(client, folder, load_cast(args.cast), args.beats)
    except Exception as exc:
        print(f'停止：{exc}\n已通过的正文保存在 {folder}。', flush=True)
        return 1
    print(f"已完成 {len(state['accepted'])}/{args.beats} 拍：{folder / 'manuscript.txt'}", flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
