"""Fit reference framing from explicit correspondences, leaving pose/meshes fixed."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument("--frame", type=int)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--camera')
    parser.add_argument('--landmarks-json', required=True)
    parser.add_argument('--width', type=int, required=True)
    parser.add_argument('--height', type=int, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    source, output = Path(args.input).resolve(), Path(args.output_dir).resolve()
    if not source.is_file() or source.suffix.lower() != '.blend':
        raise ValueError('An existing .blend is required')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output directory must be new or empty')
    if not all(1 <= v <= 8192 for v in (args.width, args.height)):
        raise ValueError('Reference dimensions must be between 1 and 8192')
    landmarks = json.loads(args.landmarks_json)
    if not isinstance(landmarks, list) or not 3 <= len(landmarks) <= 32:
        raise ValueError('Supply 3 to 32 identified reference landmarks')
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    if args.frame is not None:
        if not -1048574 <= args.frame <= 1048574:
            raise ValueError("frame must be within Blender limits")
        bpy.context.scene.frame_set(args.frame)
    original = scene.objects.get(args.camera) if args.camera else scene.camera
    if original is None or original.type != 'CAMERA' or original.data.type not in ('ORTHO', 'PERSP'):
        raise ValueError('Select an orthographic or perspective camera')
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points, target = [], []
    for item in landmarks:
        uv, local = item['referenceUv'], item.get('localPoint', [0, 0, 0])
        if len(uv) != 2 or len(local) != 3 or not all(math.isfinite(v) for v in [*uv, *local]) or not all(0 <= v <= 1 for v in uv):
            raise ValueError('Use finite local XYZ and reference UV from top-left in [0,1]')
        obj = scene.objects.get(item['objectName'])
        if obj is None:
            raise ValueError(f"Unknown landmark object: {item['objectName']}")
        points.append(obj.evaluated_get(depsgraph).matrix_world @ Vector(local))
        target.append(uv)
    # Work on a detached evaluated camera copy, never alter the original camera.
    evaluated = original.evaluated_get(depsgraph)
    camera = bpy.data.objects.new('BAS_ReferenceFit', evaluated.data.copy())
    camera.data.animation_data_clear()
    camera.matrix_world = evaluated.matrix_world.copy()
    scene.collection.objects.link(camera)
    scene.camera = camera
    scene.render.resolution_x, scene.render.resolution_y = args.width, args.height
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
    scene.render.use_border = False
    parameter = 'ortho_scale' if camera.data.type == 'ORTHO' else 'lens'
    initial = np.array([math.log(getattr(camera.data, parameter)), camera.data.shift_x, camera.data.shift_y])
    weights = np.array([args.width, args.height])
    target = np.array(target)
    lower = np.array([math.log(1e-4 if parameter == 'ortho_scale' else 1), -2, -2])
    upper = np.array([math.log(1e6 if parameter == 'ortho_scale' else 300), 2, 2])

    def project(p):
        setattr(camera.data, parameter, math.exp(float(p[0])))
        camera.data.shift_x, camera.data.shift_y = float(p[1]), float(p[2])
        bpy.context.view_layer.update()
        values = [world_to_camera_view(scene, camera, point) for point in points]
        if any(v.z <= 0 for v in values):
            raise ValueError('A landmark is behind the camera; fix orientation before fitting framing')
        return np.array([[v.x, 1 - v.y] for v in values])

    def residual(p):
        return ((project(p) - target) * weights).ravel()

    p = initial.copy()
    before = residual(p)
    iterations = 0
    for iterations in range(1, 13):
        current = residual(p)
        jacobian = np.column_stack([(residual(p + np.eye(3)[i] * .001) - current) / .001 for i in range(3)])
        if np.linalg.matrix_rank(jacobian, tol=1e-4) < 3:
            raise ValueError('Landmarks do not constrain framing; use spatially separated features')
        step = np.linalg.lstsq(jacobian, -current, rcond=None)[0]
        accepted = False
        for factor in (1, .5, .25, .125):
            candidate = np.clip(p + step * factor, lower, upper)
            if np.linalg.norm(residual(candidate)) < np.linalg.norm(current):
                p = candidate
                accepted = True
                break
        if not accepted or np.linalg.norm(step) < 1e-6:
            break
    after = residual(p)
    rms = lambda values: float(np.sqrt(np.mean(np.sum(values.reshape(-1, 2) ** 2, axis=1))))
    # Do not retain a numerical regression from a bounded or ill-conditioned solve.
    if rms(after) > rms(before):
        p = initial
        after = residual(p)
    output.mkdir(parents=True, exist_ok=True)
    candidate_path = output / 'camera-fit.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(candidate_path))
    report = {
        'scope': 'fixed_pose_reference_framing_fit', 'source': str(source),
        'frame': int(scene.frame_current),
        'candidate': str(candidate_path), 'source_camera': original.name, 'fitted_camera': camera.name,
        'projection': camera.data.type, 'resolution': [args.width, args.height], 'iterations': iterations,
        'rms_before_px': rms(before), 'rms_after_px': rms(after),
        'max_error_after_px': float(np.max(np.linalg.norm(after.reshape(-1, 2), axis=1))),
        'geometry_changed': False, 'camera_pose_changed': False,
        'parameters': {parameter: getattr(camera.data, parameter), 'shift_x': camera.data.shift_x, 'shift_y': camera.data.shift_y},
        'landmarks': [{'name': item['name'], 'error_before_px': float(np.linalg.norm(a)),
                       'error_after_px': float(np.linalg.norm(b))}
                      for item, a, b in zip(landmarks, before.reshape(-1, 2), after.reshape(-1, 2))],
        'limitations': ['Fits scale/focal length and lens shift only; orientation and camera position remain fixed.',
                       'Residual errors can mean wrong pose, geometry, correspondences or lens distortion.',
                       'No automatic landmark detection or occlusion inference; inspect the candidate overlay before retaining.',
                       'Copy accepted camera parameters into durable bpy source; the original source file is never saved.'],
    }
    (output / 'camera-fit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'BLENDER_AGENT_STUDIO_CAMERA_FIT={output / "camera-fit.json"}')


if __name__ == '__main__':
    main()
