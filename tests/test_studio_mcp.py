import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1] / 'skills' / 'blender2easy'
sys.path.insert(0,str(ROOT/'scripts'))
from animkit import __version__
from animkit.mcp_tools import command_for, completed_result, execution_timeout, tool_content

def write_fixture(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return str(path)


def current_snapshot(directory):
    source = directory / 'source.blend'
    source.write_bytes(b'local synthetic evaluated snapshot fixture')
    def item(ident, parent=None):
        return {'id': ident, 'kind': 'EMPTY', 'parent': parent, 'materials': [],
                'world_matrix': [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]}
    return write_fixture(directory / 'snapshot.json', {
        'schema_version': 'object-animation.scene-snapshot/1',
        'source': {'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()},
        'frames': [{'frame': -1, 'meters_per_unit': 1, 'objects': [item('Base'), item('Child', 'Base'), item('Other')]}]})


class MCPTests(unittest.TestCase):
    def test_schema_rejects_invalid_types_ranges_and_duplicate_frames(self):
        invalid = [
            ('animation_snapshot', {'asset': 'x', 'output': 'y', 'frames': [True]}),
            ('animation_snapshot', {'asset': 'x', 'output': 'y', 'frames': [1, 1]}),
            ('animation_snapshot', {'asset': 'x', 'output': 'y', 'frames': [1048575]}),
            ('animation_snapshot', {'asset': 'x', 'output': 'y', 'frames': list(range(33))}),
            ('animation_describe', {'snapshot': 'x', 'descendants': 1}),
            ('animation_describe', {'snapshot': 'x', 'descendants': True}),
            ('animation_describe', {'snapshot': 'x', 'limit': True}),
            ('animation_describe', {'snapshot': 'x', 'limit': 0}),
            ('animation_describe', {'snapshot': 'x', 'limit': 201}),
            ('animation_describe', {'snapshot': 'x', 'offset': 1.0}),
            ('animation_describe', {'snapshot': 'x', 'offset': 10**400}),
            ('animation_quality', {'tool': 'inspect', 'spec_path': 'x', 'timeout_seconds': 7201}),
            ('animation_quality', {'tool': 'inspect', 'spec_path': 'x', 'timeout_seconds': False}),
            ('animation_quality', {'tool': 'inspect', 'spec_path': 'x', 'reuse': 'yes'}),
            ('animation_asset_search', {'provider': 'arbitrary', 'query': 'walk'}),
            ('animation_asset_search', {'provider': 'mixamo', 'query': 'a'*201}),
            ('animation_asset_search', {'provider': 'mixamo', 'query': 'walk\nrun'}),
            ('animation_asset_search', {'provider': 'mixamo', 'query': 'walk\n'}),
            ('animation_review_wait', {'project': 'x', 'thread_id': 't', 'request_id': 'r', 'timeout_seconds': float('nan')}),
            ('animation_review_wait', {'project': 'x', 'thread_id': 't', 'request_id': 'r', 'timeout_seconds': float('inf')}),
            ('animation_review_wait', {'project': 'x', 'thread_id': 't', 'request_id': 'r', 'timeout_seconds': -1}),
            ('animation_review_wait', {'project': 'x', 'thread_id': 't', 'request_id': 'r', 'timeout_seconds': 61}),
            ('animation_review_close', {'project': 'x', 'thread_id': 't', 'request_id': 'r', 'message': None}),
            ('animation_review_close', {'project': 'x', 'thread_id': 't', 'request_id': 'r', 'message': 'a'*4001}),
        ]
        for name, arguments in invalid:
            with self.subTest(name=name, arguments=arguments), self.assertRaises(ValueError):
                command_for(name, arguments)


    def test_bounded_options_and_literal_messages_reach_real_parsers(self):
        from diagnostics_cli import parser as diagnostics_parser
        from review_cli import parser as review_parser
        command = command_for('animation_describe', {'snapshot': '-snapshot.json', 'object_id': '-Base', 'descendants': True,
                                                    'frame': -1, 'offset': 1, 'limit': 2})
        parsed = diagnostics_parser().parse_args(command[1:])
        self.assertEqual((parsed.object_id, parsed.descendants, parsed.frame, parsed.offset, parsed.limit), ('-Base', True, -1, 1, 2))
        self.assertTrue(Path(parsed.snapshot).is_absolute())
        command = command_for('animation_review_close', {'project': 'project.json', 'thread_id': 'task', 'request_id': 'request', 'message': '--literal message'})
        parsed = review_parser().parse_args(command[1:])
        self.assertEqual(parsed.message, '--literal message')
        command = command_for('animation_review_wait', {'project': 'project.json', 'thread_id': 'task', 'request_id': 'request', 'timeout_seconds': 0.25})
        self.assertEqual(review_parser().parse_args(command[1:]).timeout, 0.25)
        command = command_for('animation_snapshot', {'asset': 'asset.blend', 'output': 'snapshot.json', 'frames': list(range(32)), 'timeout_seconds': 3600})
        self.assertEqual(diagnostics_parser().parse_args(command[1:]).timeout, 3600)
        self.assertEqual(execution_timeout('animation_quality', {'timeout_seconds': 7200}), 7260)
        self.assertEqual(execution_timeout('animation_review_wait', {'timeout_seconds': 0}), 30)
        self.assertIn('--reuse', command_for('animation_quality', {'tool': 'inspect', 'spec_path': 'spec.json', 'reuse': True}))
        self.assertNotIn('--reuse', command_for('animation_quality', {'tool': 'inspect', 'spec_path': 'spec.json', 'reuse': False}))
        self.assertEqual(command_for('animation_asset_search', {'provider': 'pixabay', 'query': 'calm ocean'}),
                         ['assets', 'search', 'pixabay', '--query=calm ocean'])


    def test_negative_snapshot_frames_reach_cli_argument_parser(self):
        argv = command_for('animation_snapshot', {'asset': 'asset.blend', 'output': 'snapshot.json', 'frames': [-1, 1]})
        parser = argparse.ArgumentParser()
        parser.add_argument('--frames')
        parsed, _ = parser.parse_known_args(argv)
        self.assertEqual(parsed.frames, '-1,1')


    def test_unknown_and_extra_arguments_cannot_reach_arbitrary_commands(self):
        for name,args in [('execute_python',{'code':'anything'}),('animation_quality',{'tool':'arbitrary','spec_path':'x'}),
                          ('animation_review_status',{'project':'x','script':'run.py'})]:
            with self.subTest(name=name),self.assertRaises(ValueError):command_for(name,args)
        self.assertEqual(command_for('animation_review_status',{'project':'folder with spaces/project.json'}),
                         ['review','status','folder with spaces/project.json'])


    def test_completed_diagnostics_are_bounded_and_report_mismatch_is_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'report.json'
            findings = [{'id': str(i), 'severity': 'info', 'title': 'fact'} for i in range(70)]
            findings.append({'id': 'last', 'severity': 'error', 'title': 'actionable'})
            write_fixture(path, {'schema_version': 'object-animation.diagnostic-report/1', 'status': 'FAIL', 'findings': findings})
            value = {'status': 'FAIL', 'output': str(path), 'findings': 71}
            result, error = completed_result('animation_diagnose', {'output': str(path)}, value, 2)
            self.assertFalse(error)
            self.assertEqual(result['findings_count'], 71)
            self.assertEqual(len(result['findings']), 50)
            self.assertEqual(result['findings'][0]['id'], 'last')
            self.assertTrue(result['findings_truncated'])
            self.assertTrue(completed_result('animation_diagnose', {'output': str(path)}, value, 1)[1])
            with self.assertRaises(ValueError):
                completed_result('animation_diagnose', {'output': str(path)}, {**value, 'findings': 72}, 2)


if __name__=='__main__':unittest.main()
