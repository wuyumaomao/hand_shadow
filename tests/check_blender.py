"""Run with Blender --background --python this file; no rendering."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy
from mathutils import Matrix, Euler, Vector
from configuration import SCENES
from scene_controller import SceneController


def close(a, b):
    assert max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4)) < 0.0001, (a, b)


bpy.ops.wm.open_mainfile(filepath=str(SCENES['multi']))
names = ['骨架', '骨架.001', 'Hand_Circle', 'Hand_Circle.001']
before = {n: bpy.data.objects[n].matrix_world.copy() for n in names}
controller = SceneController('multi')
controller.apply({})
for n in names:
    close(bpy.data.objects[n].matrix_world, before[n])
assert bpy.data.objects['骨架.001'].matrix_world.determinant() < 0
pivot = before['骨架.001'].translation
offset = Vector((2, 3, 4))
rot = Euler((0.1, 0.2, 0.3)).to_matrix().to_4x4()
import math
controller.apply({'hands': {'right': {'translation': dict(zip('xyz', offset)),
                                    'rotation_degrees': dict(zip('xyz', [math.degrees(v) for v in (0.1, 0.2, 0.3)])),
                                    'state': [4, 4, 4, 4, 4]}}})
delta = Matrix.Translation(pivot + offset) @ rot @ Matrix.Translation(-pivot)
for n in ['骨架.001', 'Hand_Circle.001']:
    close(bpy.data.objects[n].matrix_world, delta @ before[n])
for n in ['骨架', 'Hand_Circle']:
    close(bpy.data.objects[n].matrix_world, before[n])
assert abs(bpy.data.objects['骨架'].pose.bones['骨骼.013'].rotation_euler.z) < 1e-7
assert abs(bpy.data.objects['骨架.001'].pose.bones['骨骼.013'].rotation_euler.z - math.radians(60)) < 1e-6
controller.apply({'camera': {'position': {'x': 31}}, 'light': {'rotation_degrees': {'x': 30}}})
assert abs(controller.camera.matrix_world.translation.x - 31) < 1e-5
controller.apply({})
close(controller.camera.matrix_world, controller.base_camera)
close(controller.light.matrix_world, controller.base_light)
expected_angles = controller.base_camera_angles.copy()
expected_angles.x = math.radians(190)
loc, _, scale = controller.base_camera.decompose()
controller.apply({'camera': {'rotation_degrees': {'x': 190}}})
close(controller.camera.matrix_world, Matrix.LocRotScale(loc, expected_angles.to_quaternion(), scale))
controller.apply({})
for n in names:
    close(bpy.data.objects[n].matrix_world, before[n])
controller.apply({'hands': {'right': {'enabled': False}}})
assert bpy.data.objects['Hand_Circle.001'].hide_render
controller.apply({})
assert not bpy.data.objects['Hand_Circle.001'].hide_render
print('BLENDER_CHECKS_PASSED: world transforms, mirror, independent poses, reset, visibility', flush=True)
