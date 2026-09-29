#!/usr/bin/env python3
"""Install the Blender2Easy skill locally; existing skills need --replace."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import os
import shutil
import tempfile

SOURCE = Path(__file__).resolve().parents[1] / 'skills' / 'blender2easy'
IGNORED = {'__pycache__', '.animation', 'node_modules', '.git', '.venv-mcp', 'target'}

def excluded(directory, names):
    parent = Path(directory)
    return [name for name in names if name in IGNORED or name.endswith('.pyc')
            or (parent.name == 'editor' and name == 'projects')]

def install(destination, replace=False):
    destination = Path(destination).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / 'blender2easy'
    legacy = destination / 'object-animation'
    existing = [path for path in (target, legacy) if path.exists() or path.is_symlink()]
    for path in existing:
        if path.is_symlink() or path.resolve().parent != destination or not path.is_dir():
            raise ValueError(f'Refusing to replace a link or non-directory: {path}')
    if existing and not replace:
        raise ValueError('Existing skill found. Re-run with --replace to back it up outside the skills directory: '
                         + ', '.join(str(path) for path in existing))
    if not (SOURCE / 'SKILL.md').is_file():
        raise ValueError('Skill source is missing; run this script from a complete repository checkout.')
    temporary = Path(tempfile.mkdtemp(prefix='.blender2easy-install-', dir=destination.parent))
    staged = temporary / 'blender2easy'
    moved = []
    try:
        shutil.copytree(SOURCE, staged, ignore=excluded)
        if existing:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup_root = destination.parent / 'skill-backups' / ('blender2easy-' + stamp)
            backup_root.mkdir(parents=True, exist_ok=False)
            for path in existing:
                backup = backup_root / path.name
                path.rename(backup)
                moved.append((path, backup))
        staged.rename(target)
    except Exception:
        for original, backup in reversed(moved):
            if not original.exists() and backup.exists():
                backup.rename(original)
        raise
    finally:
        # Only remove the unique staging directory created by this call.
        if temporary.parent == destination.parent and temporary.name.startswith('.blender2easy-install-'):
            shutil.rmtree(temporary)
    return target, [backup for _, backup in moved]

def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='Before --replace, stop editors, render jobs and MCP processes using the old installation. Projects inside it remain in the backup and are not merged into the new copy.')
    default = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'skills'
    parser.add_argument('--dest', type=Path, default=default, help='Parent skills directory (default: $CODEX_HOME/skills or ~/.codex/skills)')
    parser.add_argument('--replace', action='store_true', help='Back up and replace an existing blender2easy or legacy object-animation skill')
    args = parser.parse_args()
    try:
        target, backups = install(args.dest, args.replace)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    print('Installed:', target)
    for backup in backups:
        print('Backup:', backup)
    if backups:
        print('Projects inside the old installation remain in these backups. Reopen them with explicit project/workspace paths.')
    print('Open a new agent chat and invoke $blender2easy. Dependencies are installed separately; see README.md.')

if __name__ == '__main__':
    main()
