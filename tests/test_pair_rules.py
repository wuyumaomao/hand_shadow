import sys
import unittest
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pair_rules import plan, RULES


class RuleTests(unittest.TestCase):
    def test_all_single_pairs_and_cache(self):
        p = plan({'rules': [{'type': rule} for rule in RULES]})
        self.assertEqual(Counter(v['rule'] for v in p['pairs']),
                         {'count_preserve': 220, 'shift_one': 5, 'shift_two': 10,
                          'lighting_l1': 32, 'lighting_l2': 32, 'stretch': 32})
        self.assertEqual(len(p['images']), 128)
        for record in p['pairs']:
            a, b = record['input_states']['left'], record['output_states']['left']
            if record['rule'] == 'count_preserve':
                self.assertNotEqual(a, b)
                self.assertEqual(a.count(4), b.count(4))
            elif record['rule'].startswith('shift'):
                self.assertEqual(a.count(0), 1 if record['rule'] == 'shift_one' else 2)
                self.assertEqual(b, a[-1:] + a[:-1])
            else:
                self.assertEqual(a, b)

    def test_two_hands_use_one_combined_vector(self):
        config = {'active_hands': ['left', 'right'], 'seed': 7,
                  'rules': [{'type': 'count_preserve', 'pair_count': 100}]}
        p = plan(config)
        self.assertEqual(p, plan(config))
        signatures = set()
        for record in p['pairs']:
            signatures.add((str(record['input_states']), str(record['output_states'])))
            a, b = record['flat_input_state'], record['flat_output_state']
            self.assertNotEqual(a, b)
            self.assertEqual(a.count(4), b.count(4))
            self.assertEqual(a, [record['input_states']['left'][4], record['input_states']['left'][3],
                                 record['input_states']['left'][2], record['input_states']['left'][1],
                                 record['input_states']['left'][0], *record['input_states']['right']])
            self.assertEqual(b, [record['output_states']['left'][4], record['output_states']['left'][3],
                                 record['output_states']['left'][2], record['output_states']['left'][1],
                                 record['output_states']['left'][0], *record['output_states']['right']])
        self.assertEqual(len(signatures), 100)

    def test_two_hand_shift_wraps_across_boundary(self):
        p = plan({'active_hands': ['left', 'right'], 'rules': [
            {'type': 'shift_one', 'pair_count': 'all'},
            {'type': 'shift_two', 'pair_count': 'all'}]})
        self.assertEqual(Counter(v['rule'] for v in p['pairs']),
                         {'shift_one': 10, 'shift_two': 45})
        for record in p['pairs']:
            a, b = record['flat_input_state'], record['flat_output_state']
            self.assertEqual(b, a[-1:] + a[:-1])
            self.assertEqual(a.count(0), 1 if record['rule'] == 'shift_one' else 2)

    def test_impossible_or_unknown_rules_rejected(self):
        for config in [
            {'rules': [{'type': 'shift_one', 'pair_count': 25}]},
            {'rules': [{'type': 'unrecognised'}]},
            {'rules': [{'type': 'stretch'}, {'type': 'stretch'}]},
            {'active_hands': ['left', 'left'], 'rules': [{'type': 'stretch'}]},
            {'active_hands': ['left', 'right'], 'rules': [{'type': 'count_preserve', 'pair_count': 10001}]},
        ]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                plan(config)


if __name__ == '__main__':
    unittest.main()
