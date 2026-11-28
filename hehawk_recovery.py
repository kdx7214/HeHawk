"""Reconcile verified local publication transactions under the project lock."""
import json
import os
import re
from pathlib import Path
from hehawk_publication import atomic_json, digest, project_lock, sync_dir


def reconcile(root, preflight):
    root = Path(root)
    preflight()
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError('Invalid resource root')
    with project_lock(root):
        preflight()
        journal = root / '.publication.json'
        manifest = root / 'manifest.json'
        for p in (journal, manifest):
            if p.is_symlink() or p.resolve() != p:
                raise ValueError('Unsafe metadata path')
        if not journal.exists():
            return 'no_pending_transaction'
        record = json.loads(journal.read_text())
        target, temporary = (root / record[k] for k in ('target', 'temporary'))
        for p in (target, temporary):
            rel = p.relative_to(root)
            if len(rel.parts) != 2 or rel.parts[0] not in ('audio', 'subtitles') or p.resolve() != p or p.is_symlink():
                raise ValueError('Unsafe resource path')
            if p.parent.stat().st_dev != root.stat().st_dev or os.path.ismount(p.parent):
                raise ValueError('Unexpected filesystem')
        if target.parent != temporary.parent or not re.fullmatch(r'\.pending-[0-9a-f]{32}'+re.escape(target.suffix), temporary.name) or target == temporary:
            raise ValueError('Invalid temporary filename')
        if record['state'] == 'pending':
            return 'incomplete_preserved'
        if record['state'] != 'verified':
            raise ValueError('Unknown transaction state')
        entry = {'path': record['target'], 'size': record['size'], 'sha256': record['sha256'], 'timeline_mapping': 'unverified'}
        state = json.loads(manifest.read_text()) if manifest.exists() else {'schema_version': 1, 'resources': {}}
        if state['schema_version'] != 1:
            raise ValueError('Unsupported manifest')
        rid = record['resource_id']
        existing = state['resources'].get(rid)
        if existing is not None and existing != entry:
            raise ValueError('Manifest conflict')
        for p in (target, temporary):
            if p.exists() and (not p.is_file() or p.stat().st_size != entry['size'] or digest(p) != entry['sha256']):
                raise ValueError('Resource integrity failure')
        if target.exists() and temporary.exists() and not target.samefile(temporary):
            raise ValueError('Unexplained destination')
        if target.exists() and not temporary.exists() and existing is None:
            raise ValueError('Cannot establish publication provenance')
        if not target.exists():
            if existing is not None or not temporary.exists():
                raise ValueError('Missing resource')
            preflight()
            os.link(temporary, target)
            sync_dir(target.parent)
        preflight()
        if existing is None:
            state['resources'][rid] = entry
            atomic_json(manifest, state, replace=True)
        temporary.unlink(missing_ok=True)
        sync_dir(target.parent)
        journal.unlink()
        sync_dir(root)
        return 'reconciled'
