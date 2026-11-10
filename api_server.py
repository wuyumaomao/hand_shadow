"""Local JSON/HTTP interface. One Blender job at a time; Python standard library."""
import argparse
import json
import mimetypes
import queue
import re
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
from pair_rules import plan as pair_plan
from generate_dataset import command as pair_command, finish_pairs, check_dependencies
from configuration import ROOT, capabilities, validate
from render_dataset import blender_executable, worker_command


def now():
    return datetime.now(timezone.utc).isoformat()


class Jobs:
    def __init__(self, exe, directory):
        self.exe, self.directory = exe, directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock, self.queue = threading.RLock(), queue.Queue()
        self.records, self.processes = {}, {}
        for folder in self.directory.iterdir():
            if folder.is_dir() and (folder / 'status.json').is_file():
                record = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
                if record['status'] in ['queued', 'running']:
                    record.update(status='failed', error='Server stopped before task finished', finished_at=now())
                    self.save(record)
                self.records[record['id']] = record
        threading.Thread(target=self.work, daemon=True).start()

    def save(self, record):
        folder = self.directory / record['id']
        tmp = folder / 'status.tmp'
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(folder / 'status.json')

    def submit(self, request):
        if not isinstance(request, dict) or set(request) - {'config', 'action', 'scene_job_id'} or 'config' not in request:
            raise ValueError('Expected {"config": {...}, "action": "render", "configure" or "pairs"}')
        action = request.get('action', 'render')
        if action not in ['render', 'configure', 'pairs']:
            raise ValueError('action must be render, configure or pairs')
        source_scene = None
        if action == 'pairs':
            planned = pair_plan(request['config'])
            config = planned['config']
            check_dependencies()
            previous = self.get(request.get('scene_job_id', ''))
            source_scene = self.directory / previous['id'] / 'scene_00000.blend'
            if previous['status'] != 'succeeded' or not source_scene.is_file():
                raise ValueError('scene_job_id must identify a succeeded job containing scene_00000.blend')
            count = len(planned['images'])
        else:
            config = validate(request['config'])
            if action == 'configure' and len(config['samples']) != 1:
                raise ValueError('Stage 1 configure requires a single sample')
            count = len(config['samples'])
        job_id = uuid.uuid4().hex
        folder = self.directory / job_id
        # The output root may be removed manually while the server stays alive.
        # Recreate it before allocating the per-job directory.
        self.directory.mkdir(parents=True, exist_ok=True)
        folder.mkdir(parents=False, exist_ok=False)
        (folder / 'request.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        record = {'id': job_id, 'status': 'queued', 'action': action, 'created_at': now(),
                  'completed_images': 0, 'total_images': count,
                  'output_directory': str(folder), 'error': None}
        if source_scene:
            record['source_scene'] = str(source_scene)
        with self.lock:
            self.records[job_id] = record
            self.save(record)
            self.queue.put(job_id)
            return dict(record)

    def get(self, job_id):
        with self.lock:
            return dict(self.records[job_id])

    def cancel(self, job_id):
        with self.lock:
            record = self.records[job_id]
            if record['status'] in ['queued', 'running']:
                record.update(status='cancelled', finished_at=now())
                if job_id in self.processes:
                    self.processes[job_id].terminate()
                self.save(record)
            return dict(record)

    def work(self):
        while True:
            job_id = self.queue.get()
            folder = self.directory / job_id
            try:
                with self.lock:
                    record = self.records[job_id]
                    if record['status'] == 'cancelled':
                        continue
                    if record['action'] == 'pairs':
                        planned = pair_plan(json.loads((folder / 'request.json').read_text(encoding='utf-8')))
                        plan_path = folder / 'plan.json'
                        plan_path.write_text(json.dumps(planned, ensure_ascii=False, indent=2), encoding='utf-8')
                        cmd = pair_command(self.exe, record['source_scene'], plan_path, folder)
                    else:
                        cmd = worker_command(self.exe, folder / 'request.json', folder, record['action'] == 'configure')
                    process = subprocess.Popen(cmd,
                                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    self.processes[job_id] = process
                    record.update(status='running', started_at=now())
                    self.save(record)
                with (folder / 'render.log').open('wb') as log:
                    for line in process.stdout:
                        log.write(line)
                        log.flush()
                        match = re.match(rb'PROGRESS (\d+)/(\d+)', line)
                        if match:
                            with self.lock:
                                record['completed_images'] = int(match[1])
                                self.save(record)
                code = process.wait()
                process.stdout.close()
                if code == 0 and record['action'] == 'pairs' and record['status'] != 'cancelled':
                    finish_pairs(folder, planned)
                with self.lock:
                    if record['status'] != 'cancelled':
                        record.update(status='succeeded' if code == 0 else 'failed', finished_at=now())
                        if code:
                            record['error'] = f'Blender exited {code}; read render.log'
                    self.save(record)
            except Exception as exc:
                with self.lock:
                    record = self.records[job_id]
                    if record['status'] != 'cancelled':
                        record.update(status='failed', error=str(exc), finished_at=now())
                    self.save(record)
            finally:
                with self.lock:
                    self.processes.pop(job_id, None)
                self.queue.task_done()

    def shutdown(self):
        with self.lock:
            for job_id in self.records:
                if self.records[job_id]['status'] in ['queued', 'running']:
                    self.cancel(job_id)


def handler(jobs):
    class Handler(BaseHTTPRequestHandler):
        def json(self, code, value):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parts = self.path.split('?', 1)[0].strip('/').split('/')
            static = {'': ('index.html', 'text/html'), 'app.js': ('app.js', 'text/javascript'),
                      'style.css': ('style.css', 'text/css')}
            if len(parts) == 1 and parts[0] in static:
                filename, content_type = static[parts[0]]
                data = (ROOT / 'web' / filename).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', content_type + '; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                return self.wfile.write(data)
            if parts == ['ui', 'bootstrap']:
                presets = json.loads((ROOT / 'configs/scene_presets.json').read_text(encoding='utf-8'))
                scene = json.loads((ROOT / 'configs/scene_config.json').read_text(encoding='utf-8-sig'))
                generation = json.loads((ROOT / 'configs/generation_config.json').read_text(encoding='utf-8-sig'))
                from configuration import merge
                return self.json(200, {'scene': merge(presets[scene.get('mode', 'multi')], scene),
                                       'presets': presets, 'generation': generation})
            if parts == ['capabilities']:
                return self.json(200, capabilities())
            if parts == ['health']:
                return self.json(200, {'status': 'ok'})
            if len(parts) >= 2 and parts[0] == 'jobs':
                try:
                    record = jobs.get(parts[1])
                except KeyError:
                    return self.json(404, {'error': 'Job not found'})
                folder = jobs.directory / record['id']
                if len(parts) == 2:
                    record['files'] = [p.name for p in folder.iterdir() if p.is_file() and p.suffix in ['.png', '.json', '.log', '.blend']]
                    return self.json(200, record)
                if len(parts) in [4, 5] and parts[2] == 'files':
                    # Only immediate regular files generated in this job; no path traversal.
                    if len(parts) == 5 and parts[3] not in ['images', 'pairs']:
                        return self.json(400, {'error': 'Invalid file folder'})
                    filename = parts[-1]
                    if not re.fullmatch(r'[A-Za-z0-9_.-]+', filename) or filename in ['.', '..']:
                        return self.json(400, {'error': 'Invalid filename'})
                    file = folder / parts[3] / filename if len(parts) == 5 else folder / filename
                    if not file.is_file() or file.suffix not in ['.png', '.json', '.log', '.blend']:
                        return self.json(404, {'error': 'File not found'})
                    self.send_response(200)
                    self.send_header('Content-Type', mimetypes.guess_type(filename)[0] or 'application/octet-stream')
                    self.send_header('Content-Length', str(file.stat().st_size))
                    self.end_headers()
                    with file.open('rb') as stream:
                        import shutil
                        shutil.copyfileobj(stream, self.wfile)
                    return
            self.json(404, {'error': 'Route not found'})

        def do_POST(self):
            parts = self.path.split('?', 1)[0].strip('/').split('/')
            try:
                if parts in [['jobs'], ['ui', 'validate-scene']]:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 8 * 1024 * 1024:
                        return self.json(413, {'error': 'Body must be 1 byte..8 MiB'})
                    body = json.loads(self.rfile.read(length).decode('utf-8-sig'))
                    if parts == ['ui', 'validate-scene']:
                        if not isinstance(body, dict) or set(body) != {'config'}:
                            raise ValueError('Expected {"config": scene configuration}')
                        config = validate(body['config'])
                        if len(config['samples']) != 1 or config['samples'][0]:
                            raise ValueError('Stage 1 config cannot contain sample overrides')
                        return self.json(200, {'config': config})
                    return self.json(202, jobs.submit(body))
                if len(parts) == 3 and parts[0] == 'jobs' and parts[2] == 'cancel':
                    return self.json(200, jobs.cancel(parts[1]))
                self.json(404, {'error': 'Route not found'})
            except KeyError:
                self.json(404, {'error': 'Job not found'})
            except (ValueError, UnicodeError, TypeError) as exc:
                self.json(400, {'error': str(exc)})
            except OSError as exc:
                self.json(500, {'error': f'后端无法创建任务目录：{exc}'})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--jobs-dir', type=Path, default=ROOT / 'outputs')
    args = parser.parse_args()
    jobs = Jobs(blender_executable(args.blender), args.jobs_dir)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(jobs))
    print(f'Listening on http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        jobs.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
