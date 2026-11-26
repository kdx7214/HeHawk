# HeHawk — Current session checkpoint (2026-11-25 local time)

This supersedes the resume instructions in DARS_PROJECT_HANDOFF.md; retain that file as historical context. ROADMAP.md and REFERENCES.md remain useful. This checkpoint records aggregate results and engineering decisions only; episode-specific evidence, media, transcripts, voice vectors and review JSON remain local.

## Completed experiments
- SWAN diagnostics and conservative timing normalization: 415-cue regression, 24 overlaps reduced to zero, 27 short cues reduced to zero, 288 cues changed, maximum extension 2976 ms. Independent audit passed; playback confirmed improved readability. Preserve start times and text, prefer 24 ms gap, extend only to needed reading duration and available space. Protect complex conflicts; do not extend final cue without media duration. Whitespace normalization deferred until reconciliation. Some apparent missing dialogue was already absent from original embedded captions, not removed by SWAN.
- MAGPIE: inventory 265 discrepancy candidates (50 reference-only, 127 competing, 88 recognition-only); 95 provisional outside-caption insertions, then four human-approved boundary reconstructions. One rejected reconstruction combines two speakers. Latest merged output 518 cues; final experimental SWAN pass leaves one protected 120 ms overlap. Independent audit passed; not all insertions reviewed. Preserve proposal hashes and decisions.
- CHIRP: local acoustic transitions and diarization compared with full-episode diarization. Global baseline 41:47 audio, 13:38 runtime at 16 threads, 16 provisional clusters. Global context improved selected regression cases but coverage remains incomplete. Full scans: 139/703 ASR cues and 124/415 reference cues flagged multiple speakers; not verified error counts. Three human-reviewed extreme cases demonstrate false rapid speaker oscillation and overcounted transitions. Preserve short events; no hard minimum utterance duration. Distinguish speakers, turns, overlap, and conversational floor. Raw assignments immutable.
- BOWERBIRD assisted collection: 16 reviewed samples, 10 known single-speaker (including singing), 5 mixed, 1 unidentified. Manual collection added six samples, 63 seconds selected duration, approximate boundaries. Both collectors and comparison utilities ran successfully locally. Model pyannote/wespeaker-voxceleb-resnet34-LM; exact revision unpinned. Cached cross comparison completed, 22 samples, 96 cross pairs. Independent same-speaker speech comparisons 0.5641 and 0.7721; strongest different-speaker cross comparison 0.4237. A 0.9786 same-speaker comparison shares 5.118 seconds of source audio: exclude from independent validation. Small sample, no production threshold. Singing/speech similarity 0.39; singing/singing 0.771, potentially confounded by music and overlapping source intervals (check all pairs). Long singing selection includes instrumental pauses. Mixed passages can resemble one dominant speaker; whole-passage embeddings cannot prove single-speaker status.

## Exact next step
1. Implement read-only source interval overlap audit across both BOWERBIRD manifests. Compare common source identity, audio track and episode-relative intervals, flag partial/complete overlap and exclude dependent pairs from independent validation. Inspect actual schemas first. Include synthetic tests. Preserve both collections.
2. Investigate vocal coverage vs recording duration, especially singing with instrumental pauses. Speech activity estimates are not singing ground truth. Compare full audio, individual verified phrases and derived concatenations; preserve originals.
3. Sliding-window embedding experiment on three human-reviewed mixed passages, 0.5/1/2/3-second windows as experimental settings. Compare against independent reference samples, retain uncertainty and unknown speakers. Evaluate false/missed transitions separately. Then investigate short-utterance aggregation and stability analysis (persistence, alternation, lexical and acoustic corroboration).
4. Continue CHIRP cue-level refinement, MAGPIE reconciliation, SWAN final presentation, ZOOKEEPER integration. Capture working environments and installation instructions before drift.

## Local resume inputs (do not publish contents)
- nutcracker/Angel/S03E01/manifest.json and similarity_01.json
- nutcracker/Angel/S03E01_manual/manifest.json and similarity_01.json
- nutcracker/Angel/S03E01_cross_similarity_01.json
- episodes/Angel/S03E01_chirp_full_diarization.json and S03E01_chirp_full.wav
- episodes/Angel/S03E01_magpie_03d_swan.srt and earlier reconciliation artifacts

Use explicit interpreters from repository root: ./.venv/bin/python for core, ./.venv-chirp/bin/python for speaker inference. Eight physical cores provisional default; benchmark separately. Torchcodec warning observed; waveform dictionary path works. One episode at a time. Full replacement scripts, exact relative input/output paths. Do not request upload of private evidence. Inspect code or sanitized schema only. No overwrite of source or decisions.

## Resume prompt
Read this checkpoint and ROADMAP_ADDENDUM.md first. Resume BOWERBIRD source interval overlap auditing before sliding-window analysis. Inspect actual collector/comparison schemas, use controlled experiments, keep all evidence local. Verify Git status before changing code.
