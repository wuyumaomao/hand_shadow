import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configuration import ROOT, merge, validate


class ConfigurationTests(unittest.TestCase):
    def test_examples(self):
        for filename in ['single_hand.json', 'multi_hand.json']:
            validate(json.loads((ROOT / 'configs' / filename).read_text()))

    def test_bad_controls_rejected(self):
        bad = [
            {'camera': {'name': 'Camera'}},
            {'camera': {'position': {'x': float('nan')}}},
            {'hands': {'left': {'state': [False, 0, 0, 0, 0]}}},
            {'hands': {'left': {'bend_angles': {'thumb': [-20, 30]}}}},
            {'hands': {'right': {'enabled': True}}},
            {'samples': [{'light': {'rotation_degrees': {'q': 4}}}]},
            {'samples': []}, {'render': {'resolution': [512, 0]}},
        ]
        for config in bad:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate(config)

    def test_merge_preserves_independent_axes_and_inputs(self):
        base = {'hands': {'right': {'translation': {'x': 5, 'y': 2}}}}
        before = copy.deepcopy(base)
        changed = merge(base, {'hands': {'right': {'translation': {'y': 9}}}})
        self.assertEqual(changed['hands']['right']['translation'], {'x': 5, 'y': 9})
        self.assertEqual(base, before)


if __name__ == '__main__':
    unittest.main()
