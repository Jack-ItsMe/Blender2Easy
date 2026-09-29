#!/usr/bin/env python3
"""Build a self-contained skill ZIP and SHA-256 manifest without local state."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'skills' / 'blender2easy'
EXCLUDED = {'__pycache__', '.animation', 'node_modules', '.git', '.venv-mcp', 'target'}

def package(output):
    output = Path(output).resolve()
    if output.is_relative_to(SOURCE):
        raise ValueError('Output must be outside the skill source directory.')
    output.mkdir(parents=True, exist_ok=True)
    version = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)', (SOURCE / 'scripts/animkit/__init__.py').read_text(encoding='utf-8'))[1]
    archive = output / f'blender2easy-v{version}.zip'
    if archive.exists():
        raise FileExistsError(f'Preserving existing archive: {archive}')
    files = []
    for path in sorted(SOURCE.rglob('*')):
        relative = path.relative_to(SOURCE)
        if (not path.is_file() or path.suffix == '.pyc'
                or any(part in EXCLUDED for part in relative.parts)
                or relative.parts[:2] == ('editor', 'projects')):
            continue
        if path.is_symlink():
            raise ValueError(f'Symlinks are not supported in releases: {relative}')
        files.append((path, relative.as_posix()))
    records = []
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as result:
        for path, relative in files:
            data = path.read_bytes()
            item = zipfile.ZipInfo('blender2easy/' + relative, (2026, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            result.writestr(item, data)
            records.append({'path': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    with zipfile.ZipFile(archive) as result:
        assert result.testzip() is None
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = output / f'blender2easy-v{version}-manifest.json'
    manifest.write_text(json.dumps({'version': version, 'archive': archive.name, 'sha256': checksum, 'files': records}, indent=2) + '\n', encoding='utf-8')
    (output / f'blender2easy-v{version}.sha256').write_text(f'{checksum}  {archive.name}\n', encoding='utf-8')
    return archive, len(records)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    archive, count = package(args.output)
    print(f'{archive} ({count} files)')
