"""Tests cho cải tiến: theo incident được dẫn tới trong update (case H1/H6)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import run_agent
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call, final

PARENT = '{"provider":"github","incident_id":"h02n9572mx9y"}'   # update dẫn sang xr3myzj7ms51
LINKED = '{"provider":"github","incident_id":"xr3myzj7ms51"}'
URL = 'https://stspg.io/7pwv28hvkmz8'


class LinkFollowTests(unittest.TestCase):
    def test_unfollowed_link_asks_model_to_read_linked_incident(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', PARENT), final('Xong ' + URL),
                             tool_call('2', 'get_incident_details', LINKED), final('Đã đọc cả hai ' + URL)])
        result = run_agent('x', fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        gates = [e for e in result['trace'] if e['event'] == 'validation_unfollowed_link']
        self.assertEqual(gates[0]['incidents'], ['github/xr3myzj7ms51'])
        tools = [e['arguments']['incident_id'] for e in result['trace'] if e['event'] == 'tool']
        self.assertEqual(tools, ['h02n9572mx9y', 'xr3myzj7ms51'])

    def test_link_gate_fires_only_once(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', PARENT), final('Xong ' + URL),
                             final('Vẫn không đọc ' + URL)])
        result = run_agent('x', fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(sum(e['event'] == 'validation_unfollowed_link' for e in result['trace']), 1)

    def test_no_gate_when_already_followed(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', PARENT),
                             tool_call('2', 'get_incident_details', LINKED), final('Xong ' + URL)])
        result = run_agent('x', fake, StatusTools(), max_steps=6)
        self.assertFalse(any(e['event'] == 'validation_unfollowed_link' for e in result['trace']))


if __name__ == '__main__':
    unittest.main()
