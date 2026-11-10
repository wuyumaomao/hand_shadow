"""Portable CLI: python render_dataset.py --config configs/multi_hand.json."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from configuration import ROOT, SCENES, capabilities, validate


def blender_executable(explicit=None):
    candidate = explicit or os.environ.get('BLENDER_EXE') or shutil.which('blender')
    if candidate and Path(candidate).is_file():
        return str(Path(candidate).resolve())
    raise ValueError('Blender not found. Set BLENDER_EXE or pass --blender with its executable path.')


def worker_command(exe, config_path, output, configure_only=False):
    command = [exe, '--background', '--python-exit-code', '1', '--python',
               str(ROOT / 'blender_worker.py'), '--', '--config', str(config_path), '--output', str(output)]
    return command + (['--configure-only'] if configure_only else [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--blender')
    parser.add_argument('--output', type=Path, help='Must be a new directory')
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--configure-only', action='store_true', help='Save configured blend snapshots without rendering')
    parser.add_argument('--capabilities', action='store_true')
    args = parser.parse_args()
    if args.capabilities:
        print(json.dumps(capabilities(), ensure_ascii=False, indent=2))
        return
    if not args.config:
        parser.error('--config is required')
    try:
        config = validate(json.loads(args.config.read_text(encoding='utf-8-sig')))
        if not SCENES[config['mode']].is_file():
            raise ValueError('Scene preset missing: ' + str(SCENES[config['mode']]))
        if args.validate_only:
            print(f'Valid: mode={config["mode"]}, images={len(config["samples"])}')
            return
        exe = blender_executable(args.blender)
        output = (args.output or ROOT / 'outputs' / uuid.uuid4().hex).resolve()
        output.mkdir(parents=True, exist_ok=False)
        config_path = output / 'request.json'
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Output:', output, flush=True)
        with (output / 'render.log').open('wb') as log:
            process = subprocess.Popen(worker_command(exe, config_path, output, args.configure_only),
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    text = line.decode('utf-8', errors='replace').strip()
                    if text.startswith('PROGRESS'):
                        print(text, flush=True)
                code = process.wait()
                process.stdout.close()
            except KeyboardInterrupt:
                process.terminate()
                process.wait()
                raise
        if code:
            raise RuntimeError(f'Blender exited {code}; see {output / "render.log"}')
        print('Finished:', output / 'manifest.json')
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
