"""Actual HTTP -> Blender -> PNG/snapshot integration; uses temporary outputs."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api_server import Jobs, handler, ThreadingHTTPServer


@unittest.skipUnless(os.environ.get('BLENDER_EXE'), 'Set BLENDER_EXE for Blender integration test')
class ApiIntegration(unittest.TestCase):
    def test_real_jobs(self):
        with tempfile.TemporaryDirectory(prefix='shadow-api-') as folder:
            jobs = Jobs(os.environ['BLENDER_EXE'], Path(folder))
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(jobs))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'

            def request(route, body=None):
                data = json.dumps(body).encode() if body is not None else None
                req = urllib.request.Request(base + route, data=data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    return response.status, response.read()

            def run(config, action='render', scene_job_id=None):
                body = {'config': config, 'action': action}
                if scene_job_id:
                    body['scene_job_id'] = scene_job_id
                code, data = request('/jobs', body)
                self.assertEqual(code, 202)
                job_id = json.loads(data)['id']
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    _, data = request('/jobs/' + job_id)
                    status = json.loads(data)
                    if status['status'] in ['succeeded', 'failed', 'cancelled']:
                        break
                    time.sleep(0.2)
                self.assertEqual(status['status'], 'succeeded', status)
                filename = 'pairs.json' if action == 'pairs' else 'manifest.json'
                _, manifest = request('/jobs/' + job_id + '/files/' + filename)
                return job_id, json.loads(manifest)

            try:
                # Simulate a user deleting the output root while the server remains up.
                import shutil
                shutil.rmtree(folder)
                code, data = request('/jobs', {'config': {'mode': 'multi', 'samples': [{}]}, 'action': 'configure'})
                self.assertEqual(code, 202)
                recovered_job = json.loads(data)['id']
                recovered = wait_for_job = None
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    recovered = json.loads(request('/jobs/' + recovered_job)[1])
                    if recovered['status'] in ['succeeded', 'failed', 'cancelled']:
                        break
                    time.sleep(0.2)
                self.assertEqual(recovered['status'], 'succeeded', recovered)
                self.assertEqual(request('/health')[0], 200)
                self.assertEqual(urllib.request.urlopen(base + '/').status, 200)
                bootstrap = json.loads(request('/ui/bootstrap')[1])
                self.assertIn('camera', bootstrap['presets']['multi'])
                self.assertEqual(request('/ui/validate-scene', {'config': bootstrap['scene']})[0], 200)
                self.assertEqual(json.loads(request('/capabilities')[1])['camera'], 'Camera.001')
                with self.assertRaises(urllib.error.HTTPError) as bad:
                    request('/jobs', {'config': {'mode': 'bad'}})
                self.assertEqual(bad.exception.code, 400)
                for mode in ['single', 'multi']:
                    config = {'mode': mode, 'render': {'resolution': [256, 256], 'samples': 8},
                              'light': {'rotation_degrees': {'x': 0, 'y': 30}},
                              'samples': [{}, {'hands': {'left': {'state': [4] * 5}}}]}
                    job_id, manifest = run(config)
                    self.assertEqual(len(manifest['images']), 2)
                    _, image = request(f'/jobs/{job_id}/files/image_00000.png')
                    self.assertTrue(image.startswith(b'\x89PNG\r\n\x1a\n'))
                    self.assertNotEqual((Path(folder) / job_id / 'image_00000.png').read_bytes(),
                                        (Path(folder) / job_id / 'image_00001.png').read_bytes())
                    # Copy actual previews to the project for visual QA.
                    import shutil
                    qa = Path(__file__).resolve().parents[1] / 'outputs' / 'verified_previews'
                    qa.mkdir(parents=True, exist_ok=True)
                    for i in range(2):
                        shutil.copyfile(Path(folder) / job_id / f'image_{i:05d}.png', qa / f'{mode}_{i}.png')
                scene_job, manifest = run({'mode': 'multi', 'hands': {
                    'left': {'translation': {'x': -2}, 'rotation_degrees': {'z': 5}},
                    'right': {'translation': {'x': 2}, 'state': [4, 0, 0, 4, 4]}}}, 'configure')
                self.assertIn('scene', manifest['images'][0])
                self.assertNotIn('image', manifest['images'][0])
                from pair_rules import RULES
                pair_job, pairs = run({'rules': [{'type': rule, 'pair_count': 1} for rule in RULES],
                                       'render': {'resolution': [128, 128], 'samples': 8}}, 'pairs', scene_job)
                self.assertEqual(pairs['pair_count'], 6)
                _, pair_png = request(f'/jobs/{pair_job}/files/pairs/pair_00000.png')
                self.assertTrue(pair_png.startswith(b'\x89PNG'))
                render_manifest = json.loads(request(f'/jobs/{pair_job}/files/render_manifest.json')[1])
                base_matrices = render_manifest['base_world_matrices']
                first_right_pose = render_manifest['images'][0]['actual']['joint_angles_degrees']['骨架.001']
                self.assertAlmostEqual(first_right_pose['thumb'][0], -20, places=4)
                for image_record in render_manifest['images']:
                    matrices = image_record['actual']['world_matrices']
                    for rig_name in ['骨架', '骨架.001']:
                        self.assertEqual(matrices[rig_name], base_matrices[rig_name])
                    self.assertEqual(image_record['actual']['joint_angles_degrees']['骨架.001'], first_right_pose)
                    expected_x = base_matrices['Camera.001'][0][3] + {'L1': 30, 'L2': -30}.get(image_record['variant'], 0)
                    self.assertAlmostEqual(matrices['Camera.001'][0][3], expected_x, places=4)
                    if image_record['variant'] == 'LS':
                        self.assertAlmostEqual(matrices['Camera.001'][1][3], 75, places=4)
                queued = jobs.submit({'config': {'samples': [{}] * 10}})
                status = jobs.cancel(queued['id'])
                self.assertEqual(status['status'], 'cancelled')
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    request('/jobs/not-a-job')
                self.assertEqual(missing.exception.code, 404)
            finally:
                server.shutdown()
                jobs.shutdown()
                # Let subprocesses release files before removing temporary directory on Windows.
                with jobs.lock:
                    processes = list(jobs.processes.values())
                for process in processes:
                    process.wait(timeout=15)
                server.server_close()
                jobs.queue.join()


if __name__ == '__main__':
    unittest.main()
