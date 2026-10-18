import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch, MagicMock

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('story', BASE / '3_story.py')
story = importlib.util.module_from_spec(spec)
spec.loader.exec_module(story)

class FakeClient:
    def __init__(self, reject=0, crash_at=None, malformed=False):
        self.data = story.read_json(BASE / 'examples/three_scene_replay.json')
        self.reject, self.crash_at, self.malformed = reject, crash_at, malformed
        self.contexts = []

    def complete(self, stage, system, context, structured=False):
        self.contexts.append((stage, copy.deepcopy(context)))
        if stage == 'plan':
            if self.malformed:
                self.malformed = False
                return 'bad json'
            return json.dumps(self.data['plan'], ensure_ascii=False)
        if context['scene_number'] == self.crash_at:
            raise ConnectionError('simulated outage')
        item = self.data['scenes'][context['scene_number'] - 1]
        if stage == 'write':
            return item['text']
        if self.reject:
            self.reject -= 1
            return json.dumps({'approved': False, 'issues': ['结尾未达成，请补充行动']}, ensure_ascii=False)
        return json.dumps(item['review'], ensure_ascii=False)

class StoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.cfg = story.read_json(BASE / 'story_state.json')

    def test_complete_preserves_opening_and_full_history(self):
        client = FakeClient()
        state = story.run(client, self.folder, self.cfg)
        self.assertEqual(state['status'], 'complete')
        self.assertEqual(len(state['accepted']), 3)
        self.assertEqual(state['memory']['unresolved'], [])
        self.assertIn(self.cfg['opening'], (self.folder / 'manuscript.txt').read_text(encoding='utf-8'))
        third = next(c for stage, c in client.contexts if stage == 'write' and c['scene_number'] == 3)
        self.assertEqual(third['accepted_text'], [s['text'] for s in state['accepted'][:2]])
        self.assertEqual(third['memory'], state['accepted'][1]['review']['memory'])

    def test_rejection_rewrites_before_commit(self):
        client = FakeClient(reject=1)
        state = story.run(client, self.folder, self.cfg)
        writes = [c for stage, c in client.contexts if stage == 'write']
        self.assertEqual(len(writes), 4)
        self.assertTrue(writes[1]['revision_notes'])
        self.assertTrue(writes[1]['previous_draft'])
        self.assertEqual(len(state['accepted']), 3)

    def test_rejected_draft_never_committed_and_resume_keeps_logs(self):
        with self.assertRaises(RuntimeError):
            story.run(FakeClient(reject=10), self.folder, self.cfg, max_revisions=1)
        state = story.read_json(self.folder / 'state.json')
        self.assertEqual(state['accepted'], [])
        self.assertEqual(state['status'], 'needs_revision')
        self.assertNotIn('第1场', (self.folder / 'manuscript.txt').read_text(encoding='utf-8'))
        old_files = set(self.folder.glob('*raw*'))
        state = story.run(FakeClient(), self.folder)
        self.assertEqual(state['status'], 'complete')
        self.assertTrue(old_files.issubset(set(self.folder.glob('*raw*'))))

    def test_network_resume_and_completed_noop(self):
        with self.assertRaises(ConnectionError):
            story.run(FakeClient(crash_at=2), self.folder, self.cfg)
        self.assertEqual(len(story.read_json(self.folder / 'state.json')['accepted']), 1)
        client = FakeClient()
        story.run(client, self.folder)
        self.assertEqual([c['scene_number'] for stage, c in client.contexts if stage == 'write'], [2, 3])
        completed = FakeClient(crash_at=1)
        story.run(completed, self.folder)
        self.assertEqual(completed.contexts, [])

    def test_format_retry_and_final_closure_gate(self):
        story.run(FakeClient(malformed=True), self.folder, self.cfg)
        review = copy.deepcopy(FakeClient().data['scenes'][2]['review'])
        review['memory']['unresolved'] = ['仍未投稿']
        with self.assertRaises(ValueError):
            story.validate_review(review, True)
        review['approved'] = 'true'
        with self.assertRaises(ValueError):
            story.validate_review(review, False)

    def test_plan_and_backend_validation(self):
        plan = FakeClient().data['plan']
        plan['scenes'].pop()
        with self.assertRaises(ValueError):
            story.validate_plan(plan, self.cfg['characters'])
        story.run(FakeClient(), self.folder, self.cfg, source='replay')
        with self.assertRaises(ValueError):
            story.run(FakeClient(), self.folder, source='ollama')

    def test_ollama_request_contract(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {'message': {'content': '{"ok":true}'}}).encode('utf-8')
        with patch.object(story.urllib.request, 'urlopen', return_value=response) as send:
            result = story.Ollama('test-model', 'http://localhost:11434/', 12).complete(
                'review', 'editor', {'draft': '正文'}, True)
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, 'http://localhost:11434/api/chat')
        self.assertFalse(payload['stream'])
        self.assertEqual(payload['format'], 'json')
        self.assertEqual(payload['model'], 'test-model')
        self.assertIn('正文', payload['messages'][1]['content'])
        self.assertEqual(send.call_args.kwargs['timeout'], 12)
        self.assertEqual(json.loads(result), {'ok': True})

if __name__ == '__main__':
    unittest.main()
