"""Stage 2 Blender worker: vary poses/light only, preserve configured layout."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
from mathutils import Matrix
from configuration import HANDS, FINGERS, DEFAULT_ANGLES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    scene = bpy.context.scene
    camera, light = scene.objects.get('Camera.001'), scene.objects.get('日光')
    if camera is None or camera.type != 'CAMERA' or light is None or light.type != 'LIGHT' or light.data.type != 'SUN':
        raise ValueError('Configured scene needs Camera.001 and SUN 日光')
    scene.camera = camera
    hands = {}
    for name in plan['config']['active_hands']:
        binding = HANDS[name]
        rig = scene.objects.get(binding['rig'])
        meshes = [scene.objects.get(n) for n in binding['meshes']]
        if rig is None or rig.type != 'ARMATURE' or any(m is None or m.hide_render for m in meshes):
            raise ValueError(f'{name}: active hand missing or hidden in configured scene')
        if any(n not in rig.pose.bones for names in FINGERS.values() for n in names):
            raise ValueError(f'{name}: missing finger bones')
        if any(not any(m.type == 'ARMATURE' and m.object == rig for m in mesh.modifiers) for mesh in meshes):
            raise ValueError(f'{name}: wrong armature modifier')
        hands[name] = rig
    base = {o.name: o.matrix_world.copy() for o in scene.objects}
    camera_position, camera_rotation, camera_scale = camera.matrix_world.decompose()
    light_position, _, light_scale = light.matrix_world.decompose()
    light_angles = light.matrix_world.to_euler('XYZ', light.rotation_euler)
    # Restore exact base pose before every unique image, including untouched hands.
    rigs = [o for o in scene.objects if o.type == 'ARMATURE']
    poses = {r.name: {b.name: b.matrix_basis.copy() for b in r.pose.bones} for r in rigs}
    # Configured snapshots retain angles even when the initial state is open.
    scene_config = json.loads(scene.get('hand_shadow_scene_config', '{}'))
    angles = {h: scene_config.get('hands', {}).get(h, {}).get('bend_angles', {}) for h in hands}
    for obj in [camera, light, *rigs]:
        obj.animation_data_clear()
    for obj in scene.objects:
        if obj.type == 'LIGHT':
            obj.hide_render = obj != light
    for rig in rigs:
        rig.data.pose_position = 'POSE'
    render = plan['config']['render']
    if 'resolution' in render:
        scene.render.resolution_x, scene.render.resolution_y = render['resolution']
        scene.render.resolution_percentage = 100
    if hasattr(scene, 'cycles'):
        scene.cycles.seed = plan['config']['seed']
        if 'samples' in render:
            scene.cycles.samples = render['samples']
    if 'samples' in render and hasattr(scene, 'eevee'):
        for attribute in ['taa_render_samples', 'taa_samples']:
            if hasattr(scene.eevee, attribute):
                setattr(scene.eevee, attribute, render['samples'])
    scene.render.use_border = False
    scene.render.use_crop_to_border = False
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    scene.render.use_file_extension = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    records = []
    output = args.output
    (output / 'images').mkdir(exist_ok=True)
    metadata = {'source_scene': bpy.data.filepath, 'source_sha256': hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
                'blender_version': bpy.app.version_string, 'camera': camera.name, 'base_world_matrices': {n: [list(row) for row in m] for n, m in base.items()},
                'configured_scene': scene_config, 'images': records}
    for spec in plan['images']:
        for rig in rigs:
            for bone in rig.pose.bones:
                bone.matrix_basis = poses[rig.name][bone.name]
        camera.matrix_world = base[camera.name].copy()
        light.matrix_world = base[light.name].copy()
        for name, state in spec['states'].items():
            rig = hands[name]
            for bone in rig.pose.bones:
                bone.rotation_mode = 'XYZ'
                bone.rotation_euler = (0, 0, 0)
                bone.location = (0, 0, 0)
                bone.scale = (1, 1, 1)
            for bit, (finger, names) in zip(state, FINGERS.items()):
                for bone, angle in zip(names, angles[name].get(finger, DEFAULT_ANGLES[finger])):
                    rig.pose.bones[bone].rotation_euler[0 if finger == 'thumb' else 2] = math.radians(angle if bit else 0)
        variant = spec['variant']
        position, rotation = camera_position.copy(), light_angles.copy()
        if variant in ['L1', 'L2']:
            direction = 1 if variant == 'L1' else -1
            rotation.x += math.radians(30) * direction
            position.x += 30 * direction
        elif variant == 'LS':
            rotation.y = math.radians(60)
            position.y = 75
        if variant != 'base':
            camera.matrix_world = Matrix.LocRotScale(position, camera_rotation, camera_scale)
            light.matrix_world = Matrix.LocRotScale(light_position, rotation.to_quaternion(), light_scale)
        bpy.context.view_layer.update()
        scene.render.filepath = str(output / spec['image'])
        if 'FINISHED' not in bpy.ops.render.render(write_still=True):
            raise RuntimeError('Rendering failed')
        actual = {'world_matrices': {o.name: [list(row) for row in o.matrix_world] for o in [camera, light, *rigs]},
                  'joint_angles_degrees': {r.name: {f: [math.degrees(r.pose.bones[n].rotation_euler[0 if f == 'thumb' else 2]) for n in names] for f, names in FINGERS.items()} for r in rigs}}
        records.append(dict(spec, actual=actual))
        (output / 'render_manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'PROGRESS {len(records)}/{len(plan["images"])}', flush=True)


if __name__ == '__main__':
    main()
