"""Read-only Kodi TV show metadata inspection; no network access."""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def value(node, key):
    return (node.findtext(key) or '').strip() or None


def inspect_nfo(path, identity=None):
    path = Path(path)
    result = {'path': str(path), 'status': 'unavailable', 'warnings': []}
    warnings = result['warnings']
    try:
        with path.open('rb') as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('NFO exceeds 8 MiB inspection limit')
        result['sha256'] = hashlib.sha256(raw).hexdigest()
        root = ET.fromstring(raw)
        if root.tag != 'tvshow':
            raise ValueError('Expected tvshow root element')
    except FileNotFoundError:
        result['status'] = 'missing'
        return result
    except (OSError, ValueError, ET.ParseError) as exc:
        warnings.append(str(exc))
        return result
    result['status'] = 'parsed'
    for key in ('title', 'originaltitle', 'showtitle', 'year', 'premiered', 'originallanguage', 'plot'):
        result[key] = value(root, key)
    identifiers = {}

    def add(provider, identifier, source, default=False):
        if not identifier or not provider:
            return
        provider = provider.strip().lower()
        identifier = str(identifier).strip()
        if not provider or not identifier:
            return
        entries = identifiers.setdefault(provider, {})
        entries.setdefault(identifier, []).append({'source': source, 'default': default})

    for node in root.findall('uniqueid'):
        add(node.get('type'), node.text, 'uniqueid', node.get('default', '').lower() == 'true')
    for provider in ('imdb', 'tmdb', 'tvdb'):
        add(provider, value(root, provider + 'id'), provider + 'id')
    guide = value(root, 'episodeguide')
    result['episodeguide_raw'] = guide
    if guide and guide.startswith('{'):
        try:
            for provider, identifier in json.loads(guide).items():
                if isinstance(identifier, (str, int)) and not isinstance(identifier, bool):
                    add(provider, identifier, 'episodeguide')
        except (ValueError, AttributeError) as exc:
            warnings.append(f'Invalid JSON episodeguide: {exc}')
    result['legacy_id'] = value(root, 'id')
    result['identifiers'] = identifiers
    for provider, entries in identifiers.items():
        if len(entries) > 1:
            warnings.append(f'Conflicting {provider} identifiers')
    result['actors'] = [dict(name=value(node, 'name'), role=value(node, 'role'),
                             order=value(node, 'order'), tmdbid=value(node, 'tmdbid'),
                             source_position=i)
                        for i, node in enumerate(root.findall('actor'))]
    result['named_seasons'] = [{'number': node.get('number'), 'name': (node.text or '').strip()}
                               for node in root.findall('namedseason')]
    years = {}
    for key in ('year', 'premiered'):
        text = result[key]
        if text and re.match(r'^\d{4}(?:$|-)', text):
            years[key] = int(text[:4])
    if identity and identity.get('year') is not None:
        years['directory'] = identity['year']
    if len(set(years.values())) > 1:
        warnings.append(f'Conflicting year observations: {years}')
    if identity and identity.get('series') and result['title'] and identity['series'].casefold() != result['title'].casefold():
        warnings.append('Directory series name differs from NFO title')
    result['year_observations'] = years
    return result
