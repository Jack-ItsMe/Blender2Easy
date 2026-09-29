"""Attach bounded, source-bound diagnostic evidence to a frozen review."""
from copy import deepcopy
from pathlib import Path

from .common import read_json, sha256, digest
from .diagnostics import fingerprint


def project_source(source, project, path, asset_hashes):
    source_path = Path(source['path']).resolve()
    native = project.get('source', {})
    if native and not native.get('overrides'):
        if source_path == Path(native['blend']).resolve() and asset_hashes.get(str(source_path)) == source['sha256']:
            return True
    builds = path.parent / '.animation' / 'builds'
    if not source_path.is_relative_to(builds):
        return False
    try:
        build = read_json(source_path.parent / 'build.json')
        inputs = build['inputs']
        return (build['status'] == 'PASS' and Path(build['blend']).resolve() == source_path
                and build['blend_sha256'] == source['sha256']
                and inputs.get('scene') == project.get('scene')
                and inputs.get('source') == project.get('source')
                and inputs.get('units', 'm') == project.get('units', 'm')
                and inputs.get('assets', []) == project.get('assets', [])
                and inputs.get('asset_hashes', {}) == asset_hashes
                and inputs.get('fps') == project['render']['fps'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def attach_reports(evidence, project, path, asset_hashes):
    """Expand requested report findings, retaining report and input fingerprints."""
    from .review import _fields, _require, _text
    reports = evidence.get('reports', [])
    _require(isinstance(reports, list) and len(reports) <= 4, 'evidence.reports needs at most four reports')
    findings = deepcopy(evidence.get('findings', []))
    _require(isinstance(findings, list), 'evidence.findings must be a list')
    frozen = []
    for entry in reports:
        _fields(entry, {'path', 'finding_ids', 'kind'}, 'evidence report', {'path'})
        _require(entry.get('kind', 'diagnostic') in ('diagnostic', 'quality'), 'Unsupported evidence report kind')
        if entry.get('kind') == 'quality':
            from .quality_review import attach_quality
            attached = attach_quality(entry, project, path, asset_hashes)
            findings.extend(attached['findings'])
            _require(len(findings) <= 24, 'Too many findings; choose up to 24 finding_ids for this review')
            for key in ('references', 'checkpoints'):
                _require(isinstance(evidence.get(key, []), list), 'evidence.' + key + ' must be a list')
                evidence.setdefault(key, []).extend(attached[key])
            frozen.append(attached['report'])
            continue
        raw = Path(_text(entry['path'], 'diagnostic report path', 4096)).expanduser()
        report_path = (raw if raw.is_absolute() else path.parent / raw).resolve()
        _require(report_path.is_file() and report_path.stat().st_size <= 8_000_000,
                 'Diagnostic report must be an existing JSON file up to 8 MB')
        report_hash = sha256(report_path)
        report = read_json(report_path)
        _require(isinstance(report, dict), 'Diagnostic report must be an object')
        _require(report.get('schema_version') == 'object-animation.diagnostic-report/1', 'Unsupported diagnostic report schema')
        _require(report.get('kind') in ('analyze', 'compare'), 'Unsupported diagnostic report kind')
        sources = report.get('sources', [])
        source_count = 2 if report['kind'] == 'compare' else 1
        _require(isinstance(sources, list) and len(sources) == source_count,
                 'Diagnostic report has an invalid source count')
        provenance = report.get('provenance', {})
        _require(isinstance(provenance, dict), 'Diagnostic provenance must be an object')
        historical = report['kind'] == 'compare' and provenance.get('historical_baseline') is True
        attachments = provenance.get('snapshot_files', [])
        _require(isinstance(attachments, list), 'Diagnostic snapshot files must be an array')
        snapshot_hashes = report.get('snapshot_sha256', [])
        if historical or attachments:
            _require(len(attachments) == len(sources), 'Diagnostic report requires all of its frozen snapshot files')
            _require(isinstance(snapshot_hashes, list) and len(snapshot_hashes) == len(sources),
                     'Diagnostic report needs normalized snapshot fingerprints')
        checked_files = []
        for index, item in enumerate(attachments):
            _require(isinstance(item, dict) and isinstance(item.get('path'), str)
                     and isinstance(item.get('sha256'), str), 'Invalid diagnostic snapshot fingerprint')
            snapshot_path = Path(item['path']).resolve()
            _require(snapshot_path.is_file() and sha256(snapshot_path) == item['sha256'], 'Diagnostic snapshot changed', 409)
            snapshot = read_json(snapshot_path)
            _require(isinstance(snapshot, dict) and snapshot.get('source') == sources[index],
                     'Diagnostic snapshot/source mismatch', 409)
            _require(fingerprint(snapshot) == snapshot_hashes[index], 'Diagnostic snapshot/report mismatch', 409)
            checked_files.append({'path': str(snapshot_path), 'sha256': item['sha256']})
        contract = provenance.get('contract_file')
        if contract is not None:
            _require(isinstance(contract, dict) and isinstance(contract.get('path'), str)
                     and isinstance(contract.get('sha256'), str), 'Invalid diagnostic contract fingerprint')
            contract_path = Path(contract['path']).resolve()
            _require(contract_path.is_file() and sha256(contract_path) == contract['sha256'], 'Diagnostic contract changed', 409)
            _require(fingerprint(read_json(contract_path)) == report.get('contract_sha256'),
                     'Diagnostic contract/report mismatch', 409)
            checked_files.append({'path': str(contract_path), 'sha256': contract['sha256']})
        checked_sources = []
        for index, source in enumerate(sources):
            _require(isinstance(source, dict) and isinstance(source.get('path'), str)
                     and isinstance(source.get('sha256'), str), 'Invalid diagnostic source fingerprint')
            source_path = Path(source['path']).resolve()
            if historical and index < len(sources) - 1:
                continue  # Its immutable snapshot is the baseline; the authored asset may have changed.
            _require(source_path.is_file() and sha256(source_path) == source['sha256'], 'Diagnostic source changed; rerun diagnosis', 409)
            checked_sources.append({'path': str(source_path), 'sha256': source['sha256']})
        subject = checked_sources[-1] if report.get('kind') == 'compare' else checked_sources[0]
        _require(project_source(subject, project, path, asset_hashes),
                 'Diagnostic report does not describe this project source/build', 409)
        source_findings = report.get('findings', [])
        _require(isinstance(source_findings, list) and all(isinstance(item, dict) for item in source_findings),
                 'Diagnostic findings must be objects')
        requested = entry.get('finding_ids')
        if requested is not None:
            _require(isinstance(requested, list) and len(requested) <= 24 and all(isinstance(item, str) for item in requested)
                     and len(set(requested)) == len(requested), 'finding_ids must be unique IDs, at most 24')
            _require(set(requested).issubset({item.get('id') for item in source_findings}), 'Unknown requested diagnostic finding')
        focus = project['_review_focus']
        lo, hi = focus['source_range']
        selected, finding_map = [], {}
        for item in source_findings:
            if requested is not None and item.get('id') not in requested:
                continue
            _require(isinstance(item.get('object_ids'), list) and all(isinstance(obj, str) for obj in item['object_ids']),
                     'Diagnostic finding object IDs must be a list of strings')
            _require(type(item.get('source_frame', focus['source_frame'])) is int,
                     'Diagnostic finding source frame must be an integer')
            eligible = (bool(item.get('object_ids')) and set(item['object_ids']).issubset(focus['object_ids'])
                        and lo <= item.get('source_frame', focus['source_frame']) <= hi)
            if requested is not None:
                _require(eligible, 'Requested diagnostic finding is outside this review focus')
            if not eligible or (requested is None and item.get('severity') == 'info'
                                and item.get('constraint') != 'review_required'):
                continue
            clean = {key: deepcopy(item[key]) for key in ('id', 'title', 'severity', 'object_ids', 'source_frame', 'camera_id') if key in item}
            clean['id'] = 'd-' + report_hash[:10] + '-' + digest(item['id'])[:12]
            finding_map[clean['id']] = item['id']
            clean.setdefault('source_frame', focus['source_frame'])
            clean.setdefault('camera_id', focus['camera_id'])
            selected.append(clean)
        _require(len(findings) + len(selected) <= 24, 'Too many findings; choose up to 24 finding_ids for this review')
        findings.extend(selected)
        _require(sha256(report_path) == report_hash, 'Diagnostic report changed during attachment', 409)
        frozen.append({'path': str(report_path), 'sha256': report_hash, 'sources': checked_sources, 'files': checked_files,
                       'finding_map': finding_map})
    evidence['findings'] = findings
    if reports:
        evidence['reports'] = frozen
    return evidence


def check_reports(evidence):
    from .review import _require
    for report in evidence.get('reports', []):
        for item in [report, *report['sources'], *report.get('files', [])]:
            path = Path(item['path'])
            _require(path.is_file() and sha256(path) == item['sha256'],
                     'Diagnostic evidence changed; ask the agent for a new review', 409)
