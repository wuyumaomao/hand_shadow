"""Render a configured/saved .blend without resetting any hand or light transform."""
import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path


def main():
    worker = '--scene-render-worker' in sys.argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path, required=not worker)
    parser.add_argument('--blender')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--resolution', nargs=2, type=int)
    args = parser.parse_args(sys.argv[sys.argv.index('--scene-render-worker') + 1:] if worker else None)
    if worker:
        import bpy
        scene = bpy.context.scene
        camera = scene.objects.get('Camera.001')
        if camera is None or camera.type != 'CAMERA':
            raise ValueError('Scene must contain Camera.001')
        scene.camera = camera
        scene.render.use_border = False
        scene.render.use_crop_to_border = False
        scene.render.use_compositing = False
        scene.render.use_sequencer = False
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGB'
        if args.resolution:
            scene.render.resolution_x, scene.render.resolution_y = args.resolution
            scene.render.resolution_percentage = 100
        scene.render.filepath = str(args.output / 'image.png')
        if 'FINISHED' not in bpy.ops.render.render(write_still=True):
            raise RuntimeError('Render failed')
        metadata = {'source_scene': bpy.data.filepath, 'camera': camera.name,
                    'image': 'image.png', 'blender_version': bpy.app.version_string,
                    'object_world_matrices': {o.name: [list(row) for row in o.matrix_world] for o in scene.objects}}
        (args.output / 'manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        return
    from configuration import ROOT
    from render_dataset import blender_executable
    if not args.scene.is_file():
        parser.error('Scene does not exist')
    if args.resolution and any(v < 64 or v > 4096 for v in args.resolution):
        parser.error('Resolution dimensions must be 64..4096')
    output = (args.output or ROOT / 'outputs' / uuid.uuid4().hex).resolve()
    output.mkdir(parents=True, exist_ok=False)
    cmd = [blender_executable(args.blender), '--background', str(args.scene.resolve()), '--python-exit-code', '1',
           '--python', str(Path(__file__).resolve()), '--', '--scene-render-worker', '--output', str(output)]
    if args.resolution:
        cmd += ['--resolution', *map(str, args.resolution)]
    print('Output:', output, flush=True)
    with (output / 'render.log').open('wb') as log:
        result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        parser.exit(1, f'Blender exited {result.returncode}; see {output / "render.log"}\n')
    print('Finished:', output / 'image.png')


if __name__ == '__main__':
    main()
