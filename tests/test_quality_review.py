"""Quality-to-review contracts: exact scope, usable imagery, immutable evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'skills' / 'blender2easy'
sys.path.insert(0, str(ROOT / 'scripts'))
from animkit import review
from animkit.common import read_json, sha256, write_json
from animkit.project import normalize_project
from animkit.quality_review import attach_quality

PNG = b'\x89PNG\r\n\x1a\n'  # The existing reference boundary checks local type/magic.


class QualityReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Hand-built asset hashes must use the canonical keys produced at runtime.
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / 'project.json'
        self.raw = read_json(ROOT / 'assets/templates/box.json')
        write_json(self.path, self.raw)
        normalized = normalize_project(self.raw, self.path)
        self.source = self.root / '.animation/builds/quality/scene.blend'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'frozen Blender fixture')
        inputs = {'scene': normalized['scene'], 'source': None, 'units': normalized['units'],
                  'assets': normalized['assets'], 'asset_hashes': normalized['_asset_hashes'], 'fps': normalized['render']['fps']}
        write_json(self.source.parent / 'build.json', {'status': 'PASS', 'blend': str(self.source),
                   'blend_sha256': sha256(self.source), 'inputs': inputs})
        self.spec = {'title': 'Inspect quality evidence', 'question': 'Review the highlighted finding', 'stage': 'model',
                     'segments': [{'id': 'open', 'title': 'Open', 'source_range': [1, 48]}],
                     'focus': {'shot_id': 'opening', 'segment_id': 'open', 'object_ids': ['hinge', 'lid'],
                               'source_frame': 38, 'source_range': [1, 48], 'camera_id': 'hero'}, 'controls': []}

    def file_record(self, path, role):
        return {'path': str(path), 'role': role, 'sha256': sha256(path), 'bytes': path.stat().st_size}

    def make_run(self, tool, report, reference=False):
        folder = self.root / ('quality-' + tool)
        payload = folder / 'payload'
        payload.mkdir(parents=True)
        quality_spec = self.root / (tool + '-spec.json')
        write_json(quality_spec, {'input': str(self.source), 'outputDir': str(folder), 'frame': 38})
        dependency = self.root / (tool + '-texture.png')
        dependency.write_bytes(PNG)
        inputs = [self.file_record(quality_spec, 'spec'), self.file_record(self.source, 'input'),
                  self.file_record(dependency, 'dependency')]
        if reference:
            image = self.root / 'reference.png'
            image.write_bytes(PNG)
            inputs.append(self.file_record(image, 'reference'))
            for name in ('reference.png', 'overlay.png'):
                (payload / name).write_bytes(PNG)
            report.update(reference=str(image), reference_sha256=sha256(image), mask=None,
                          overlay=str(payload / 'overlay.png'), source_sha256=sha256(self.source))
        report.setdefault('source' if tool == 'reference' else 'input', str(self.source))
        report_path = payload / 'report.json'
        write_json(report_path, report)
        manifest = {'schemaVersion': 1, 'tool': tool, 'status': 'complete', 'returnCode': 0,
                    'outputDir': str(folder), 'report': str(report_path), 'provenance': str(folder / 'provenance.json'),
                    'inputs': inputs, 'inputsAfter': deepcopy(inputs), 'inputUnchanged': True,
                    'outputs': [self.file_record(path, 'output') for path in sorted(payload.iterdir())]}
        self.manifest_path = folder / 'provenance.json'
        write_json(self.manifest_path, manifest)
        self.spec['evidence'] = {'reports': [{'kind': 'quality', 'path': str(self.manifest_path)}]}
        return report_path

    def topology(self, names=('lid',)):
        return {'schema_version': 'bas-topology-diagnostics/0.1', 'scope': {'frame': 38, 'objectName': None},
                'findings': [{'objectName': name, 'evaluatedElementIndex': index, 'kind': 'degenerate_face',
                              'worldCenter': [10, 20, 30], 'area': 0.0} for index, name in enumerate(names)],
                'truncated': False, 'limitations': ['Evaluated indexes are not editable source indexes.']}

    def create(self):
        self.request = review.create_request(self.path, self.spec, 'quality-test-task')['request']
        return self.request

    def rewrite_report(self, data):
        manifest = read_json(self.manifest_path)
        report_path = Path(manifest['report'])
        write_json(report_path, data)
        manifest['outputs'] = [self.file_record(Path(item['path']), 'output') for item in manifest['outputs']]
        write_json(self.manifest_path, manifest)

    def test_topology_maps_exact_names_and_frame_without_preview_coordinates(self):
        self.make_run('topology', self.topology(('lid', 'floor')))
        evidence = self.create()['evidence']
        self.assertEqual(len(evidence['findings']), 1)
        finding = evidence['findings'][0]
        self.assertEqual((finding['object_ids'], finding['source_frame'], finding['camera_id']), (['lid'], 38, 'hero'))
        self.assertNotIn('points', finding)
        self.assertNotIn('worldCenter', finding)
        self.assertEqual(evidence['reports'][0]['camera_binding'], 'review_navigation')
        self.assertEqual(list(evidence['reports'][0]['finding_map'].values()), ['topology:0'])
        self.spec['evidence']['reports'][0]['finding_ids'] = ['topology:1']
        with self.assertRaisesRegex(review.ReviewError, 'outside this review focus'):
            self.create()

    def test_inspect_emits_factual_counts_without_pass_fail(self):
        self.make_run('inspect', {'schema_version': 3, 'scene': {'frame_current': 38},
                                  'meshes': [{'name': 'lid', 'non_manifold_edges': 4, 'degenerate_faces': 0}]})
        evidence = self.create()['evidence']
        self.assertEqual([item['title'] for item in evidence['findings']], ['Non-manifold edges (context required): 4'])
        self.assertEqual(evidence['findings'][0]['severity'], 'warning')
        self.assertNotIn('status', evidence['reports'][0])

    def test_reference_imports_images_checkpoint_and_exact_landmark(self):
        self.make_run('reference', {'schema_version': 1, 'scope': 'projected_geometry_reference_comparison',
                                   'frame': 38, 'camera': {'name': 'hero'}, 'metrics': None,
                                   'landmarks': [{'name': 'Lid tip', 'object': 'lid', 'error_pixels': 7.2}]}, reference=True)
        original = self.path.read_bytes()
        request = self.create()
        evidence = request['evidence']
        self.assertEqual(len(evidence['references']), 2)
        self.assertEqual(evidence['reports'][0]['camera_binding'], 'reported_projection')
        self.assertEqual(evidence['checkpoints'][0]['source_frame'], 38)
        self.assertEqual(evidence['checkpoints'][0]['camera_id'], 'hero')
        self.assertNotIn('object_ids', evidence['checkpoints'][0])  # Global silhouette does not localize an object.
        finding = evidence['findings'][0]
        self.assertEqual(finding['object_ids'], ['lid'])
        self.assertIn('7.2 px', finding['title'])
        annotation = {'source_frame': 38, 'finding_id': finding['id'], 'reference_id': finding['reference_id'],
                      'reference_uv': [.3, .4]}
        response = review.submit_review(self.path, request['id'], request['revision'], {}, 'revise',
                                        'Lid tip needs adjustment', annotation)['response']
        self.assertEqual(response['annotation'], annotation)
        self.assertEqual(self.path.read_bytes(), original)

    def test_reference_without_landmarks_does_not_invent_object_findings(self):
        self.make_run('reference', {'schema_version': 1, 'scope': 'projected_geometry_reference_comparison',
                                   'frame': 38, 'camera': {'name': 'hero'}, 'metrics': None, 'landmarks': []}, reference=True)
        evidence = self.create()['evidence']
        self.assertEqual(evidence['findings'], [])
        self.assertEqual(len(evidence['references']), 2)

    def test_reference_frame_and_camera_must_match_frozen_review(self):
        report = {'schema_version': 1, 'scope': 'projected_geometry_reference_comparison',
                  'frame': 38, 'camera': {'name': 'hero'}, 'landmarks': []}
        report_path = self.make_run('reference', report, reference=True)
        original = read_json(report_path)
        for changed in (dict(original, frame=49), dict(original, camera={'name': 'detail'}), dict(original, frame=37)):
            with self.subTest(changed=changed):
                self.rewrite_report(changed)
                with self.assertRaises(review.ReviewError):
                    self.create()

    def test_incomplete_unsupported_or_foreign_source_is_rejected(self):
        self.make_run('topology', self.topology())
        original = read_json(self.manifest_path)
        for field, value in (('status', 'failed'), ('inputUnchanged', False), ('returnCode', 1),
                             ('tool', 'motion'), ('inputsAfter', []), ('outputs', [])):
            write_json(self.manifest_path, dict(original, **{field: value}))
            with self.subTest(field=field), self.assertRaises(review.ReviewError):
                self.create()
        write_json(self.manifest_path, original)
        foreign = self.root / 'other.blend'
        foreign.write_bytes(b'foreign source')
        manifest = deepcopy(original)
        manifest['inputs'][1] = self.file_record(foreign, 'input')
        manifest['inputsAfter'] = deepcopy(manifest['inputs'])
        write_json(self.manifest_path, manifest)
        with self.assertRaisesRegex(review.ReviewError, 'does not describe this project'):
            self.create()

    def test_changed_inputs_outputs_provenance_block_attachment_and_feedback(self):
        report_path = self.make_run('topology', self.topology())
        manifest = read_json(self.manifest_path)
        for item in [manifest['inputs'][2], manifest['outputs'][0], {'path': str(self.manifest_path)}]:
            path = Path(item['path'])
            original = path.read_bytes()
            request = self.create()
            path.write_bytes(original + b' ')
            with self.subTest(path=path):
                with self.assertRaises(review.ReviewError):
                    review.preview_review(self.path, request['id'], request['revision'], {})
                with self.assertRaises(review.ReviewError):
                    review.submit_review(self.path, request['id'], request['revision'], {}, 'confirm')
                if path != self.manifest_path:
                    with self.assertRaises(review.ReviewError):
                        self.create()
            path.write_bytes(original)
        request = self.create()
        response = review.submit_review(self.path, request['id'], request['revision'], {}, 'confirm')['response']
        report_path.write_bytes(report_path.read_bytes() + b' ')
        with self.assertRaises(review.ReviewError):
            review.apply_review(self.path, request['id'], response['digest'])

    def test_limits_require_explicit_finding_selection_and_preserve_image_cap(self):
        self.make_run('topology', self.topology(['lid'] * 25))
        with self.assertRaisesRegex(review.ReviewError, 'Too many findings'):
            self.create()
        self.spec['evidence']['reports'][0]['finding_ids'] = ['topology:3']
        self.assertEqual(len(self.create()['evidence']['findings']), 1)
        image = self.root / 'manual.png'
        image.write_bytes(PNG)
        self.make_run('reference', {'schema_version': 1, 'scope': 'projected_geometry_reference_comparison',
                                   'frame': 38, 'camera': {'name': 'hero'}, 'landmarks': []}, reference=True)
        self.spec['evidence']['references'] = [{'id': 'manual-' + str(i), 'title': 'Manual', 'path': str(image)} for i in range(5)]
        with self.assertRaisesRegex(review.ReviewError, 'at most 6 images'):
            self.create()

    def test_native_inspect_requires_selected_scene_and_declared_dependencies(self):
        self.source = self.root / 'native.blend'
        self.source.write_bytes(b'native source')
        self.make_run('inspect', {'schema_version': 3, 'scene': {'frame_current': 38, 'name': 'Selected'}, 'meshes': []})
        project = {'source': {'blend': str(self.source), 'scene': 'Selected'},
                   '_review_focus': self.spec['focus'], 'render': {'fps': 24}}
        hashes = {str(self.source): sha256(self.source)}
        entry = self.spec['evidence']['reports'][0]
        self.assertEqual(attach_quality(entry, project, self.path, hashes)['findings'], [])
        project['source']['scene'] = 'Another'
        with self.assertRaisesRegex(review.ReviewError, 'selected native scene'):
            attach_quality(entry, project, self.path, hashes)
        project['source']['scene'] = 'Selected'
        missing_dependency = self.root / 'external-texture.png'
        missing_dependency.write_bytes(PNG)
        hashes[str(missing_dependency)] = sha256(missing_dependency)
        with self.assertRaisesRegex(review.ReviewError, 'all declared native dependencies'):
            attach_quality(entry, project, self.path, hashes)
        manifest = read_json(self.manifest_path)
        manifest['inputs'].append(self.file_record(missing_dependency, 'dependency'))
        manifest['inputsAfter'] = deepcopy(manifest['inputs'])
        write_json(self.manifest_path, manifest)
        self.assertEqual(attach_quality(entry, project, self.path, hashes)['findings'], [])

    def test_native_topology_requires_verified_build_with_selected_scene(self):
        self.source = self.root / 'native.blend'
        self.source.write_bytes(b'native source')
        self.make_run('topology', self.topology())
        project = {'source': {'blend': str(self.source), 'scene': 'Selected'},
                   '_review_focus': self.spec['focus'], 'render': {'fps': 24}}
        with self.assertRaisesRegex(review.ReviewError, 'verified project build'):
            attach_quality(self.spec['evidence']['reports'][0], project, self.path, {str(self.source): sha256(self.source)})


if __name__ == '__main__':
    unittest.main()
