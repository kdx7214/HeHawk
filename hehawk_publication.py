"""Local resource publication primitives; Linux, cooperative writers only."""
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path
from contextlib import contextmanager


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value, replace=False):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.json-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(name, path)
        else:
            os.link(name, path)
        sync_dir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def project_lock(root):
    fd = os.open(root / '.publication.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def publish(root, relative, resource_id, producer, verifier, preflight):
    """Publish one resource. Caller supplies trusted workspace preflight and callbacks.

    Producer writes only the supplied temporary path; verifier raises on failure.
    Any interrupted transaction blocks subsequent writes pending reconciliation.
    """
    root = Path(root)
    relative = Path(relative)
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError('Invalid resource root')
    if relative.is_absolute() or '..' in relative.parts or len(relative.parts) != 2 or relative.parts[0] not in ('audio', 'subtitles'):
        raise ValueError('Invalid resource destination')
    target = root / relative
    journal = root / '.publication.json'
    manifest = root / 'manifest.json'
    preflight()
    with project_lock(root):
        preflight()
        for path in (target, target.parent, journal, manifest):
            if path.resolve() != path or path.is_symlink():
                raise ValueError('Unsafe resource path')
        if journal.exists():
            raise RuntimeError('Pending publication requires reconciliation')
        if target.exists():
            raise FileExistsError(target)
        state = json.loads(manifest.read_text()) if manifest.exists() else {'schema_version': 1, 'resources': {}}
        if state['schema_version'] != 1 or resource_id in state['resources']:
            raise ValueError('Manifest conflict')
        target.parent.mkdir(mode=0o700, exist_ok=True)
        if target.parent.stat().st_dev != root.stat().st_dev or os.path.ismount(target.parent):
            raise ValueError('Unexpected destination filesystem')
        sync_dir(root)
        import uuid
        temporary = target.parent / ('.pending-' + uuid.uuid4().hex + target.suffix)
        record = {'resource_id': resource_id, 'target': relative.as_posix(), 'temporary': temporary.relative_to(root).as_posix(), 'state': 'pending'}
        atomic_json(journal, record)
        preflight()
        producer(temporary)
        if temporary.is_symlink() or not temporary.is_file() or temporary.stat().st_size == 0:
            raise ValueError('Invalid temporary resource')
        verifier(temporary)
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        record.update(state='verified', size=temporary.stat().st_size, sha256=digest(temporary))
        atomic_json(journal, record, replace=True)
        preflight()
        os.link(temporary, target)
        sync_dir(target.parent)
        state['resources'][resource_id] = {'path': relative.as_posix(), 'size': record['size'], 'sha256': record['sha256'], 'timeline_mapping': 'unverified'}
        atomic_json(manifest, state, replace=True)
        temporary.unlink()
        sync_dir(target.parent)
        journal.unlink()
        sync_dir(root)
        return state['resources'][resource_id]
