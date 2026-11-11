"""Tests cho phần bonus: retry budget 429, Retry-After, lược dữ liệu nhiễu, pagination, provider theo tên tool."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import agent
from agent import run_agent, tool_provider, retry_wait, compact
from bonus.tools import BonusTools
from bonus.test_agent import ScriptedProvider, call, final


def tool_events(result, name):
    return [e for e in result['trace'] if e['event'] == 'tool' and e['name'] == name]


class BonusRobustnessTests(unittest.TestCase):
    def test_retry_budget_stops_after_three_attempts(self):
        p = ScriptedProvider([call(str(i), 'get_vercel_status', {}) for i in range(5)]
                             + [final('Vercel: rate limit 429 liên tục, không biết trạng thái.')])
        result = run_agent('x', p, BonusTools(scenario='rate_limit_always'), max_steps=8)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(tool_events(result, 'get_vercel_status')), 3)       # max_calls của B4
        blocked = [e for e in result['trace'] if e['event'] == 'retry_budget_exhausted']
        self.assertEqual(len(blocked), 2)
        self.assertEqual(json.loads(p.histories[3][-1]['content'])['error'], 'RATE_LIMITED')         # lần 3
        self.assertEqual(json.loads(p.histories[4][-1]['content'])['error'], 'RETRY_BUDGET_EXHAUSTED')  # lần 4 bị chặn
        self.assertIn('1/3', json.loads(p.histories[1][-1]['content'])['agent_note'])

    def test_rate_limit_counter_resets_after_success(self):
        p = ScriptedProvider([call('a', 'get_vercel_status', {}), call('b', 'get_vercel_status', {}), final('ok')])
        result = run_agent('x', p, BonusTools(scenario='rate_limit_once'), max_steps=5)
        self.assertEqual(len(tool_events(result, 'get_vercel_status')), 2)
        self.assertFalse(any(e['event'] == 'retry_budget_exhausted' for e in result['trace']))

    def test_model_giving_up_early_is_asked_to_retry(self):
        # B10 lần 1: model dừng sau một lần 429 dù còn lượt
        p = ScriptedProvider([call('a', 'get_vercel_status', {}), final('Vercel: 429, bỏ qua.'),
                              call('b', 'get_vercel_status', {}), final('Vercel: none, thử lại thành công.')])
        result = run_agent('x', p, BonusTools(scenario='rate_limit_once'), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([e['event'] for e in result['trace'] if e['event'].startswith('validation')],
                         ['validation_pending_retry'])
        self.assertEqual(len(tool_events(result, 'get_vercel_status')), 2)

    def test_retry_prompt_is_bounded(self):
        p = ScriptedProvider([call('a', 'get_vercel_status', {})] + [final('Vercel: không biết (429).')] * 3)
        result = run_agent('x', p, BonusTools(scenario='rate_limit_always'), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(sum(e['event'] == 'validation_pending_retry' for e in result['trace']), 2)

    def test_retry_after_is_honoured_and_capped(self):
        self.assertEqual(retry_wait({'retry_after_seconds': 0}), 0.0)
        self.assertEqual(retry_wait({'retry_after': '2'}), 2.0)
        self.assertEqual(retry_wait({'retry_after': '120'}), agent.MAX_RETRY_WAIT)
        self.assertEqual(retry_wait({'retry_after': 'Wed, 21 Oct 2026 07:28:00 GMT'}), 0.0)
        tools = mock.Mock(execute=mock.Mock(side_effect=[
            {'ok': False, 'error': 'RATE_LIMITED', 'http_status': 429, 'retry_after': '1'},
            {'provider': 'vercel', 'overall': {'indicator': 'none'}}]), spec=['execute'])
        p = ScriptedProvider([call('a', 'get_vercel_status', {}), call('b', 'get_vercel_status', {}), final('ok')])
        with mock.patch.object(agent.time, 'sleep') as sleep:
            result = run_agent('x', p, tools, max_steps=5)
        sleep.assert_called_once_with(1.0)
        self.assertTrue(any(e['event'] == 'retry_wait' for e in result['trace']))

    def test_noisy_distractors_are_compacted_for_model_only(self):
        p = ScriptedProvider([call('a', 'get_vercel_status', {'component': 'Builds'}), final('ok')])
        result = run_agent('x', p, BonusTools(scenario='noisy'), max_steps=3)
        sent = json.loads(p.histories[1][-1]['content'])
        self.assertEqual(len(sent['distractors']), 3)
        self.assertIn('160', sent['distractors_omitted'])
        self.assertEqual(len(tool_events(result, 'get_vercel_status')[0]['result']['distractors']), 160)  # trace đầy đủ
        self.assertEqual(compact({'incidents': [1] * 8}), {'incidents': [1] * 8})

    def test_pagination_note_on_unread_pages(self):
        args = {'provider': 'vercel', 'incident_id': 'sps6n39gm4sg', 'offset': 0, 'limit': 3}
        p = ScriptedProvider([call('a', 'get_incident_details', args), final('Nguồn: https://stspg.io/cfrfjg8fqxfr')])
        run_agent('x', p, BonusTools(), max_steps=3)
        sent = json.loads(p.histories[1][-1]['content'])
        self.assertIn('next_offset=3', sent['agent_note'])

    def test_provider_from_status_tool_name(self):
        self.assertEqual(tool_provider('get_digitalocean_status', {}), 'digitalocean')
        self.assertEqual(tool_provider('get_incident_details', {'provider': 'npm'}), 'npm')
        self.assertEqual(tool_provider('get_status', {'provider': 'github'}), 'github')
        self.assertEqual(tool_provider('get_linear_status', {}), '')

    def test_unverified_vercel_claim_is_revised(self):
        p = ScriptedProvider([call(str(i), 'get_vercel_status', {}) for i in range(3)]
                             + [final('Vercel đang hoạt động bình thường.'),
                                final('Vercel bị rate limit 429 nên không biết trạng thái.')])
        result = run_agent('x', p, BonusTools(scenario='rate_limit_always'), max_steps=8)
        gates = [e for e in result['trace'] if e['event'] == 'validation_unverified_provider']
        self.assertEqual(gates[0]['providers'], ['vercel'])
        self.assertIn('không biết', result['answer'])

    def test_core_tools_keep_core_prompt(self):
        from status_tools import StatusTools
        p = ScriptedProvider([final('ok')])
        run_agent('x', p, StatusTools())
        self.assertEqual(p.histories[0][0]['content'], agent.SYSTEM_PROMPT)
        p = ScriptedProvider([final('ok')])
        run_agent('x', p, BonusTools())
        self.assertIn('RATE_LIMITED/429', p.histories[0][0]['content'])


if __name__ == '__main__':
    unittest.main()
