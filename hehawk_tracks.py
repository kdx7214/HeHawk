"""Conservative, read-only track recommendations (English transcription workflow)."""
import re

TEXT_CODECS = {'ass', 'ssa', 'subrip', 'srt', 'mov_text', 'webvtt', 'text'}


def recommend(streams):
    inventory = []
    for s in streams:
        if s.get('codec_type') not in ('audio', 'subtitle'):
            continue
        tags = {k.lower(): v for k, v in s.get('tags', {}).items()}
        d = s.get('disposition', {})
        lang = str(tags.get('language') or '').strip().lower()
        language = 'english' if lang in ('eng', 'en') or lang.startswith('en-') else ('unknown' if lang in ('', 'und', 'unk', 'mul') else 'other')
        title = str(tags.get('title') or '')
        special = bool(d.get('comment') or d.get('visual_impaired') or d.get('descriptions') or d.get('clean_effects') or d.get('lyrics') or d.get('karaoke') or re.search(r'\b(commentary|audio description|descriptive audio|forced|signs only|songs only)\b', title, re.I) or d.get('forced'))
        supported = s['codec_type'] == 'audio' or s.get('codec_name') in TEXT_CODECS
        inventory.append(dict(index=s['index'], kind=s['codec_type'], codec=s.get('codec_name'), language_tag=lang or None, language=language, title=title, default=bool(d.get('default')), special_purpose=special, supported=supported, eligible=language=='english' and not special and supported))
    def select(kind):
        tracks = [t for t in inventory if t['kind']==kind]
        candidates = [t for t in tracks if t['eligible']]
        unknown = [t for t in tracks if t['language']=='unknown' and not t['special_purpose']]
        defaults = [t for t in candidates if t['default']]
        chosen = None
        if len(defaults)==1:
            chosen, reason = defaults[0], 'Unique eligible English default track'
        elif len(candidates)==1 and not unknown:
            chosen, reason = candidates[0], 'Unique eligible English track; default flag not required'
        else:
            reason = 'Ambiguous candidates or unknown language' if candidates or unknown else 'No eligible English track'
        return dict(status='selected' if chosen else ('deferred' if tracks else 'absent'), selected_index=chosen['index'] if chosen else None, reason=reason, eligible_indices=[t['index'] for t in candidates], unknown_indices=[t['index'] for t in unknown])
    audio, subtitle = select('audio'), select('subtitle')
    return dict(inventory=inventory, audio=audio, subtitle=subtitle, subtitle_preserve_indices=[t['index'] for t in inventory if t['kind']=='subtitle'], relationship='unverified', recognition_ready=False)
