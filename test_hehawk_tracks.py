"""Synthetic regression tests for read-only track recommendations."""
import unittest
from copy import deepcopy
from hehawk_tracks import recommend


def track(index, kind='audio', language='eng', codec=None, title='', **flags):
    tags = {'title': title}
    if language is not None:
        tags['language'] = language
    return dict(index=index, codec_type=kind,
                codec_name=codec or ('aac' if kind == 'audio' else 'ass'),
                tags=tags, disposition=flags)


class TrackTests(unittest.TestCase):
    def test_audio_selection(self):
        cases = [
            ([], None, 'absent', 'no_selected_audio'),
            ([track(1)], 1, 'english_unique', 'metadata_english'),
            ([track(1, language=None)], 1, 'provisional_language', 'confirmation_required'),
            ([track(1, language='swe')], 1, 'provisional_language', 'non_english'),
            ([track(1), track(2)], None, 'ambiguous', 'no_selected_audio'),
            ([track(1), track(2, default=1)], 2, 'english_default', 'metadata_english'),
            ([track(1, default=1), track(2, default=1)], None, 'ambiguous', 'no_selected_audio'),
            ([track(1), track(2, language='jpn', default=1)], 1, 'english_unique', 'metadata_english'),
            ([track(1), track(2, language=None)], None, 'ambiguous', 'no_selected_audio'),
            ([track(1, default=1), track(2, language=None)], 1, 'english_default', 'metadata_english'),
            ([track(1, language=None), track(2, language='und')], None, 'ambiguous', 'no_selected_audio'),
            ([track(1, language='jpn'), track(2, language='swe')], None, 'ambiguous', 'no_selected_audio'),
            ([track(1), track(2, comment=1, default=1)], 1, 'english_unique', 'metadata_english'),
            ([track(1, title='Audio Description')], None, 'special_purpose_only', 'no_selected_audio'),
            ([track(1, clean_effects=1)], None, 'special_purpose_only', 'no_selected_audio'),
            ([track(1, forced=1)], 1, 'english_unique', 'metadata_english'),
        ]
        for streams, index, code, auth in cases:
            with self.subTest(streams=streams):
                r = recommend(streams)
                self.assertEqual((r['audio']['selected_index'], r['audio']['status_code'], r['english_recognition_authorization']), (index, code, auth))
                self.assertFalse(r['recognition_ready'])

    def test_subtitle_selection(self):
        def sub(index, **kw):
            return track(index, kind='subtitle', **kw)
        cases = [
            ([], None, 'absent'),
            ([sub(2)], 2, 'english_unique'),
            ([sub(2, language=None)], 2, 'provisional_language'),
            ([sub(2, language='jpn')], 2, 'provisional_language'),
            ([sub(2), sub(3, hearing_impaired=1)], None, 'ambiguous'),
            ([sub(2), sub(3, forced=1)], 2, 'english_unique'),
            ([sub(2, title='Signs & Songs')], None, 'special_purpose_only'),
            ([sub(2, codec='dvd_subtitle')], None, 'unsupported'),
            ([sub(2, codec='hdmv_pgs_subtitle', forced=1)], None, 'special_purpose_only'),
            ([sub(2, codec='dvd_subtitle'), sub(3)], 3, 'english_unique'),
            ([sub(2, codec='mov_text', hearing_impaired=1)], 2, 'english_unique'),
            ([sub(2), sub(3, default=1)], 3, 'english_default'),
        ]
        for streams, index, code in cases:
            with self.subTest(streams=streams):
                r = recommend(streams)
                self.assertEqual((r['subtitle']['selected_index'], r['subtitle']['status_code']), (index, code))
                self.assertEqual(r['subtitle_preserve_indices'], [s['index'] for s in streams])
                self.assertEqual(r['relationship'], 'unverified')

    def test_metadata_and_capabilities(self):
        streams = [track(1, language='EN_us', dub=1), track(2, kind='subtitle', codec='dvd_subtitle')]
        streams[0]['tags']['handler_name'] = 'SoundHandler'
        before = deepcopy(streams)
        r = recommend(streams)
        self.assertEqual(streams, before)
        a, s = r['inventory']
        self.assertEqual(a['original_language_tag'], 'EN_us')
        self.assertEqual(a['language'], 'english')
        self.assertEqual(a['handler_name'], 'SoundHandler')
        self.assertEqual(a['disposition']['dub'], 1)
        self.assertEqual(a['capabilities']['audio_decode'], 'unverified')
        self.assertEqual(s['capabilities']['subtitle_format'], 'bitmap')
        self.assertFalse(s['capabilities']['structural_text_processing'])
        a['tags']['language'] = 'changed'
        self.assertEqual(streams, before)

    def test_non_media_streams_ignored(self):
        r = recommend([dict(index=0, codec_type='video'), dict(index=4, codec_type='attachment')])
        self.assertEqual(r['inventory'], [])


if __name__ == '__main__':
    unittest.main()
