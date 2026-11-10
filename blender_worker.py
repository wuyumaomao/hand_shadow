"""Blender subprocess entry point; always loads a pristine scene preset."""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
from configuration import SCENES, merge, validate
from scene_controller import SceneController


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--configure-only', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    config = validate(json.loads(Path(args.config).read_text(encoding='utf-8-sig')))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    source = SCENES[config['mode']]
    bpy.ops.wm.open_mainfile(filepath=str(source))
    controller = SceneController(config['mode'])
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = config['render']['resolution']
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.use_file_extension = True
    scene.render.use_border = False
    scene.render.use_crop_to_border = False
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    random.seed(config['seed'])
    if hasattr(scene, 'cycles'):
        scene.cycles.seed = config['seed']
        scene.cycles.samples = config['render']['samples']
    if hasattr(scene, 'eevee') and hasattr(scene.eevee, 'taa_render_samples'):
        scene.eevee.taa_render_samples = config['render']['samples']
    if hasattr(scene, 'eevee') and hasattr(scene.eevee, 'taa_samples'):
        scene.eevee.taa_samples = config['render']['samples']
    records = []
    save_json(output / 'config.json', config)
    base = {k: config[k] for k in ['hands', 'camera', 'light'] if k in config}
    import hashlib
    manifest = {'schema_version': 1, 'mode': config['mode'], 'source_scene': str(source),
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'blender_version': bpy.app.version_string, 'seed': config['seed'],
                'render': config['render'], 'camera': 'Camera.001', 'images': records}
    for i, patch in enumerate(config['samples']):
        effective = merge(base, patch)
        controller.apply(effective)
        scene['hand_shadow_scene_config'] = json.dumps(dict(config, hands=effective.get('hands', {})), ensure_ascii=False)
        record = {'index': i, 'configuration': effective, 'actual': controller.snapshot()}
        if not args.configure_only:
            filename = f'image_{i:05d}.png'
            scene.render.filepath = str(output / filename)
            if 'FINISHED' not in bpy.ops.render.render(write_still=True) or not (output / filename).is_file():
                raise RuntimeError('Render failed: ' + filename)
            record['image'] = filename
        if config['save_scene'] or args.configure_only:
            filename = f'scene_{i:05d}.blend'
            bpy.ops.wm.save_as_mainfile(filepath=str(output / filename), copy=True)
            record['scene'] = filename
        records.append(record)
        save_json(output / 'manifest.json', manifest)
        print(f'PROGRESS {i+1}/{len(config["samples"])}', flush=True)


if __name__ == '__main__':
    main()
