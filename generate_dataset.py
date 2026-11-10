"""Stage 2: render rule-based input/output pairs from an already configured scene."""
import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path
from configuration import ROOT
from pair_rules import plan
from render_dataset import blender_executable


def command(executable, scene, plan_path, output):
    return [executable, '--background', str(scene), '--python-exit-code', '1', '--python',
            str(ROOT / 'generate_pairs_worker.py'), '--', '--plan', str(plan_path), '--output', str(output)]


def check_dependencies():
    try:
        import PIL
    except ImportError as exc:
        raise ValueError('Pair composition needs Pillow: python -m pip install -r requirements.txt') from exc


def finish_pairs(output, planned):
    from PIL import Image
    output = Path(output)
    (output / 'pairs').mkdir(exist_ok=True)
    rendered = json.loads((output / 'render_manifest.json').read_text(encoding='utf-8'))
    images = {r['image_id']: r for r in rendered['images']}
    if len(images) != len(planned['images']):
        raise RuntimeError('Incomplete render; will not publish pairs.json')
    records = []
    gap = planned['config']['pair_layout']['gap']
    for pair in planned['pairs']:
        left, right = images[pair['input_image_id']], images[pair['output_image_id']]
        with Image.open(output / left['image']) as a, Image.open(output / right['image']) as b:
            canvas = Image.new('RGB', (a.width + gap + b.width, max(a.height, b.height)), 'white')
            canvas.paste(a.convert('RGB'), (0, 0))
            canvas.paste(b.convert('RGB'), (a.width + gap, 0))
            canvas.save(output / pair['pair_image'])
        record = dict(pair, input_image=left['image'], output_image=right['image'],
                      input_variant=left['variant'], output_variant=right['variant'])
        records.append(record)
        (output / Path(pair['pair_image']).with_suffix('.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'pairs.json').write_text(json.dumps({'source_scene': rendered['source_scene'],
        'source_sha256': rendered['source_sha256'], 'config': planned['config'],
        'rule_semantics': planned['rule_semantics'], 'pair_count': len(records), 'pairs': records}, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/generation_config.json')
    parser.add_argument('--scene', type=Path, help='Defaults to most recent stage 1 scene')
    parser.add_argument('--blender')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--plan-only', action='store_true', help='Inspect rule counts without rendering')
    args = parser.parse_args()
    try:
        planned = plan(json.loads(args.config.read_text(encoding='utf-8-sig')))
        from collections import Counter
        print('Pairs by rule:', dict(Counter(p['rule'] for p in planned['pairs'])))
        print('Total pairs:', len(planned['pairs']), '| Unique render images:', len(planned['images']))
        if args.plan_only:
            return
        check_dependencies()
        scene = args.scene
        if scene is None:
            pointer = ROOT / 'outputs/latest_scene.json'
            if not pointer.is_file():
                raise ValueError('Run configure_scene.py first, or specify --scene')
            scene = Path(json.loads(pointer.read_text(encoding='utf-8'))['scene'])
        scene = scene.resolve()
        if not scene.is_file() or scene.suffix.lower() != '.blend':
            raise ValueError('Configured .blend scene not found: ' + str(scene))
        executable = blender_executable(args.blender)
        output = (args.output or ROOT / 'outputs' / ('pairs_' + uuid.uuid4().hex)).resolve()
        output.mkdir(parents=True, exist_ok=False)
        request = output / 'generation_config.json'
        request.write_text(json.dumps(planned['config'], ensure_ascii=False, indent=2), encoding='utf-8')
        plan_path = output / 'plan.json'
        plan_path.write_text(json.dumps(planned, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Source scene:', scene, flush=True)
        print('Output:', output, flush=True)
        with (output / 'render.log').open('wb') as log:
            process = subprocess.Popen(command(executable, scene, plan_path, output), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    text = line.decode('utf-8', errors='replace').strip()
                    if text.startswith('PROGRESS'):
                        print(text, flush=True)
                code = process.wait()
            except KeyboardInterrupt:
                process.terminate()
                process.wait()
                raise
            finally:
                process.stdout.close()
        if code:
            raise RuntimeError(f'Blender exited {code}; see {output / "render.log"}')
        finish_pairs(output, planned)
        print('Finished:', output / 'pairs.json')
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
