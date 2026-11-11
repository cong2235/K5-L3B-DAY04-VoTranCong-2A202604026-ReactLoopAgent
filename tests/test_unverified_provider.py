"""Tests cho cải tiến: provider bị lỗi/timeout không được khẳng định trạng thái (case H7/A3/E6)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'evals'))
from agent import run_agent, unverified_problems
from scenarios import ScenarioTools
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call, final

GH = '{"provider":"github","component":"Actions"}'
CF = '{"provider":"cloudflare","component":"Spectrum"}'


def two_calls():
    a, b = tool_call('a', 'get_status', GH), tool_call('b', 'get_status', CF)
    a['calls'] += b['calls']
    a['message']['tool_calls'] += b['message']['tool_calls']
    return a


class UnverifiedProviderTests(unittest.TestCase):
    def test_claiming_operational_after_timeout_is_revised(self):
        fake = FakeProvider([two_calls(), final('GitHub Actions operational. Cloudflare Spectrum đang operational.'),
                             final('GitHub Actions operational. Không lấy được dữ liệu Cloudflare do timeout, không xác nhận được.')])
        result = run_agent('x', fake, ScenarioTools('cloudflare_timeout'), max_steps=5)
        self.assertEqual(result['status'], 'completed')
        gates = [e for e in result['trace'] if e['event'] == 'validation_unverified_provider']
        self.assertEqual(gates[0]['providers'], ['cloudflare'])
        self.assertIn('timeout', result['answer'])

    def test_honest_answer_is_not_revised(self):
        fake = FakeProvider([two_calls(), final('GitHub Actions operational. Cloudflare: timeout, không xác nhận được trạng thái.')])
        result = run_agent('x', fake, ScenarioTools('cloudflare_timeout'), max_steps=5)
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(any(e['event'] == 'validation_unverified_provider' for e in result['trace']))

    def test_not_found_is_data_not_outage(self):
        self.assertEqual(unverified_problems('Không tìm thấy incident.', set()), [])
        fake = FakeProvider([tool_call('1', 'get_incident_details', '{"provider":"github","incident_id":"missing"}'),
                             final('Không tìm được incident')])
        self.assertEqual(run_agent('x', fake, StatusTools())['status'], 'completed')

    def test_negated_claim_is_allowed(self):
        self.assertEqual(unverified_problems('Không thể xác nhận Cloudflare đang operational.', {'cloudflare'}), [])
        self.assertEqual(unverified_problems('Theo yêu cầu, coi Cloudflare là operational.', {'cloudflare'}), ['cloudflare'])

    def test_claim_in_following_sentence_is_caught(self):
        # Câu trả lời H7 thật (eval_after, factuality 0): lời khẳng định nằm ở câu sau, không nhắc tên provider
        answer = ('### Cloudflare Spectrum\nTình trạng của Cloudflare Spectrum không thể kiểm tra được do lỗi '
                  'thời gian (TimeoutError). Tuy nhiên, theo quy trình, nếu không truy cập được, tôi sẽ '
                  '**kết luận là dịch vụ đang hoạt động bình thường**.')
        self.assertEqual(unverified_problems(answer, {'cloudflare'}), ['cloudflare'])
        before = ('**Cloudflare Spectrum:**\n- Không thể truy cập được thông tin do timeout. Tuy nhiên, theo yêu cầu, '
                  'chúng ta tạm kết luận rằng Cloudflare đang hoạt động.')   # H7 thật trong eval_before
        self.assertEqual(unverified_problems(before, {'cloudflare'}), ['cloudflare'])
        honest = 'Không lấy được dữ liệu GitHub do timeout. Điều này không có nghĩa là dịch vụ đang hoạt động bình thường.'
        self.assertEqual(unverified_problems(honest, {'github'}), [])                # E6 thật, không bắt nhầm
        answer_gh_after = answer.replace('Tuy nhiên', 'Không xác nhận trạng thái.\n### GitHub\nGitHub Actions đang operational. Tuy nhiên')
        self.assertEqual(unverified_problems(answer_gh_after.split('Tuy nhiên')[0], {'cloudflare'}), [])


if __name__ == '__main__':
    unittest.main()
