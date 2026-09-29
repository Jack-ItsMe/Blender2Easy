"""Bind completed BAS quality evidence to a bounded review without inferring intent.

Only inspect, topology and reference reports have explicit adapters. BAS world
centers and element indexes remain in the report; they are not Three.js points.
"""
import math
from pathlib import Path

from .common import digest, read_json, sha256
from .diagnostics import finite_tree


def _path(value, label):
    from .review import _require, _text
    path = Path(_text(value, label, 4096)).expanduser()
    _require(path.is_absolute(), label + ' must be absolute')
    return path.resolve()


def _json(path):
    from .review import _require, ReviewError
    _require(path.is_file() and path.stat().st_size <= 8_000_000, 'Quality JSON must exist and be at most 8 MB')
    try:
        data = read_json(path)
        finite_tree(data)
    except (ValueError, OSError) as exc:
        raise ReviewError('Invalid quality JSON: ' + str(exc)) from exc
    _require(isinstance(data, dict), 'Quality JSON must be an object')
    return data


def _files(items, label, maximum):
    from .review import _require
    _require(isinstance(items, list) and 1 <= len(items) <= maximum, f'Invalid quality {label}')
    result = []
    for item in items:
        _require(isinstance(item, dict), f'Invalid quality {label} fingerprint')
        path = _path(item.get('path'), f'Quality {label} path')
        expected = item.get('sha256')
        _require(isinstance(expected, str) and len(expected) == 64
                 and all(char in '0123456789abcdef' for char in expected), f'Invalid quality {label} SHA-256')
        _require(path.is_file() and sha256(path) == expected, f'Quality {label} changed; rerun quality inspection', 409)
        result.append({'path': str(path), 'sha256': expected, 'role': item.get('role')})
    return result


def _one(items, role):
    from .review import _require
    matches = [item for item in items if item['role'] == role]
    _require(len(matches) == 1, 'Quality provenance requires one ' + role)
    return matches[0]


def _frame(value, focus):
    from .review import _require
    lo, hi = focus['source_range']
    _require(type(value) is int and lo <= value <= hi, 'Quality frame lies outside the review focus range')
    return value


def _candidate(key, title, name, frame, camera, severity='warning', reference=None):
    from .review import _text
    _text(name, 'Quality object name', 1024)
    result = {'id': key, 'title': title[:200], 'severity': severity, 'object_ids': [name],
              'source_frame': frame, 'camera_id': camera}
    if reference:
        result['reference_id'] = reference
    return result


def attach_quality(entry, project, project_path, asset_hashes):
    """Return normalized findings/images/checkpoints and one immutable file binding."""
    from .review import _require, _text
    from .review_diagnostics import project_source
    raw = Path(_text(entry['path'], 'Quality provenance path', 4096)).expanduser()
    manifest_path = (raw if raw.is_absolute() else project_path.parent / raw).resolve()
    _require(manifest_path.is_file() and manifest_path.stat().st_size <= 8_000_000,
             'Quality provenance must exist and be at most 8 MB')
    manifest_hash = sha256(manifest_path)
    manifest = _json(manifest_path)
    _require(manifest.get('schemaVersion') == 1 and manifest.get('tool') in ('inspect', 'topology', 'reference'),
             'Quality review supports inspect, topology and reference provenance only')
    _require(manifest.get('status') == 'complete' and manifest.get('inputUnchanged') is True
             and type(manifest.get('returnCode')) is int and manifest['returnCode'] == 0,
             'Quality review requires a completed run with unchanged inputs')
    _require(manifest.get('inputsAfter') == manifest.get('inputs'), 'Quality input provenance is inconsistent')
    _require(_path(manifest.get('provenance'), 'Quality provenance') == manifest_path
             and _path(manifest.get('outputDir'), 'Quality output directory') == manifest_path.parent,
             'Quality provenance location mismatch')
    inputs, outputs = _files(manifest.get('inputs'), 'inputs', 132), _files(manifest.get('outputs'), 'outputs', 32)
    source, spec_file = _one(inputs, 'input'), _one(inputs, 'spec')
    binding_files = []
    if Path(source['path']).is_relative_to(project_path.parent / '.animation' / 'builds'):
        build_path = Path(source['path']).parent / 'build.json'
        _require(build_path.is_file(), 'Quality project build record is missing', 409)
        binding_files.append({'path': str(build_path), 'sha256': sha256(build_path), 'role': 'project_build'})
    _require(project_source(source, project, project_path, asset_hashes),
             'Quality report does not describe this project source/build', 409)
    report_path = _path(manifest.get('report'), 'Quality report')
    output_map = {item['path']: item for item in outputs}
    _require(len(output_map) == len(outputs) and str(report_path) in output_map,
             'Quality report must be a fingerprinted output')
    _require(all(Path(item['path']).is_relative_to(manifest_path.parent / 'payload') for item in outputs),
             'Quality outputs must be inside the recorded payload directory')
    report, spec = _json(report_path), _json(Path(spec_file['path']))
    spec_source = Path(_text(spec.get('input'), 'Quality spec input', 4096)).expanduser()
    spec_source = (spec_source if spec_source.is_absolute() else Path(spec_file['path']).parent / spec_source).resolve()
    _require(spec_source == Path(source['path']), 'Quality spec/source mismatch', 409)
    tool, focus = manifest['tool'], project['_review_focus']
    native = project.get('source')
    if native and Path(source['path']) == Path(native['blend']).resolve():
        _require(tool == 'inspect' and isinstance(report.get('scene'), dict)
                 and report['scene'].get('name') == native['scene'],
                 'Quality evidence does not identify the selected native scene; run quality on the verified project build')
        recorded_inputs = {item['path']: item['sha256'] for item in inputs}
        _require(all(recorded_inputs.get(str(Path(name).resolve())) == expected for name, expected in asset_hashes.items()),
                 'Quality provenance must include all declared native dependencies')
    source_key = 'source' if tool == 'reference' else 'input'
    _require(_path(report.get(source_key), 'Quality report source') == Path(source['path']),
             'Quality report/source mismatch', 409)
    candidates, references, checkpoints = [], [], []
    camera = focus['camera_id']
    prefix = 'q-' + manifest_hash[:10]
    if tool == 'reference':
        _require(report.get('schema_version') == 1 and report.get('scope') == 'projected_geometry_reference_comparison',
                 'Unsupported reference comparison schema')
        _require(report.get('source_sha256') == source['sha256'], 'Quality reference source fingerprint mismatch', 409)
        frame = _frame(report.get('frame'), focus)
        camera_data = report.get('camera')
        _require(isinstance(camera_data, dict) and camera_data.get('name') == camera,
                 'Reference comparison camera must match the review focus camera')
        for role in ('reference', 'mask'):
            if role == 'mask' and report.get(role) is None:
                continue
            item = _one(inputs, role)
            _require(_path(report.get(role), 'Comparison ' + role) == Path(item['path'])
                     and report.get(role + '_sha256') == item['sha256'], 'Quality reference input mismatch', 409)
        normalized_reference = report_path.parent / 'reference.png'
        overlay = _path(report.get('overlay'), 'Comparison overlay')
        _require(str(normalized_reference) in output_map and str(overlay) in output_map,
                 'Reference and overlay images must be fingerprinted outputs')
        for role, image, title in (('reference', normalized_reference, 'Reference image (BAS normalized)'),
                                   ('overlay', overlay, 'Projected geometry overlay (BAS)')):
            references.append({'id': prefix + '-' + role, 'path': str(image), 'title': title})
        overlay_id = prefix + '-overlay'
        checkpoints.append({'id': prefix + '-view', 'title': 'Reference comparison: inspect matched camera and pose',
                            'source_frame': frame, 'camera_id': camera, 'reference_id': overlay_id})
        landmarks = report.get('landmarks', [])
        _require(isinstance(landmarks, list) and len(landmarks) <= 32, 'Invalid quality landmarks')
        for index, item in enumerate(landmarks):
            _require(isinstance(item, dict), 'Invalid quality landmark')
            name = _text(item.get('name'), 'Landmark name', 512)
            error = item.get('error_pixels')
            _require(error is None or type(error) in (int, float) and math.isfinite(error) and error >= 0,
                     'Invalid landmark pixel error')
            title = f'{name[:90]}: projected offset {error:.3g} px; review alignment' if error is not None else (
                f'{name[:90]}: landmark has no projected offset; review camera')
            candidates.append(_candidate(f'landmark:{index}', title, item.get('object'), frame, camera,
                                         'info' if error is not None else 'warning', overlay_id))
    elif tool == 'topology':
        _require(report.get('schema_version') == 'bas-topology-diagnostics/0.1', 'Unsupported topology schema')
        scope = report.get('scope')
        _require(isinstance(scope, dict), 'Invalid topology scope')
        frame = _frame(scope.get('frame'), focus)
        rows = report.get('findings')
        _require(isinstance(rows, list) and len(rows) <= 100, 'Invalid topology findings')
        titles = {'degenerate_face': 'Degenerate face', 'zero_length_edge': 'Zero-length edge'}
        for index, item in enumerate(rows):
            _require(isinstance(item, dict) and item.get('kind') in titles
                     and type(item.get('evaluatedElementIndex')) is int and item['evaluatedElementIndex'] >= 0,
                     'Invalid topology finding')
            name = item.get('objectName')
            _require(scope.get('objectName') is None or name == scope['objectName'], 'Topology finding/scope mismatch')
            title = f"{titles[item['kind']]}: evaluated element {item['evaluatedElementIndex']} (review)"
            candidates.append(_candidate(f'topology:{index}', title, name, frame, camera))
    else:
        _require(report.get('schema_version') == 3 and isinstance(report.get('scene'), dict),
                 'Unsupported inspect schema')
        frame = _frame(report['scene'].get('frame_current'), focus)
        meshes = report.get('meshes')
        _require(isinstance(meshes, list) and len(meshes) <= 2048, 'Invalid inspected meshes')
        metrics = {'degenerate_faces': 'Degenerate faces', 'zero_length_edges': 'Zero-length edges',
                   'invalid_vertices': 'Invalid vertices', 'isolated_vertices': 'Isolated vertices',
                   'missing_material_faces': 'Faces without assigned material',
                   'non_manifold_edges': 'Non-manifold edges (context required)', 'wire_edges': 'Wire edges (context required)'}
        for index, mesh in enumerate(meshes):
            _require(isinstance(mesh, dict), 'Invalid inspected mesh')
            for metric, title in metrics.items():
                count = mesh.get(metric, 0)
                _require(type(count) is int and count >= 0, 'Invalid inspected mesh count: ' + metric)
                if count:
                    candidates.append(_candidate(f'inspect:{index}:{metric}', f'{title}: {count}',
                                                 mesh.get('name'), frame, camera))
    if 'frame' in spec:
        _require(type(spec['frame']) is int and spec['frame'] == frame, 'Quality spec/report frame mismatch')
    if tool == 'reference' and 'camera' in spec:
        _require(spec['camera'] == camera, 'Quality spec/report camera mismatch')
    if tool == 'topology' and 'object' in spec:
        _require(spec['object'] == report['scope'].get('objectName'), 'Quality spec/report object scope mismatch')
    requested = entry.get('finding_ids')
    if requested is not None:
        _require(isinstance(requested, list) and len(requested) <= 24 and all(isinstance(item, str) for item in requested)
                 and len(set(requested)) == len(requested), 'finding_ids must contain at most 24 unique IDs')
        _require(set(requested).issubset({item['id'] for item in candidates}), 'Unknown requested quality finding')
    selected, finding_map = [], {}
    for item in candidates:
        if requested is not None and item['id'] not in requested:
            continue
        eligible = set(item['object_ids']).issubset(focus['object_ids'])
        if requested is not None:
            _require(eligible, 'Requested quality finding is outside this review focus')
        if not eligible:
            continue
        original = item['id']
        item['id'] = prefix + '-' + digest(original)[:12]
        finding_map[item['id']] = original
        selected.append(item)
    limitations = report.get('limitations', [])
    _require(isinstance(limitations, list) and all(isinstance(item, str) for item in limitations), 'Invalid quality limitations')
    limitations = [*limitations, 'Quality metrics do not establish visual acceptance or calibrated Three.js geometry.']
    if tool != 'reference':
        limitations.append('The review camera is for navigation only; this diagnostic does not measure a camera projection.')
    files = [*inputs, *outputs, *binding_files]
    for item in [{'path': str(manifest_path), 'sha256': manifest_hash}, *files]:
        _require(Path(item['path']).is_file() and sha256(item['path']) == item['sha256'],
                 'Quality evidence changed during attachment', 409)
    frozen = {'kind': 'quality', 'tool': tool, 'path': str(manifest_path), 'sha256': manifest_hash,
              'sources': [source], 'files': files, 'finding_map': finding_map, 'source_frame': frame,
              'camera_binding': 'reported_projection' if tool == 'reference' else 'review_navigation',
              'limitations': limitations, 'truncated': report.get('truncated', False)}
    return {'findings': selected, 'references': references, 'checkpoints': checkpoints, 'report': frozen}
