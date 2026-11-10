"""Stage 1: save one configured scene; do not render or vary gestures."""
import argparse
import json
import subprocess
import uuid
from pathlib import Path
from configuration import ROOT, validate
from render_dataset import blender_executable, worker_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/scene_config.json')
    parser.add_argument('--blender')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.config.read_text(encoding='utf-8-sig'))
        if 'samples' in value:
            raise ValueError('Stage 1 scene config must not contain samples; use generation_config.json for variation')
        config = validate(value)
        executable = blender_executable(args.blender)
        output = (args.output or ROOT / 'outputs' / ('scene_' + uuid.uuid4().hex)).resolve()
        output.mkdir(parents=True, exist_ok=False)
        request = output / 'request.json'
        request.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        with (output / 'configure.log').open('wb') as log:
            result = subprocess.run(worker_command(executable, request, output, True), stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'Blender exited {result.returncode}; see {output / "configure.log"}')
        scene = output / 'scene_00000.blend'
        if not scene.is_file():
            raise RuntimeError('Configured scene not produced')
        pointer = ROOT / 'outputs/latest_scene.json'
        pointer.parent.mkdir(parents=True, exist_ok=True)
        temp = pointer.with_name('latest_scene.' + uuid.uuid4().hex + '.tmp')
        temp.write_text(json.dumps({'scene': str(scene), 'scene_config': str(output / 'config.json')}, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(pointer)
        print('Configured scene:', scene)
        print('Stage 2 will use this scene automatically unless --scene is specified.')
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
