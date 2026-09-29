from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'skills' / 'blender2easy'
sys.path.insert(0, str(ROOT / 'scripts'))
from animkit import review
from animkit.common import read_json, write_json, sha256
from animkit.diagnostics import fingerprint
from animkit.project import normalize_project


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'project.json'
        self.raw = read_json(ROOT / 'assets/templates/box.json')
        write_json(self.path, self.raw)
        self.spec = {'title': 'Inspect', 'question': 'Check this edge', 'stage': 'motion',
                     'segments': [{'id': 'open', 'title': 'Open', 'source_range': [1,48]}],
                     'focus': {'shot_id': 'opening', 'segment_id': 'open', 'object_ids': ['hinge','lid'],
                               'source_frame': 38, 'source_range': [1,48], 'camera_id': 'hero'},
                     'controls': [], 'inspection': {'tools': ['point','measure','isolate','xray'], 'object_ids': ['lid']},
                     'evidence': {'findings': [self.finding()]}}

    def tearDown(self):
        self.temp.cleanup()

    def finding(self):
        return {'id':'edge', 'title':'Check edge', 'severity':'warning', 'object_ids':['lid'],
                'source_frame':38, 'camera_id':'hero'}

    def create(self, spec=None):
        self.state = review.create_request(self.path, spec or self.spec, 'qa-task')
        return self.state['request']

    def submit(self, annotation, decision='revise'):
        request = self.state['request']
        return review.submit_review(self.path, request['id'], request['revision'], {}, decision, 'Check marked surface', annotation)

    def point(self, world=None):
        return {'object_id':'lid','local':[0,0,0], 'world': world or [0,0,0]}

    def build_source(self, name='one', data=b'blender-test-fixture'):
        source = self.root / '.animation/builds' / name / 'scene.blend'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(data)
        normalized = normalize_project(self.raw, self.path)
        inputs = {'scene':normalized['scene'], 'source':None, 'units':normalized['units'],
                  'assets':normalized['assets'], 'asset_hashes':normalized['_asset_hashes'], 'fps':normalized['render']['fps']}
        write_json(source.parent / 'build.json', {'status':'PASS','blend':str(source),'blend_sha256':sha256(source),'inputs':inputs})
        return {'path':str(source), 'sha256':sha256(source)}

    def report(self, sources=None, **extra):
        report = {'schema_version':'object-animation.diagnostic-report/1', 'kind':'analyze',
                  'sources':sources or [self.build_source()], 'findings':[self.finding()], **extra}
        path = self.root / 'report.json'
        write_json(path, report)
        self.spec['evidence'] = {'reports':[{'path':str(path)}]}
        return path

    def test_findings_without_reference_images_and_scoped_measurement(self):
        original = self.path.read_bytes()
        self.create()
        response = self.submit({'source_frame':38,'finding_id':'edge','points':[self.point(),self.point([0,3,4])]}, 'confirm')['response']
        self.assertEqual(response['annotation']['measurement']['distance'],5)
        self.assertFalse(response['annotation']['measurement']['verified_geometry'])
        self.assertEqual(response['annotation']['coordinate_space'],'three-preview')
        review.apply_review(self.path, self.state['request']['id'], response['digest'])
        self.assertEqual(self.path.read_bytes(), original)

    def test_reject_surface_points_without_tool_or_outside_scope(self):
        self.create()
        for annotation in ({'points':[self.point()]}, {'source_frame':38,'points':[dict(self.point(),object_id='floor')]},
                           {'source_frame':38,'points':[self.point([0,float('nan'),1])]},
                           {'source_frame':38,'points':[self.point()]*3}):
            with self.subTest(annotation=annotation), self.assertRaises(review.ReviewError): self.submit(annotation)
        spec=deepcopy(self.spec);spec['inspection']['tools']=['isolate'];self.create(spec)
        with self.assertRaises(review.ReviewError):self.submit({'source_frame':38,'points':[self.point()]})

    def test_point_only_cannot_submit_measurement_and_no_invented_distance(self):
        spec=deepcopy(self.spec);spec['inspection']['tools']=['point'];self.create(spec)
        with self.assertRaises(review.ReviewError):self.submit({'source_frame':38,'points':[self.point(),self.point()]})
        with self.assertRaises(review.ReviewError):self.submit({'source_frame':38,'measurement':{'distance':1}})
        response=self.submit({'source_frame':38,'points':[self.point()]})['response']
        self.assertNotIn('measurement',response['annotation'])

    def test_findings_require_known_frame_objects_camera_and_unique_id(self):
        for field, value in [('source_frame',49),('camera_id','missing'),('object_ids',['floor']),('severity','good')]:
            spec=deepcopy(self.spec);spec['evidence']['findings'][0][field]=value
            with self.subTest(field=field),self.assertRaises(review.ReviewError):self.create(spec)
        self.create()
        with self.assertRaises(review.ReviewError):self.submit({'finding_id':'edge','source_frame':37})

    def test_inspection_cannot_expand_focus_or_invent_tools(self):
        for field,value in [('object_ids',['floor']),('tools',['transform']),('tools',['point','point'])]:
            spec=deepcopy(self.spec);spec['inspection'][field]=value
            with self.subTest(field=field),self.assertRaises(review.ReviewError):self.create(spec)

    def test_legacy_neighbor_annotation_is_feedback_not_a_write(self):
        self.create()
        response=self.submit({'source_frame':38,'object_id':'floor'})['response']
        self.assertEqual(response['changes'],[])

    def test_report_freezes_evidence_and_rejects_changed_report_or_asset(self):
        report=self.report();raw=read_json(report);raw['findings'][0]['id']='connection:38:盒盖';write_json(report,raw);request=self.create()
        self.assertEqual(len(request['evidence']['findings']),1)
        self.assertEqual(list(request['evidence']['reports'][0]['finding_map'].values()),['connection:38:盒盖'])
        report.write_text('{}')
        with self.assertRaises(review.ReviewError):review.preview_review(self.path,request['id'],request['revision'],{})

    def test_report_must_describe_this_project(self):
        foreign=self.root/'foreign.blend';foreign.write_bytes(b'foreign')
        self.report([{'path':str(foreign),'sha256':sha256(foreign)}])
        with self.assertRaises(review.ReviewError):self.create()

    def test_report_keeps_informational_changes_that_require_review(self):
        changed = dict(self.finding(), id='changed:38:lid:geometry', severity='info',
                       constraint='review_required', title='Object geometry changed')
        passed = dict(self.finding(), id='connections:38:hinge', severity='info',
                      constraint='hard', title='Declared anchors coincide within tolerance')
        self.report(findings=[changed, passed])
        request = self.create()
        findings = request['evidence']['findings']
        self.assertEqual([item['title'] for item in findings], ['Object geometry changed'])
        self.assertEqual(list(request['evidence']['reports'][0]['finding_map'].values()), [changed['id']])

    def test_compare_subject_is_after_not_matching_before(self):
        before=self.build_source();foreign=self.root/'foreign.blend';foreign.write_bytes(b'foreign')
        self.report([before,{'path':str(foreign),'sha256':sha256(foreign)}],kind='compare')
        with self.assertRaises(review.ReviewError):self.create()

    def test_historical_baseline_is_frozen_by_snapshot_not_live_old_asset(self):
        before=self.build_source(data=b'old');after=self.build_source(data=b'new')
        snapshots=[]
        for i,source in enumerate([before,after]):
            p=self.root/f'snapshot-{i}.json';write_json(p,{'source':source})
            snapshots.append({'path':str(p),'sha256':sha256(p)})
        self.report([before,after],kind='compare',snapshot_sha256=[fingerprint({'source':source}) for source in [before,after]],
                    provenance={'historical_baseline':True,'snapshot_files':snapshots})
        request=self.create()
        review.preview_review(self.path,request['id'],request['revision'],{})
        Path(snapshots[0]['path']).write_text('{}')
        with self.assertRaises(review.ReviewError):review.preview_review(self.path,request['id'],request['revision'],{})

    def test_report_snapshot_must_match_source_and_normalized_fingerprint(self):
        source = self.build_source()
        snapshot_path = self.root / 'snapshot.json'
        snapshot = {'source': source, 'frames': []}
        write_json(snapshot_path, snapshot)
        report_path = self.report([source], snapshot_sha256=[fingerprint(snapshot)],
                                 provenance={'snapshot_files': [{'path': str(snapshot_path), 'sha256': sha256(snapshot_path)}]})
        self.create()
        original = read_json(report_path)
        # A valid file checksum alone does not bind substituted data to the report.
        snapshot['frames'] = [{'frame': 38}]
        write_json(snapshot_path, snapshot)
        changed = deepcopy(original)
        changed['provenance']['snapshot_files'][0]['sha256'] = sha256(snapshot_path)
        write_json(report_path, changed)
        with self.assertRaisesRegex(review.ReviewError, 'snapshot/report mismatch'):
            self.create()
        # Source correspondence applies to analyze reports as well as comparisons.
        snapshot['source'] = dict(source, sha256='0' * 64)
        write_json(snapshot_path, snapshot)
        changed['provenance']['snapshot_files'][0]['sha256'] = sha256(snapshot_path)
        changed['snapshot_sha256'] = [fingerprint(snapshot)]
        write_json(report_path, changed)
        with self.assertRaisesRegex(review.ReviewError, 'snapshot/source mismatch'):
            self.create()

    def test_report_contract_must_match_normalized_fingerprint(self):
        contract_path = self.root / 'contract.json'
        contract = {'schema_version': 'object-animation.diagnostic-contract/1', 'triangle_budget': 24}
        write_json(contract_path, contract)
        report_path = self.report(contract_sha256=fingerprint(contract),
                                 provenance={'contract_file': {'path': str(contract_path), 'sha256': sha256(contract_path)}})
        self.create()
        report = read_json(report_path)
        contract['triangle_budget'] = 25
        write_json(contract_path, contract)
        report['provenance']['contract_file']['sha256'] = sha256(contract_path)
        write_json(report_path, report)
        with self.assertRaisesRegex(review.ReviewError, 'contract/report mismatch'):
            self.create()

    def test_report_provenance_and_snapshot_count_are_validated(self):
        source = self.build_source()
        for fields in ({'provenance': None}, {'provenance': {'snapshot_files': None}},
                       {'kind': 'unexpected'}, {'sources': [source, source]},
                       {'kind': 'compare', 'sources': [source, source],
                        'provenance': {'historical_baseline': True, 'snapshot_files': []}}):
            with self.subTest(fields=fields):
                self.report(**fields)
                with self.assertRaises(review.ReviewError):
                    self.create()


if __name__=='__main__': unittest.main()
