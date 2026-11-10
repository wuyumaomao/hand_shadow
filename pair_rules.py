"""Pure rule planner. Ground truth is computed here, not by an LLM."""
import copy
import random
from configuration import FINGERS, keys

RULES = ['count_preserve', 'shift_one', 'shift_two', 'lighting_l1', 'lighting_l2', 'stretch']
STATES = [tuple(4 if sid & (1 << i) else 0 for i in range(5)) for sid in range(32)]
COUNT_PAIRS = [(a, b) for a in STATES for b in STATES if a != b and a.count(4) == b.count(4)]


def state_options(width, rule):
    """Build rule pairs over one combined vector (5 or 10 positions)."""
    states = [tuple(4 if sid & (1 << i) else 0 for i in range(width))
              for sid in range(1 << width)]
    if rule == 'count_preserve':
        return [(a, b) for a in states for b in states
                if a != b and a.count(4) == b.count(4)]
    if rule in ['shift_one', 'shift_two']:
        straight_count = 1 if rule == 'shift_one' else 2
        return [(s, s[-1:] + s[:-1]) for s in states if s.count(0) == straight_count]
    return [(s, s) for s in states]


def split_state(vector, hands):
    if hands == ['left', 'right']:
        visual_order = [
            ('left', 'pinky'), ('left', 'ring'), ('left', 'middle'),
            ('left', 'index'), ('left', 'thumb'),
            ('right', 'thumb'), ('right', 'index'), ('right', 'middle'),
            ('right', 'ring'), ('right', 'pinky'),
        ]
        result = {hand: [0] * 5 for hand in hands}
        finger_index = {finger: i for i, finger in enumerate(FINGERS)}
        for value, (hand, finger) in zip(vector, visual_order):
            result[hand][finger_index[finger]] = value
        return result
    return {hand: list(vector[i * 5:(i + 1) * 5]) for i, hand in enumerate(hands)}


def combine_state(states, hands):
    if hands == ['left', 'right']:
        visual_order = [
            ('left', 'pinky'), ('left', 'ring'), ('left', 'middle'),
            ('left', 'index'), ('left', 'thumb'),
            ('right', 'thumb'), ('right', 'index'), ('right', 'middle'),
            ('right', 'ring'), ('right', 'pinky'),
        ]
        finger_index = {finger: i for i, finger in enumerate(FINGERS)}
        return tuple(states[hand][finger_index[finger]] for hand, finger in visual_order)
    return tuple(value for hand in hands for value in states[hand])


def validate_generation(config):
    keys(config, ['active_hands', 'seed', 'rules', 'render', 'pair_layout'], 'generation')
    result = copy.deepcopy(config)
    result.setdefault('active_hands', ['left'])
    hands = result['active_hands']
    if not isinstance(hands, list) or not hands or any(type(h) is not str or h not in ['left', 'right'] for h in hands) or len(set(hands)) != len(hands):
        raise ValueError('active_hands must be ["left"], ["right"], or ["left", "right"]')
    result.setdefault('seed', 42)
    if type(result['seed']) is not int or not 0 <= result['seed'] < 2**31:
        raise ValueError('seed must be integer 0..2147483647')
    rules = result.get('rules')
    if not isinstance(rules, list) or not rules:
        raise ValueError('rules must be a nonempty list')
    seen = set()
    for rule in rules:
        keys(rule, ['type', 'pair_count'], 'rule')
        name = rule.get('type')
        if not isinstance(name, str) or name not in RULES or name in seen:
            raise ValueError('Unknown or duplicate rule: ' + str(name))
        seen.add(name)
        count = rule.setdefault('pair_count', 'all')
        if count != 'all' and (type(count) is not int or not 1 <= count <= 10000):
            raise ValueError('pair_count must be all or integer 1..10000')
    render = result.setdefault('render', {})
    keys(render, ['resolution', 'samples'], 'render')
    if 'resolution' in render:
        res = render['resolution']
        if not isinstance(res, list) or len(res) != 2 or any(type(v) is not int or not 64 <= v <= 4096 for v in res):
            raise ValueError('render.resolution: two integers 64..4096')
    if 'samples' in render and (type(render['samples']) is not int or not 1 <= render['samples'] <= 1024):
        raise ValueError('render.samples must be integer 1..1024')
    result.setdefault('pair_layout', {'gap': 24})
    keys(result['pair_layout'], ['gap'], 'pair_layout')
    gap = result['pair_layout'].setdefault('gap', 24)
    if type(gap) is not int or not 0 <= gap <= 512:
        raise ValueError('pair_layout.gap must be integer 0..512')
    return result


def pose_key(states, variant):
    return str((tuple((h, tuple(s)) for h, s in sorted(states.items())), variant))


def plan(config):
    config = validate_generation(config)
    rng = random.Random(config['seed'])
    hands = config['active_hands']
    width = 5 * len(hands)
    pairs, images, lookup = [], [], {}

    def image(states, variant):
        key = pose_key(states, variant)
        if key not in lookup:
            image_id = len(images)
            lookup[key] = image_id
            images.append({'image_id': image_id, 'states': states, 'variant': variant,
                           'image': f'images/image_{image_id:05d}.png'})
        return lookup[key]

    for rule in config['rules']:
        name = rule['type']
        options = state_options(width, name)
        capacity = len(options)
        requested = capacity if rule['pair_count'] == 'all' else rule['pair_count']
        if requested > capacity:
            raise ValueError(f'{name}: only {capacity} distinct pairs for selected hands; requested {requested}')
        if requested > 10000 or len(pairs) + requested > 10000:
            raise ValueError('Maximum 10000 pairs per job; choose a smaller pair_count')
        indices = range(capacity) if rule['pair_count'] == 'all' else rng.sample(range(capacity), requested)
        for index in indices:
            flat_a, flat_b = options[index]
            a, b = split_state(flat_a, hands), split_state(flat_b, hands)
            target = {'lighting_l1': 'L1', 'lighting_l2': 'L2', 'stretch': 'LS'}.get(name, 'base')
            pair_id = len(pairs)
            pairs.append({'pair_id': pair_id, 'rule': name, 'active_hands': hands,
                          'input_states': a, 'output_states': b,
                          'flat_input_state': list(flat_a), 'flat_output_state': list(flat_b),
                          'flat_state_order': ('left_to_right_visual' if hands == ['left', 'right'] else 'hand_finger_order'),
                          'input_image_id': image(a, 'base'), 'output_image_id': image(b, target),
                          'pair_image': f'pairs/pair_{pair_id:05d}.png'})
    return {'schema_version': 1, 'config': config, 'pairs': pairs, 'images': images,
            'rule_semantics': {'count_preserve': 'the combined active-hand vector preserves total bent count, changes state; excludes A=A',
                               'shift_one': 'the combined active-hand vector has one straight finger, cyclic right shift by 1',
                               'shift_two': 'the combined active-hand vector has two straight fingers, cyclic right shift by 1',
                               'lighting_l1': 'same poses; Sun world Euler X +30deg and camera world X +30 units from configured base',
                               'lighting_l2': 'same poses; Sun world Euler X -30deg and camera world X -30 units from configured base',
                               'stretch': 'same poses; Sun world Euler Y=60deg and camera world Y=75 units',
                               'inactive_hands': 'preserve configured base scene pose and transforms',
                               'base': 'the scene produced by stage 1; no implicit reset to legacy L0',
                               'double_hand_order': 'left pinky, ring, middle, index, thumb, then right thumb, index, middle, ring, pinky'}}
