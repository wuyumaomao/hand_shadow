"""Refresh UI defaults from bundled .blend files. Run this script inside Blender."""
import json
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
from configuration import ROOT, SCENES


def main():
    result = {}
    for mode, path in SCENES.items():
        bpy.ops.wm.open_mainfile(filepath=str(path))
        config = {'mode': mode, 'hands': {}, 'seed': 42,
                  'render': {'resolution': [512, 512], 'samples': 32}}
        for hand in ['left'] if mode == 'single' else ['left', 'right']:
            config['hands'][hand] = {'enabled': True, 'translation': dict.fromkeys('xyz', 0),
                                     'rotation_degrees': dict.fromkeys('xyz', 0), 'state': [0] * 5}
        for field, name in [('camera', 'Camera.001'), ('light', '日光')]:
            obj = bpy.context.scene.objects[name]
            config[field] = {'position': dict(zip('xyz', obj.matrix_world.translation)),
                             'rotation_degrees': dict(zip('xyz', [math.degrees(v) for v in obj.matrix_world.to_euler('XYZ', obj.rotation_euler)]))}
        # Standard L0 source: retain camera Y/Z and rotation, use scene-specific framing X.
        config['camera']['position']['x'] = 0 if mode == 'single' else 7
        config['light']['rotation_degrees']['x'] = 0
        config['light']['rotation_degrees']['y'] = 30
        result[mode] = config
    (ROOT / 'configs/scene_presets.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
