"""Explicit, mount-checked workspace initialization (Linux)."""
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path


def absolute(value):
    p = Path(value)
    if not p.is_absolute():
        raise ValueError(f'Absolute path required: {value}')
    return p.resolve()


def preflight(config):
    media = absolute(config['media_root'])
    root = absolute(config['workspace_root'])
    mount = absolute(config['required_workspace_mount'])
    if not os.path.ismount(mount):
        raise ValueError(f'Required mount unavailable: {mount}')
    if not root.is_relative_to(mount) or root == mount:
        raise ValueError('Workspace must be below required mount')
    if root.is_relative_to(media) or media.is_relative_to(root):
        raise ValueError('Workspace and media root overlap')
    reserve = config['minimum_free_gib']
    if type(reserve) not in (int, float) or not 0 <= reserve < float('inf'):
        raise ValueError('Invalid free-space reserve')
    if shutil.disk_usage(mount).free < reserve * 1024**3:
        raise ValueError('Insufficient free space')
    if not os.access(mount, os.W_OK) or os.statvfs(mount).f_flag & os.ST_RDONLY:
        raise ValueError('Workspace mount is not writable')
    return media, root, mount


def safe_path(root, relative, mount):
    p = root / relative
    if p.resolve() != p or not p.is_relative_to(root):
        raise ValueError(f'Unsafe workspace path: {p}')
    for ancestor in (p, *p.parents):
        if ancestor == mount:
            break
        if ancestor.exists() and (ancestor.stat().st_dev != mount.stat().st_dev or os.path.ismount(ancestor)):
            raise ValueError(f'Unexpected filesystem: {ancestor}')
    return p


def publish_once(path, data):
    # Publish complete files without replacing existing persistent state.
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.init-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            return False
        return True
    finally:
        os.unlink(name)


def initialize(inventory, config):
    media, root, mount = preflight(config)
    source = Path(inventory['source'])
    if not source.is_relative_to(media):
        raise ValueError('Initial prototype requires media inside configured library')
    relative = source.relative_to(media)
    identity = inventory['identity']
    if identity['type'] == 'episode' and len(relative.parts) == 4 and relative.parts[0] == 'Series':
        project_rel = Path('projects') / relative.with_suffix('')
    elif identity['type'] == 'movie' and len(relative.parts) == 2 and relative.parts[0] == 'Movies':
        project_rel = Path('projects') / relative.with_suffix('')
    else:
        raise ValueError('Unsupported library layout for initialization')
    project = safe_path(root, project_rel, mount)
    manifest = safe_path(root, project_rel / 'project.json', mount)
    dirs = [safe_path(root, project_rel / n, mount) for n in ('resources','analysis','recognition','exports')]
    dirs += [safe_path(root, Path(n), mount) for n in ('cache','temp')]
    metadata = inventory.get('nfo_metadata') or {}
    snapshot = None
    if identity['type'] == 'episode' and metadata.get('status') == 'parsed':
        raw = Path(metadata['path']).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != metadata['sha256']:
            raise ValueError('NFO changed during inspection; retry')
        snapshot = safe_path(root, project_rel.parent.parent / 'metadata' / f'tvshow-{digest}.nfo', mount)
        dirs.append(snapshot.parent)
    if manifest.exists():
        existing = json.loads(manifest.read_text())
        if existing.get('schema_version') != 1 or existing.get('media_relative_path') != relative.as_posix():
            raise ValueError('Existing project manifest conflicts with source')
    preflight(config)
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if snapshot:
        publish_once(snapshot, raw)
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != digest:
            raise ValueError('Existing NFO snapshot has incorrect hash')
    document = {'schema_version': 1, 'project_id': str(uuid.uuid4()),
                'media_relative_path': relative.as_posix(),
                'identity': {k:v for k,v in identity.items() if k != 'nfo'},
                'source_size': source.stat().st_size,
                'nfo_snapshot': snapshot.relative_to(root).as_posix() if snapshot else None}
    created = publish_once(manifest, (json.dumps(document, indent=2, ensure_ascii=False)+'\n').encode())
    saved = json.loads(manifest.read_text())
    if saved.get('schema_version') != 1 or saved.get('media_relative_path') != relative.as_posix():
        raise ValueError('Project manifest conflicts with source')
    return {'status': 'created' if created else 'existing', 'path': str(project), 'manifest': saved}
