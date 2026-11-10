"""Shared JSON contract; no Blender or third-party Python dependency."""
import copy
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCENES = {'single': ROOT / 'scenes/single_hand.blend',
          'multi': ROOT / 'scenes/multi_hand.blend'}
HANDS = {'left': {'rig': '骨架', 'meshes': ['Hand_Circle']},
         'right': {'rig': '骨架.001', 'meshes': ['Hand_Circle.001']}}
FINGERS = {'thumb': ['骨骼.016', '骨骼.017'],
           'index': ['骨骼.013', '骨骼.014', '骨骼.015'],
           'middle': ['骨骼.010', '骨骼.012', '骨骼.011'],
           'ring': ['骨骼.007', '骨骼.009', '骨骼.008'],
           'pinky': ['骨骼.004', '骨骼.005', '骨骼.006']}
DEFAULT_ANGLES = {f: [-20, -40] if f == 'thumb' else [60, 80, 60] for f in FINGERS}


def merge(base, patch):
    result = copy.deepcopy(base)
    for key, value in patch.items():
        result[key] = merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else copy.deepcopy(value)
    return result


def keys(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label}: expected object')
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f'{label}: unknown fields {sorted(unknown)}')


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label}: expected finite number')


def axes(value, label):
    keys(value, ['x', 'y', 'z'], label)
    for axis, v in value.items():
        number(v, f'{label}.{axis}')


def validate_controls(value, label):
    keys(value, ['hands', 'camera', 'light'], label)
    hands = value.get('hands', {})
    keys(hands, HANDS, label + '.hands')
    for name, hand in hands.items():
        keys(hand, ['enabled', 'translation', 'rotation_degrees', 'state', 'bend_angles'], name)
        if 'enabled' in hand and type(hand['enabled']) is not bool:
            raise ValueError(f'{name}.enabled: expected boolean')
        for field in ['translation', 'rotation_degrees']:
            if field in hand:
                axes(hand[field], name + '.' + field)
        if 'state' in hand:
            state = hand['state']
            if not isinstance(state, list) or len(state) != 5 or any(type(v) is not int or v not in [0, 4] for v in state):
                raise ValueError(f'{name}.state: expected five integers 0 or 4')
        if 'bend_angles' in hand:
            keys(hand['bend_angles'], FINGERS, name + '.bend_angles')
            for finger, angles in hand['bend_angles'].items():
                limits = [(-30, 40), (-80, 20)] if finger == 'thumb' else [(0, 90)] * 3
                if not isinstance(angles, list) or len(angles) != len(limits):
                    raise ValueError(f'{finger}: wrong angle count')
                for angle, (low, high) in zip(angles, limits):
                    if type(angle) is not int or angle % 10 or not low <= angle <= high:
                        raise ValueError(f'{finger}: angles must be multiples of 10 within {limits}')
    if 'camera' in value:
        keys(value['camera'], ['position', 'rotation_degrees'], label + '.camera')
        for field, v in value['camera'].items():
            axes(v, 'camera.' + field)
    if 'light' in value:
        keys(value['light'], ['position', 'rotation_degrees'], label + '.light')
        for field, v in value['light'].items():
            axes(v, 'light.' + field)


def validate(config):
    keys(config, ['mode', 'hands', 'camera', 'light', 'render', 'samples', 'seed', 'save_scene'], 'config')
    result = copy.deepcopy(config)
    result.setdefault('mode', 'single')
    if not isinstance(result['mode'], str) or result['mode'] not in SCENES:
        raise ValueError('mode must be single or multi')
    validate_controls({k: v for k, v in result.items() if k in ['hands', 'camera', 'light']}, 'config')
    result.setdefault('seed', 42)
    if type(result['seed']) is not int or not 0 <= result['seed'] < 2**31:
        raise ValueError('seed must be an integer in [0, 2147483647]')
    result.setdefault('save_scene', False)
    if type(result['save_scene']) is not bool:
        raise ValueError('save_scene must be boolean')
    render = result.setdefault('render', {})
    keys(render, ['resolution', 'samples'], 'render')
    render.setdefault('resolution', [1080, 1080])
    render.setdefault('samples', 32)
    res = render['resolution']
    if not isinstance(res, list) or len(res) != 2 or any(type(v) is not int or not 64 <= v <= 4096 for v in res):
        raise ValueError('render.resolution: two integer dimensions from 64 to 4096')
    if type(render['samples']) is not int or not 1 <= render['samples'] <= 1024:
        raise ValueError('render.samples must be integer 1..1024')
    result.setdefault('samples', [{}])
    if not isinstance(result['samples'], list) or not 1 <= len(result['samples']) <= 10000:
        raise ValueError('samples must contain 1..10000 sample overrides')
    for i, sample in enumerate(result['samples']):
        validate_controls(sample, f'samples[{i}]')
        effective = merge({k: result[k] for k in ['hands', 'camera', 'light'] if k in result}, sample)
        if result['mode'] == 'single' and effective.get('hands', {}).get('right', {}).get('enabled', False):
            raise ValueError('right hand cannot be enabled in single mode')
    return result


def capabilities():
    return {'schema_version': 1, 'modes': list(SCENES), 'hands': HANDS,
            'camera': 'Camera.001', 'light': '日光', 'finger_order': list(FINGERS),
            'state_values': [0, 4], 'default_bend_angles_degrees': DEFAULT_ANGLES,
            'hand_transform': 'world-axis offsets from base scene; rotation pivot = original rig origin',
            'camera_and_light_transform': 'absolute world coordinates / XYZ Euler degrees; unspecified axes preserved',
            'single_hand': 'left (original rig); left/right identifiers follow scene placement, not anatomical classification',
            'sample_overrides': 'deep-merged over base config, independently reset each image',
            'seed': 'render seed only; poses are explicitly configured, not randomly sampled',
            'examples': ['configs/scene_config.json', 'configs/generation_config.json', 'configs/single_hand.json', 'configs/multi_hand.json'],
            'api_actions': ['configure', 'render', 'pairs'],
            'pair_rules': ['count_preserve', 'shift_one', 'shift_two', 'lighting_l1', 'lighting_l2', 'stretch'],
            'pairs_request': 'action=pairs, config=generation config, scene_job_id=succeeded configure job id'}
