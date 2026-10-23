"""三场短篇：规划、整场写作、审核修改、更新事实。标准库即可运行。"""
import argparse
import datetime
import json
import os
import threading
import time
from pathlib import Path
import urllib.request
import config

BASE = Path(__file__).resolve().parent
CARD_KEYS = ('title', 'viewpoint', 'task', 'obstacle', 'conflict', 'change', 'end_condition')
PLAN_SYSTEM = '''你是短篇小说编辑。根据人物和已发生的开场规划恰好三场，第三场必须完结。
聚焦一个核心矛盾，其余人物目标成为支线或阻力。每场用行动、选择、后果推进，换地点不算推进。
开场已经发生，不重写。只输出JSON：
{"direction":"核心矛盾","ending":"具体结局",
"initial_memory":{"facts":["开场事实"],"relationships":["关系现状"],"unresolved":["未解决事项"]},
"scenes":[{"title":"场名","viewpoint":"现有人物名","task":"当前任务","obstacle":"阻碍",
"conflict":"实际冲突","change":"必须发生的变化","end_condition":"可验证的结束条件"}]}。
结局回应核心矛盾并交代支线，不另开悬念。计划不能写成已经发生的事实。'''
WRITE_SYSTEM = '''你是小说作者，续接已有正文，按当前场景卡写一场完整的戏，约800至1200中文字。
采用指定视角的第三人称有限叙述。对白自然使用我和你，允许多人互动，不按角色轮换切段。
用动作、对白、选择与后果写戏，不堆突发事件，不反复解释人物标签。不复述开场。
遵守既定事实，不提前获知他人内心。保留轻喜剧语气，不羞辱失落中的人物。
场景卡是计划而非历史，目标未完成不能假装完成。
末场必须兑现结局，交代投稿、部费、田径场约定的结果，自然收束。
如有修改意见，改写当前场完整正文。只输出正文，不输出标题、分析或JSON。'''
REVIEW_SYSTEM = '''你是严格的小说编辑。检查草稿是否以行动实现本场变化和结束条件，是否违背既定事实
或人物动机，是否有清楚的因果衔接。严重问题拒绝并给可执行修改意见，措辞偏好不构成拒绝。
末场必须完成结局、交代支线，不能只承诺稍后解决。
通过时从已接受历史加本场提取更新后的完整记忆，只收录正文事实，不能把计划当事实。
末场通过时unresolved必须为空。只输出JSON：
{"approved":true或false,"issues":["问题与修改方式"],
"evidence":{"change":"变化的具体行动","end_condition":"结束条件如何达成",
"continuity":"与已定事实的衔接","closure":"末场结局与支线结果，其他场的后续原因"},
"memory":{"facts":["事实"],"relationships":["关系变化"],"unresolved":["未解决事项"]}}。'''


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


def validate_memory(memory):
    require(isinstance(memory, dict), '记忆必须是对象')
    for key in ('facts', 'relationships', 'unresolved'):
        require(isinstance(memory.get(key), list) and all(nonempty(x) for x in memory[key]),
                f'记忆 {key} 必须是字符串数组')


def validate_plan(plan, characters):
    require(isinstance(plan, dict), '规划必须是对象')
    require(nonempty(plan.get('direction')) and nonempty(plan.get('ending')), '缺少方向或结局')
    validate_memory(plan.get('initial_memory'))
    cards = plan.get('scenes')
    require(isinstance(cards, list) and len(cards) == 3, '必须恰好三场')
    for card in cards:
        require(isinstance(card, dict) and all(nonempty(card.get(k)) for k in CARD_KEYS), '场景卡不完整')
        require(card['viewpoint'] in {c['name'] for c in characters}, '视角必须来自现有人物')


def validate_review(review, final):
    require(isinstance(review, dict) and type(review.get('approved')) is bool, 'approved必须是布尔值')
    issues = review.get('issues')
    require(isinstance(issues, list) and all(nonempty(x) for x in issues), 'issues格式错误')
    if review['approved']:
        require(not issues, '有待修改问题不能通过')
        evidence = review.get('evidence')
        require(isinstance(evidence, dict) and all(nonempty(evidence.get(k)) for k in
                ('change', 'end_condition', 'continuity', 'closure')), '通过审核必须提供依据')
        validate_memory(review.get('memory'))
        require(not final or not review['memory']['unresolved'], '末场仍有未解决事项')
    else:
        require(bool(issues), '拒绝必须提供修改意见')


class IncompleteGeneration(RuntimeError):
    def __init__(self, message, partial=''):
        super().__init__(message)
        self.partial = partial


class Ollama:
    def __init__(self, model, base_url, timeout, num_ctx=None):
        self.model, self.base_url, self.timeout = model, base_url.rstrip('/'), timeout
        self.num_ctx = num_ctx or config.STORY_NUM_CTX
        # 私有网段也直连，避免系统代理截获局域网请求。
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def complete(self, stage, system, context, structured=False):
        ctx = min(self.num_ctx, 4096) if stage == 'plan' else self.num_ctx
        payload = {'model': self.model, 'stream': True, 'think': False,
                   'messages': [{'role': 'system', 'content': system},
                                {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}],
                   'options': {'num_ctx': ctx, 'temperature': 0.25 if structured else config.LLM_TEMPERATURE,
                               'num_predict': 2048 if structured else 3072}}
        if structured:
            payload['format'] = 'json'
        request = urllib.request.Request(self.base_url + '/api/chat', data=json.dumps(payload).encode('utf-8'),
                                         headers={'Content-Type': 'application/json'})
        started, chunks, thinking = time.monotonic(), [], []
        stopped = threading.Event()

        def progress():
            while not stopped.wait(5):
                count = sum(len(x) for x in chunks)
                status = f'已收到 {count} 字' if count else '等待加载模型/处理提示词'
                if thinking:
                    status += f'，思考 {sum(len(x) for x in thinking)} 字'
                print(f'  [{stage}] {time.monotonic() - started:.0f}s，{status}', flush=True)

        print(f'  请求 {self.base_url}，模型 {self.model}，上下文 {ctx}，流式接收……', flush=True)
        worker = threading.Thread(target=progress, daemon=True)
        worker.start()
        final = None
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                for line in response:
                    if time.monotonic() - started > self.timeout:
                        raise TimeoutError('本次生成超过时间上限')
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if item.get('error'):
                        raise RuntimeError(item['error'])
                    message = item.get('message') or {}
                    chunks.append(message.get('content') or '')
                    if message.get('thinking'):
                        thinking.append(message['thinking'])
                    if item.get('done'):
                        final = item
                        break
            text = ''.join(chunks).strip()
            if final is None:
                raise RuntimeError('连接结束但未收到完成标记')
            if final.get('done_reason') == 'length':
                raise RuntimeError('达到输出长度上限，内容可能不完整')
            require(bool(text), f'{stage}返回空内容')
            duration = final.get('eval_duration', 0) / 1e9
            speed = final.get('eval_count', 0) / duration if duration else 0
            print(f'  完成：{len(text)} 字，{time.monotonic() - started:.1f}s，生成 {speed:.1f} token/s', flush=True)
            return text
        except Exception as exc:
            raise IncompleteGeneration(str(exc), ''.join(chunks)) from exc
        finally:
            stopped.set()
            worker.join()


class Replay:
    """离线样稿回放，不代表真实模型生成或审核。"""
    def __init__(self, path):
        self.data = read_json(path)

    def complete(self, stage, system, context, structured=False):
        if stage == 'plan':
            result = self.data['plan']
        else:
            scene = self.data['scenes'][context['scene_number'] - 1]
            result = scene['text'] if stage == 'write' else scene['review']
        return json.dumps(result, ensure_ascii=False) if structured else result


def ask(client, folder, label, stage, system, context, structured, validator):
    label += '_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    for attempt in range(2):
        try:
            raw = client.complete(stage, system, context, structured)
        except IncompleteGeneration as exc:
            if exc.partial:
                write_text(folder / f'{label}_partial_{attempt + 1}.txt', exc.partial)
            raise
        write_text(folder / f'{label}_raw_{attempt + 1}.txt', raw)
        try:
            value = json.loads(raw) if structured else raw
            validator(value)
            return value
        except (ValueError, TypeError) as exc:
            if attempt:
                raise
            context = dict(context, format_error=str(exc), previous_response=raw)
            print(f'  格式不合格，重试一次：{exc}', flush=True)


def save(state, folder):
    write_json(folder / 'state.json', state)
    sections = [f"《{state['title']}》", state['opening']]
    for scene in state['accepted']:
        sections.append(f"第{scene['number']}场：{scene['card']['title']}\n\n{scene['text']}")
    write_text(folder / 'manuscript.txt', '\n\n'.join(sections) + '\n')


def run(client, folder, cfg=None, max_revisions=2, source='ollama'):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'state.json').exists():
        state = read_json(folder / 'state.json')
        require(state['source'] == source, '续跑不可混用示例回放和真实生成')
    else:
        require(isinstance(cfg, dict) and bool(cfg.get('characters')), '配置缺少人物')
        opening = cfg.get('opening') or cfg.get('manuscript') or ''
        require(nonempty(opening), '配置缺少开场')
        state = {'version': 2, 'source': source, 'title': cfg.get('title', '未命名'),
                 'characters': cfg['characters'], 'opening': opening, 'plan': None,
                 'memory': None, 'accepted': [], 'status': 'planning'}
        save(state, folder)
    if state['status'] == 'complete':
        save(state, folder)
        return state
    if state['plan'] is None:
        print('规划三场与结局……', flush=True)
        plan = ask(client, folder, 'plan', 'plan', PLAN_SYSTEM,
                   {'characters': state['characters'], 'opening': state['opening']}, True,
                   lambda p: validate_plan(p, state['characters']))
        state['plan'], state['memory'] = plan, plan['initial_memory']
        write_json(folder / 'plan.json', plan)
        save(state, folder)
    for index in range(len(state['accepted']), 3):
        card = state['plan']['scenes'][index]
        # 三场短篇使用全部已接受正文，不截断中间历史。
        context = {'characters': state['characters'], 'plan': state['plan'], 'opening': state['opening'],
                   'accepted_text': [s['text'] for s in state['accepted']], 'memory': state['memory'],
                   'card': card, 'scene_number': index + 1, 'final_scene': index == 2}
        issues, draft = [], ''
        for revision in range(max_revisions + 1):
            label = f'scene_{index + 1}_v{revision + 1}'
            print(f"第{index + 1}场《{card['title']}》：写作/修改 {revision + 1}……", flush=True)
            draft = ask(client, folder, label + '_draft', 'write', WRITE_SYSTEM,
                        dict(context, previous_draft=draft, revision_notes=issues), False,
                        lambda x: require(nonempty(x), '正文为空'))
            print('  检查场景变化、连续性与收束……', flush=True)
            review = ask(client, folder, label + '_review', 'review', REVIEW_SYSTEM,
                         dict(context, draft=draft), True, lambda r: validate_review(r, index == 2))
            write_json(folder / f'{label}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")}_review.json', review)
            if review['approved']:
                state['accepted'].append({'number': index + 1, 'card': card, 'text': draft, 'review': review})
                state['memory'] = review['memory']
                state['status'] = 'complete' if index == 2 else 'writing'
                save(state, folder)
                break
            issues = review['issues']
            print('  需要修改：' + '；'.join(issues), flush=True)
        else:
            state['status'] = 'needs_revision'
            save(state, folder)
            raise RuntimeError(f'第{index + 1}场审核未通过，草稿已保存，未计入正文；可--resume续跑')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=BASE / 'story_state.json')
    parser.add_argument('--resume', type=Path, help='继续已有runs子目录')
    parser.add_argument('--output', type=Path, help='新建输出目录（必须不存在）')
    parser.add_argument('--model', default=config.LLM_MODEL)
    parser.add_argument('--base-url', default=config.OLLAMA_BASE_URL)
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--num-ctx', type=int, default=config.STORY_NUM_CTX, help='写作/审核上下文；规划最多4096')
    parser.add_argument('--max-revisions', type=int, default=2)
    parser.add_argument('--replay', type=Path, help='离线样稿回放，仅验证流程，不调用模型')
    args = parser.parse_args()
    require(args.max_revisions >= 0 and args.timeout > 0 and args.num_ctx >= 2048, '次数不能为负，超时必须为正，上下文至少2048')
    require(not (args.resume and args.output), '--resume与--output不能同时使用')
    if args.resume:
        require((args.resume / 'state.json').is_file(), '续跑目录中没有state.json')
    folder = args.resume or args.output or BASE / 'runs' / datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    if not args.resume:
        folder.mkdir(parents=True, exist_ok=False)
    source = 'replay' if args.replay else 'ollama'
    if args.replay:
        print('离线示例回放：使用预写样稿和审核记录，不代表真实模型生成或审核。', flush=True)
    client = Replay(args.replay) if args.replay else Ollama(args.model, args.base_url, args.timeout, args.num_ctx)
    print(f'输出目录：{folder}', flush=True)
    try:
        state = run(client, folder, None if args.resume else read_json(args.config), args.max_revisions, source)
    except Exception as exc:
        print(f'停止：{exc}\n已接受正文与进度保存在 {folder}。', flush=True)
        return 1
    print(f"已完成 {len(state['accepted'])}/3 场：{folder / 'manuscript.txt'}", flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
