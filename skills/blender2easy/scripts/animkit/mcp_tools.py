"""Dependency-free business contracts shared by the MCP adapter and its tests.

This module contains no transport, JSON-RPC framing or session implementation.
"""
import base64
import json
import math
from pathlib import Path
import re

from .quality_tools import TOOLS as QUALITY_TOOLS

QUALITY = sorted(QUALITY_TOOLS)

def schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


STRING = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
FRAME = {'type': 'integer', 'minimum': -1048574, 'maximum': 1048574}
TOOLS = [
    {'name': 'animation_version', 'description': 'Read the installed local toolkit version without inspecting or changing assets.',
     'inputSchema': schema({}), 'annotations': {'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'animation_doctor', 'description': 'Discover local Python, Blender and FFmpeg dependencies and versions. Reports missing dependencies; installs nothing.',
     'inputSchema': schema({}), 'annotations': {'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'animation_asset_search', 'description': 'Prepare a Mixamo or Pixabay search URL for a host browser. Performs no network search, browser opening, sign-in, download or asset import.',
     'inputSchema': schema({'provider': {'type': 'string', 'enum': ['mixamo', 'pixabay']},
                            'query': {'type': 'string', 'minLength': 1, 'maxLength': 200,
                                      'pattern': r'^(?![\s\S]*[\x00-\x1f])[\s\S]+$'}}, ['provider', 'query']),
     'annotations': {'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'animation_quality_catalog', 'description': 'List bundled asset/reference/render capabilities and optional dependencies.',
     'inputSchema': schema({}), 'annotations': {'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'animation_quality', 'description': 'Run a named, bounded Blender inspection/reference/render tool. Input scene stays read-only; writes a new report directory. Supply the spec described by quality catalog.',
     'inputSchema': schema({'tool': {'type': 'string', 'enum': QUALITY}, 'spec_path': STRING,
                            'timeout_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 7200, 'default': 300},
                            'reuse': {'type': 'boolean', 'default': False,
                                      'description': 'Opt in to verified unchanged-output reuse; spec must declare dependenciesComplete:true.'}}, ['tool', 'spec_path']),
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'animation_snapshot', 'description': 'Capture evaluated scene facts at explicit source frames. Writes a new snapshot; never saves the asset.',
     'inputSchema': schema({'asset': STRING, 'output': STRING,
                            'frames': {'type': 'array', 'items': FRAME, 'minItems': 1, 'maxItems': 32, 'uniqueItems': True},
                            'timeout_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 3600, 'default': 120}}, ['asset', 'output', 'frames']),
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'animation_describe', 'description': 'Read a current evaluated snapshot as scoped, paginated scene facts. Aggregate counts cover the complete selected scope; no Blender run or file writes.',
     'inputSchema': schema({'snapshot': STRING, 'object_id': STRING, 'descendants': {'type': 'boolean', 'default': False},
                            'frame': FRAME, 'offset': {'type': 'integer', 'minimum': 0, 'maximum': 2048, 'default': 0},
                            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200, 'default': 50}}, ['snapshot']),
     'annotations': {'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'animation_diagnose', 'description': 'Check declared connection/hinge/structural constraints against a saved scene snapshot. Writes a new report.',
     'inputSchema': schema({'snapshot': STRING, 'contract': STRING, 'output': STRING}, ['snapshot', 'contract', 'output']),
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'animation_compare', 'description': 'Compare snapshots and check explicit preservation invariants. Writes a new report; does not repair geometry.',
     'inputSchema': schema({'before': STRING, 'after': STRING, 'contract': STRING, 'output': STRING}, ['before', 'after', 'contract', 'output']),
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'animation_review_create', 'description': 'Create a scoped user review from a prepared project and spec, bound to the controlling task. Does not open a browser or edit the model.',
     'inputSchema': schema({'project': STRING, 'spec_path': STRING, 'thread_id': STRING}, ['project', 'spec_path', 'thread_id']),
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'animation_review_status', 'description': 'Read saved scoped review feedback and its exact response digest.',
     'inputSchema': schema({'project': STRING}, ['project']), 'annotations': {'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'animation_review_wait', 'description': 'Wait 0–60 seconds (default 30) for current task feedback and acknowledge receipt. This does not wake a finished agent.',
     'inputSchema': schema({'project': STRING, 'thread_id': STRING, 'request_id': STRING,
                            'timeout_seconds': {'type': 'number', 'minimum': 0, 'maximum': 60, 'default': 30}}, ['project', 'thread_id', 'request_id']),
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'animation_review_apply', 'description': 'Apply only confirmed scoped feedback, with the exact response digest already read and the matching controlling task. Never applies revise feedback.',
     'inputSchema': schema({'project': STRING, 'thread_id': STRING, 'request_id': STRING, 'response_digest': STRING}, ['project', 'thread_id', 'request_id', 'response_digest']),
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'animation_review_close', 'description': 'Close the current request for its controlling task with an optional message, preserving feedback history. Does not apply model edits.',
     'inputSchema': schema({'project': STRING, 'thread_id': STRING, 'request_id': STRING,
                            'message': {'type': 'string', 'maxLength': 4000}}, ['project', 'thread_id', 'request_id']),
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
]


def validate_arguments(value, definition, location='arguments'):
    """Validate the JSON-schema subset used by our advertised fixed tools."""
    kind = definition['type']
    if kind == 'object':
        if not isinstance(value, dict):
            raise ValueError(location + ' must be an object')
        properties = definition.get('properties', {})
        if set(value) - set(properties) or not set(definition.get('required', [])).issubset(value):
            raise ValueError(location + ' has unexpected or missing fields')
        for key, item in value.items():
            validate_arguments(item, properties[key], location + '.' + key)
    elif kind == 'string':
        minimum, maximum = definition.get('minLength', 0), definition.get('maxLength', 4096)
        if not isinstance(value, str) or '\0' in value or not minimum <= len(value) <= maximum or (minimum and not value.strip()):
            raise ValueError(location + ' must be a bounded string')
        if 'pattern' in definition and re.search(definition['pattern'], value) is None:
            raise ValueError(location + ' does not match its allowed format')
    elif kind in ('integer', 'number'):
        valid_type = type(value) is int if kind == 'integer' else type(value) in (int, float)
        if not valid_type or (type(value) is float and not math.isfinite(value)):
            raise ValueError(location + ' must be a finite ' + kind)
        if value < definition.get('minimum', -math.inf) or value > definition.get('maximum', math.inf):
            raise ValueError(location + ' is outside its allowed range')
    elif kind == 'boolean':
        if type(value) is not bool:
            raise ValueError(location + ' must be a boolean')
    elif kind == 'array':
        if not isinstance(value, list) or not definition.get('minItems', 0) <= len(value) <= definition.get('maxItems', math.inf):
            raise ValueError(location + ' has an invalid array length')
        for index, item in enumerate(value):
            validate_arguments(item, definition['items'], f'{location}[{index}]')
        if definition.get('uniqueItems') and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise ValueError(location + ' requires unique items')
    else:
        raise ValueError('Unsupported tool schema type: ' + kind)
    if 'enum' in definition and value not in definition['enum']:
        raise ValueError(location + ' is not a supported choice')


def positional(value):
    # Paths beginning with '-' are still paths, never parser options.
    return str(Path(value).expanduser().resolve()) if value.startswith('-') else value


def command_for(name, arguments):
    tool = next((item for item in TOOLS if item['name'] == name), None)
    if tool is None:
        raise ValueError('Unknown tool')
    validate_arguments(arguments, tool['inputSchema'])
    a = arguments
    if name == 'animation_version':
        return ['--version']
    if name == 'animation_doctor':
        return ['doctor']
    if name == 'animation_asset_search':
        return ['assets', 'search', a['provider'], '--query=' + a['query']]
    if name == 'animation_quality_catalog':
        return ['quality', 'catalog']
    if name == 'animation_quality':
        return ['quality', 'run', a['tool'], '--spec=' + a['spec_path'], '--timeout', str(a.get('timeout_seconds', 300))] + (['--reuse'] if a.get('reuse') else [])
    if name == 'animation_snapshot':
        return ['diagnose', 'snapshot', positional(a['asset']), '--output=' + a['output'],
                '--frames=' + ','.join(map(str, a['frames'])), '--timeout', str(a.get('timeout_seconds', 120))]
    if name == 'animation_describe':
        if a.get('descendants') and 'object_id' not in a:
            raise ValueError('descendants requires an object_id')
        result = ['diagnose', 'describe', positional(a['snapshot']), '--offset', str(a.get('offset', 0)), '--limit', str(a.get('limit', 50))]
        if 'object_id' in a:
            result += ['--object=' + a['object_id']]
        if a.get('descendants'):
            result += ['--descendants']
        if 'frame' in a:
            result += ['--frame', str(a['frame'])]
        return result
    if name == 'animation_diagnose':
        return ['diagnose', 'analyze', positional(a['snapshot']), '--contract=' + a['contract'], '--output=' + a['output']]
    if name == 'animation_compare':
        return ['diagnose', 'compare', positional(a['before']), positional(a['after']), '--contract=' + a['contract'], '--output=' + a['output']]
    common = ['review', name.removeprefix('animation_review_'), positional(a['project'])]
    if name == 'animation_review_create':
        return common + ['--spec=' + a['spec_path'], '--thread=' + a['thread_id']]
    if name == 'animation_review_status':
        return common
    common += ['--thread=' + a['thread_id'], '--request=' + a['request_id']]
    if name == 'animation_review_wait':
        return common + ['--timeout', str(a.get('timeout_seconds', 30))]
    if name == 'animation_review_close':
        return common + ['--message=' + a.get('message', '')]
    return common + ['--response=' + a['response_digest']]


def execution_timeout(name, arguments):
    # Give the CLI time to flush its bounded worker's log/provenance on timeout.
    if name in ('animation_quality', 'animation_snapshot'):
        return arguments.get('timeout_seconds', 300 if name == 'animation_quality' else 120) + 60
    if name == 'animation_review_wait':
        return arguments.get('timeout_seconds', 30) + 30
    return 120


def completed_result(name, arguments, value, returncode):
    """Separate completed diagnostics from failures to execute the tool."""
    error = returncode != 0
    if not isinstance(value, dict):
        return value, True
    if name == 'animation_doctor' and returncode == 2 and value.get('status') == 'MISSING_DEPENDENCIES':
        return value, False
    if name not in ('animation_diagnose', 'animation_compare') or value.get('status') not in ('PASS', 'REVIEW_REQUIRED', 'FAIL'):
        return value, error
    expected_code = 2 if value['status'] == 'FAIL' else 0
    if returncode != expected_code:
        return value, True
    report_path = Path(arguments['output']).expanduser().resolve()
    if not isinstance(value.get('output'), str) or Path(value['output']).resolve() != report_path:
        raise ValueError('Diagnostic report path does not match the requested output')
    result = dict(value)
    result['findings_count'] = result.pop('findings')
    if report_path.stat().st_size > 8_000_000:
        result.update(findings=[], findings_truncated=True, findings_note='Report exceeds 8 MB; inspect the full report at output.')
        return result, False
    report = json.loads(report_path.read_text(encoding='utf-8-sig'))
    if (not isinstance(report, dict) or report.get('schema_version') != 'object-animation.diagnostic-report/1'
            or report.get('status') != value['status'] or not isinstance(report.get('findings'), list)
            or len(report['findings']) != result['findings_count']):
        raise ValueError('Diagnostic report does not match its completed summary')
    # Prioritize actionable findings, then preserve report order within severity.
    findings = sorted(report['findings'], key=lambda item: {'error': 0, 'warning': 1, 'info': 2}.get(item.get('severity'), 3))
    preview, size = [], 0
    for finding in findings[:50]:
        encoded = json.dumps(finding, ensure_ascii=False, allow_nan=False)
        if size + len(encoded.encode('utf-8')) > 200_000:
            break
        preview.append(finding)
        size += len(encoded.encode('utf-8'))
    result.update(findings=preview, findings_truncated=len(preview) < len(findings))
    return result, False


def tool_content(value):
    """Inline only known rendered PNGs under this run's output directory."""
    content = [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]
    if not isinstance(value, dict) or value.get('status') != 'complete' or not value.get('outputDir'):
        return content
    root = Path(value['outputDir']).resolve()
    candidate = None
    if value.get('tool') in ('reference', 'evidence'):
        candidate = root / 'payload' / ('comparison.png' if value['tool'] == 'reference' else 'contact_sheet.png')
    elif value.get('tool') == 'authored-render':
        report_path = Path(value.get('report', '')).resolve()
        if report_path.is_relative_to(root) and report_path.is_file():
            report = json.loads(report_path.read_text(encoding='utf-8'))
            if report.get('renders'):
                candidate = Path(report['renders'][0]['path']).resolve()
    if candidate and candidate.resolve().is_relative_to(root) and candidate.is_file() and candidate.stat().st_size <= 3_000_000:
        data = candidate.read_bytes()
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            content.append({'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(data).decode('ascii')})
    return content
