import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('beats', BASE / '5_beats' / 'engine.py')
beats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(beats)


def make_beat(actor, action, present, kind, item_id, before, after, anchor, who='', uses=None):
    effect = {'kind': kind, 'id': item_id, 'before': before, 'after': after}
    if who:
        effect['who'] = who
    return {'actor': actor, 'action': action, 'present': present, 'uses': uses or [], 'effect': effect, 'anchor': anchor}


DRAFT = make_beat('小鞠知花', '自己选定最终回的最后一句', ['小鞠知花', '温水和彦'], 'flag', 'draft', '卡住', '已选定', '就这个')
FIVE = [
    DRAFT,
    make_beat('烧盐柠檬', '放弃假约会，自己开始跑', ['烧盐柠檬', '温水和彦'], 'relationship', 'lemon_ask', '用假约会求助', '开始自己训练', '我自己跑'),
    make_beat('八奈见杏菜', '当面说出失落', ['八奈见杏菜', '温水和彦'], 'relationship', 'anna_face', '把失落藏起来', '当面说过失落', '我其实很在意', uses=['anna_loss']),
    make_beat('小鞠知花', '看着温水把谢谢说出来', ['小鞠知花', '温水和彦'], 'flag', 'thanks', '还没说', '已经亲口说过', '谢谢你'),
    make_beat('烧盐柠檬', '跑完一组训练', ['烧盐柠檬'], 'flag', 'training', '还没自己跑', '跑完一组', '一组跑完了'),
]
CIRCLE = make_beat('温水和彦', '再次吐槽八奈见把部费当零食基金', ['温水和彦', '八奈见杏菜'], 'resource', 'funds', 3000, 3000, '部费还是三千')


class Script:
    def __init__(self, proposals, proses):
        self.proposals = list(proposals)
        self.proses = list(proses)
        self.calls = []

    def complete(self, stage, system, context, structured=False):
        self.calls.append((stage, json.loads(json.dumps(context, ensure_ascii=False))))
        if stage == 'propose':
            item = self.proposals.pop(0)
            return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return self.proses.pop(0)


class BeatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.cast = beats.load_cast()
        self.state = beats.initial_state(self.cast)

    def test_gate_rejects_circle_secrets_overspend_and_repeat(self):
        self.assertEqual(beats.validate_beat(CIRCLE, self.state), '前后没有变化。')
        leaked = make_beat('烧盐柠檬', '说破八奈见的失落', ['烧盐柠檬', '八奈见杏菜'], 'knowledge', 'anna_loss', '不知道', '知道', '原来如此', who='烧盐柠檬', uses=['anna_loss'])
        self.assertEqual(beats.validate_beat(leaked, self.state), '行动者还不知道这个秘密。')
        overspent = make_beat('八奈见杏菜', '把部费买光', ['八奈见杏菜'], 'resource', 'funds', 3000, -100, '买光了')
        self.assertEqual(beats.validate_beat(overspent, self.state), '资源不足。')
        stranger = make_beat('路人甲', '走进活动室', ['路人甲'], 'flag', 'draft', '卡住', '已选定', '新来的人')
        self.assertEqual(beats.validate_beat(stranger, self.state), '不能新增人物。')
        self.assertEqual(beats.validate_beat(DRAFT, self.state), '')
        beats.apply_beat(self.state, DRAFT)
        back = make_beat('小鞠知花', '把写好的结局又划掉', ['小鞠知花'], 'flag', 'draft', '已选定', '卡住', '先停一下')
        beats.apply_beat(self.state, back)
        self.assertIn('已经提交过', beats.validate_beat(DRAFT, self.state))

    def test_circle_is_rejected_and_a_real_change_is_committed(self):
        client = Script([CIRCLE, DRAFT], ['小鞠把最后一句留下，说：就这个。'])
        state = beats.run(client, self.folder, self.cast, beats=1)
        self.assertEqual(client.calls[1][1]['rejection'], '前后没有变化。')
        self.assertEqual(state['ledger']['resources'][0]['value'], 3000)
        self.assertEqual(next(item['value'] for item in state['ledger']['flags'] if item['id'] == 'draft'), '已选定')
        manuscript = (self.folder / 'manuscript.txt').read_text(encoding='utf-8')
        self.assertIn('就这个', manuscript)
        self.assertNotIn('部费还是三千', manuscript)
        self.assertEqual(len(state['committed']), 1)

    def test_missing_anchor_rewrites_prose_without_touching_ledger(self):
        client = Script([DRAFT], ['大家又坐着聊天。', '小鞠看着屏幕，说：就这个。'])
        state = beats.run(client, self.folder, self.cast, beats=1)
        writes = [context for stage, context in client.calls if stage == 'write']
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[0]['beat']['effect'], writes[1]['beat']['effect'])
        self.assertEqual(next(item['value'] for item in writes[1]['ledger']['flags'] if item['id'] == 'draft'), '卡住')
        self.assertIn('就这个', writes[1]['revision_notes'])
        self.assertNotIn('secrets', writes[0])
        self.assertNotIn('用吃东西掩饰失落', json.dumps(writes[0], ensure_ascii=False))
        self.assertEqual(len(state['committed']), 1)
        manuscript = (self.folder / 'manuscript.txt').read_text(encoding='utf-8')
        self.assertIn('就这个', manuscript)
        self.assertNotIn('大家又坐着聊天', manuscript)

    def test_five_beats_commit_five_distinct_changes(self):
        client = Script(FIVE, [f'这一拍落在纸上。{item["anchor"]}。' for item in FIVE])
        state = beats.run(client, self.folder, self.cast, beats=5)
        self.assertEqual(state['status'], 'complete')
        self.assertEqual(len(state['committed']), 5)
        self.assertEqual(len(set(state['committed'])), 5)
        manuscript = (self.folder / 'manuscript.txt').read_text(encoding='utf-8')
        for item in FIVE:
            self.assertIn(item['anchor'], manuscript)
        propose = next(context for stage, context in client.calls if stage == 'propose')
        self.assertIn('用吃东西掩饰失落', json.dumps(propose, ensure_ascii=False))

    def test_unusable_proposals_stop_without_a_scene(self):
        client = Script([CIRCLE, CIRCLE, CIRCLE], [])
        with self.assertRaises(RuntimeError):
            beats.run(client, self.folder, self.cast, beats=1)
        state = beats.read_json(self.folder / 'state.json')
        self.assertEqual(state['status'], 'stopped')
        self.assertEqual(state['accepted'], [])
        self.assertNotIn('第1拍', (self.folder / 'manuscript.txt').read_text(encoding='utf-8'))

    def test_malformed_proposal_is_retried_once(self):
        client = Script(['bad json', DRAFT], ['小鞠说：就这个。'])
        beats.run(client, self.folder, self.cast, beats=1)
        proposals = [context for stage, context in client.calls if stage == 'propose']
        self.assertEqual(len(proposals), 2)
        self.assertIn('format_error', proposals[1])
        self.assertNotIn('format_error', proposals[0])

    def test_ollama_request_contract(self):
        lines = [
            (json.dumps({'message': {'content': '{"ok":true}'}, 'done': False}) + '\n').encode(),
            (json.dumps({'message': {'content': ''}, 'done': True, 'done_reason': 'stop'}) + '\n').encode(),
        ]
        response = MagicMock()
        response.__enter__.return_value = lines
        client = beats.Ollama('test-model', 'http://127.0.0.1:11434/', 12)
        with patch.object(client.opener, 'open', return_value=response) as send:
            result = client.complete('propose', 'editor', {'ledger': {}}, True)
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, 'http://127.0.0.1:11434/api/chat')
        self.assertTrue(payload['stream'])
        self.assertFalse(payload['think'])
        self.assertEqual(payload['format'], 'json')
        self.assertEqual(payload['model'], 'test-model')
        self.assertIn('ledger', payload['messages'][1]['content'])
        self.assertEqual(send.call_args.kwargs['timeout'], 12)
        self.assertEqual(result, '{"ok":true}')
