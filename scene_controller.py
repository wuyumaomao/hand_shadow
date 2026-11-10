"""Runs inside Blender. Move a hand as a unit while preserving its binding."""
import math
import bpy
from mathutils import Matrix, Euler, Vector
from configuration import HANDS, FINGERS, DEFAULT_ANGLES


class SceneController:
    def __init__(self, mode):
        self.scene = bpy.context.scene
        self.mode = mode
        self.camera = self.scene.objects.get('Camera.001')
        self.light = self.scene.objects.get('日光')
        if not self.camera or self.camera.type != 'CAMERA':
            raise ValueError('Required camera missing: Camera.001')
        if not self.light or self.light.type != 'LIGHT' or self.light.data.type != 'SUN':
            raise ValueError('Required SUN light missing: 日光')
        self.scene.camera = self.camera
        self.hands = {}
        self.base_camera = self.camera.matrix_world.copy()
        self.base_light = self.light.matrix_world.copy()
        self.base_camera_angles = self.base_camera.to_euler('XYZ', self.camera.rotation_euler)
        self.base_light_angles = self.base_light.to_euler('XYZ', self.light.rotation_euler)
        for obj in self.scene.objects:
            if obj.type == 'LIGHT':
                obj.hide_render = obj != self.light
        for name in ['left'] if mode == 'single' else ['left', 'right']:
            binding = HANDS[name]
            rig = self.scene.objects.get(binding['rig'])
            meshes = [self.scene.objects.get(n) for n in binding['meshes']]
            if not rig or rig.type != 'ARMATURE' or any(m is None for m in meshes):
                raise ValueError(f'{name}: missing hand mesh / armature')
            for mesh in meshes:
                if not any(m.type == 'ARMATURE' and m.object == rig for m in mesh.modifiers):
                    raise ValueError(f'{mesh.name}: wrong armature binding')
            if any(n not in rig.pose.bones for names in FINGERS.values() for n in names):
                raise ValueError(f'{rig.name}: missing finger bones')
            root = bpy.data.objects.new('Control_' + name, None)
            self.scene.collection.objects.link(root)
            pivot = rig.matrix_world.translation.copy()
            root.location = pivot
            bpy.context.view_layer.update()
            # Parent only top-level members. Parenting mesh twice would double-transform it.
            members = set([rig] + meshes)
            for obj in members:
                if obj.parent not in members:
                    world = obj.matrix_world.copy()
                    obj.parent = root
                    obj.matrix_world = world
            for obj in [rig, *meshes]:
                obj.animation_data_clear()
                obj.hide_set(False)
            rig.data.pose_position = 'POSE'
            self.hands[name] = (root, rig, meshes, pivot)
        for obj in [self.camera, self.light]:
            obj.animation_data_clear()
        bpy.context.view_layer.update()

    def apply(self, config):
        for name, (root, rig, meshes, pivot) in self.hands.items():
            hand = config.get('hands', {}).get(name, {})
            enabled = hand.get('enabled', True)
            for obj in [root, rig, *meshes]:
                obj.hide_render = not enabled
            translation = Vector([hand.get('translation', {}).get(a, 0) for a in 'xyz'])
            rotation = Euler([math.radians(hand.get('rotation_degrees', {}).get(a, 0)) for a in 'xyz'], 'XYZ')
            root.matrix_world = Matrix.Translation(pivot + translation) @ rotation.to_matrix().to_4x4()
            for bone in rig.pose.bones:
                bone.rotation_mode = 'XYZ'
                bone.rotation_euler = (0, 0, 0)
                bone.location = (0, 0, 0)
                bone.scale = (1, 1, 1)
            state = hand.get('state', [0] * 5)
            for bit, (finger, bones) in zip(state, FINGERS.items()):
                angles = hand.get('bend_angles', {}).get(finger, DEFAULT_ANGLES[finger])
                for bone, angle in zip(bones, angles):
                    rig.pose.bones[bone].rotation_euler[0 if finger == 'thumb' else 2] = math.radians(angle if bit else 0)
        self.set_absolute(self.camera, self.base_camera, config.get('camera', {}), self.base_camera_angles)
        self.set_absolute(self.light, self.base_light, config.get('light', {}), self.base_light_angles)
        bpy.context.view_layer.update()

    @staticmethod
    def set_absolute(obj, baseline, config, base_angles):
        location, rotation, scale = baseline.decompose()
        angles = base_angles.copy()
        for i, axis in enumerate('xyz'):
            if axis in config.get('position', {}):
                location[i] = config['position'][axis]
            if axis in config.get('rotation_degrees', {}):
                angles[i] = math.radians(config['rotation_degrees'][axis])
        obj.matrix_world = Matrix.LocRotScale(location, angles.to_quaternion(), scale)

    def snapshot(self):
        def transform(obj):
            loc, rot, scale = obj.matrix_world.decompose()
            return {'position': list(loc), 'rotation_degrees': [math.degrees(v) for v in rot.to_euler('XYZ')],
                    'scale': list(scale), 'matrix_world': [list(row) for row in obj.matrix_world]}
        return {'camera': transform(self.camera), 'light': transform(self.light),
                'hands': {name: {'enabled': not rig.hide_render, 'rig': rig.name,
                                 'rig_transform': transform(rig), 'controller': transform(root),
                                 'mesh_transforms': {m.name: transform(m) for m in meshes},
                                 'finger_angles_degrees': {f: [math.degrees(rig.pose.bones[n].rotation_euler[0 if f == 'thumb' else 2]) for n in names] for f, names in FINGERS.items()}}
                          for name, (root, rig, meshes, _) in self.hands.items()}}
