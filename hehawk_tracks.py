"""Read-only resource recommendations for HeHawk's English workflow."""
import re
from copy import deepcopy

TEXT_CODECS = {'ass', 'ssa', 'subrip', 'srt', 'mov_text', 'webvtt', 'text'}
BITMAP_CODECS = {'dvd_subtitle', 'hdmv_pgs_subtitle', 'dvb_subtitle', 'xsub'}


def describe(stream):
    kind = stream['codec_type']
    tags = deepcopy(stream.get('tags') or {})
    d = deepcopy(stream.get('disposition') or {})
    normalized = {k.lower(): v for k, v in tags.items()}
    raw_language = normalized.get('language')
    lang = str(raw_language or '').strip().lower().replace('_', '-')
    if lang in ('eng', 'en') or lang.startswith(('en-', 'eng-')):
        language = 'english'
    elif lang in ('', 'und', 'unk', 'mul', 'zxx', 'mis'):
        language = 'unknown'
    else:
        language = 'other'
    title = str(normalized.get('title') or '')
    handler = str(normalized.get('handler_name') or '')
    label = title + ' ' + handler
    reasons = [flag for flag in ('comment', 'visual_impaired', 'descriptions',
               'clean_effects', 'lyrics', 'karaoke', 'dependent', 'non_diegetic')
               if d.get(flag)]
    if re.search(r'\b(commentary|audio descriptions?|descriptive audio|described audio|music and effects|isolated score)\b', label, re.I):
        reasons.append('special-purpose label')
    if kind == 'subtitle' and (d.get('forced') or re.search(
            r'\b(forced|signs only|songs only|signs\s*(?:and|&)\s*songs)\b', label, re.I)):
        reasons.append('possible limited-coverage subtitles')
    codec = stream.get('codec_name')
    supported = kind == 'audio' or codec in TEXT_CODECS
    return dict(index=stream['index'], kind=kind, codec=codec,
                language_tag=lang or None, original_language_tag=raw_language,
                language=language, language_source='metadata' if lang else 'absent',
                title=title, handler_name=handler, tags=tags, disposition=d,
                default=bool(d.get('default')), special_purpose=bool(reasons),
                special_purpose_reasons=reasons, supported=supported,
                eligible=language == 'english' and not reasons and supported,
                capabilities=dict(native_preservation='unverified',
                    audio_decode='unverified' if kind == 'audio' else 'not_applicable',
                    subtitle_format=('text' if codec in TEXT_CODECS else
                        'bitmap' if codec in BITMAP_CODECS else 'unknown')
                        if kind == 'subtitle' else 'not_applicable',
                    structural_text_processing=kind == 'subtitle' and codec in TEXT_CODECS))


def select(inventory, kind):
    tracks = [t for t in inventory if t['kind'] == kind]
    main = [t for t in tracks if not t['special_purpose']]
    usable = [t for t in main if t['supported']]
    english = [t for t in usable if t['language'] == 'english']
    unknown = [t for t in usable if t['language'] == 'unknown']
    defaults = [t for t in english if t['default']]
    chosen = None
    if not tracks:
        code, reason = 'absent', 'No embedded tracks of this kind'
    elif len(defaults) == 1:
        chosen = defaults[0]
        code, reason = 'english_default', 'Unique eligible English default track'
    elif len(english) == 1 and not unknown:
        chosen = english[0]
        code, reason = 'english_unique', 'Unique eligible English track'
    elif english:
        code, reason = 'ambiguous', 'Multiple plausible tracks; manual selection required'
    elif len(usable) == 1:
        chosen = usable[0]
        code, reason = 'provisional_language', 'Unique usable main track; language is not English or is unknown'
    elif usable:
        code, reason = 'ambiguous', 'Multiple non-English or unknown-language tracks'
    elif main:
        code, reason = 'unsupported', 'Main tracks exist but text processing is unsupported'
    else:
        code, reason = 'special_purpose_only', 'Only potentially special-purpose tracks exist'
    return dict(status='selected' if chosen else ('absent' if not tracks else 'deferred'),
                status_code=code, selected_index=chosen['index'] if chosen else None,
                reason=reason, eligible_indices=[t['index'] for t in english],
                unknown_indices=[t['index'] for t in main if t['language'] == 'unknown'],
                candidate_indices=[t['index'] for t in usable],
                unsupported_indices=[t['index'] for t in tracks if not t['supported']],
                selected_language=chosen['language'] if chosen else None)


def recommend(streams):
    inventory = [describe(s) for s in streams if s.get('codec_type') in ('audio', 'subtitle')]
    audio = select(inventory, 'audio')
    subtitle = select(inventory, 'subtitle')
    language = audio['selected_language']
    authorization = ('metadata_english' if language == 'english' else
                     'confirmation_required' if language == 'unknown' else
                     'non_english' if language == 'other' else 'no_selected_audio')
    return dict(inventory=inventory, audio=audio, subtitle=subtitle,
                subtitle_preserve_indices=[t['index'] for t in inventory if t['kind'] == 'subtitle'],
                relationship='unverified', english_recognition_authorization=authorization,
                recognition_ready=False)
