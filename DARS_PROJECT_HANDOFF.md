# DARS — Distributed Avian Recognition System

**Current checkpoint: 2026-11-26 — Experiment 7F.8 complete.**

See the CURRENT DEVELOPMENT CHECKPOINT section below for authoritative
implementation status and the next experiment. Earlier resume prompts
are retained for historical reference.

Project checkpoint: November 23, 2026, end of development session.

## Purpose
Build a local, reliable subtitle generation and repair pipeline for television, including old recordings with no existing subtitles. Prioritize dialogue accuracy, completeness, synchronization, and comfortable reading. Preserve existing non-dialogue descriptions when available; do not invent them. Output SRT so Kodi controls appearance. Keep original media and manual corrections safe.

## Environment and working conventions
- Linux Mint, project root `~/drive_d/t`, Python 3.12 virtual environment `.venv`.
- FFmpeg, soundfile, sherpa-onnx, metaphone. CPU recognition with eight threads.
- Model directory `models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/`; encoder.int8.onnx, decoder.int8.onnx, joiner.int8.onnx, tokens.txt. Recognizer: OfflineRecognizer.from_transducer, provider=cpu, model_type=nemo_transducer.
- Local Ollama Mistral Small 3.1 24B Q4_K_M, 4096 context, available for later constrained contextual correction.
- Provide complete replacement scripts rather than Python snippets. Work incrementally; use controlled experiments. Never overwrite originals or review decisions; archive rather than delete. Prefer local processing.
- Friendly collaboration; project nickname DARS (Distributed Avian Recognition System). Parakeet is afraid of the HeHawk, Python chases the programmer, Mistral writes unsolicited fanfiction.

## Stable production pipeline — leave intact during experiments
- `transcribe.py`: FFmpeg first audio stream to 16 kHz mono PCM; Parakeet 300-second chunks; JSON text, tokens, timestamps, durations, source_offset_seconds. Absolute episode-relative token times. Optional --limit-seconds.
- `word_timing.py`: shared word grouping, excludes trailing punctuation tokens from spoken end time while preserving token indices and punctuation text.
- `make_srt.py`: sentence-based captions, 42 characters per line, two lines, pause threshold 0.65s, minimum cue duration 0.60s, end padding 0.12s. Current timing and sentence grouping generally good.
- `compare.py`: reference ASS vs ASR word alignment, temporal and phonetic comparison, diagnostic report.
- `review.py`: V4 timing-aware review, token ranges, context, suggestions, TODO/KEEP/ACCEPT/EDIT/DELETE/UNSURE, input SHA256. Recovers identical phrases with discrepant reference timing. Review file uses VERSION 3 header, V4 generator.
- `apply_review.py`: validates review and original hash, preserves unchanged tokens/times, applies approved edits, estimates inserted timing, backups.
- `subtitles.py`: master workflow; `python subtitles.py episodes/Angel/S03E02.mkv`; `--no-reference` for shows without subtitles; `--apply` for reviewed corrections. Automatic reference detection is planned, not implemented.
- Angel S03E01 and S03E02 tested successfully; corrected Gunn spelling without changing timestamps. Reference captions incomplete and sometimes mistimed. Preserve manual review files.
- Existing scripts archived in `archive/`, utilities in `utilities/`, media in `episodes/Angel/`, `episodes/Matthew_Starr/`, `episodes/Spider-Man/`. Stable archive `archive/subtitle_production.zip`.

## Experimental findings
Matthew Starr S01E01 (no reference subtitles) full episode took about 15 minutes; overall good quality even with noisy audio. Presentation generally comfortable. Some complete omissions in clear audio, substitutions, and missing unstressed words. Initial full run missed dialogue near 10:10 and rendered “made up” as “maybe”. Extracting 09:40–10:40 recovered both. First 900 seconds processed in separate 45s and 60s chunks (`transcribe_experiment.py --limit-seconds 900 --chunk-seconds 45` or 60) showed differing omissions and substitutions; neither duration uniformly superior. Changing duration also changes context, so controlled offset testing followed.

### Latest controlled experiment — COMPLETED
Extracted `experiments/audio_samples/MS_context_01.wav` from 09:00–11:00 of `episodes/Matthew_Starr/S01E01.mkv`, 16 kHz mono PCM. `transcribe_sliding.py` loads model once and recognizes three 60-second windows independently, with absolute episode timestamps:
- Window 1: 09:20–10:20 (sample offset 20s)
- Window 2: 09:40–10:40 (offset 40s)
- Window 3: 10:00–11:00 (offset 60s)
Command: `python transcribe_sliding.py experiments/audio_samples/MS_context_01.wav`
Outputs in same directory: `MS_context_01_window_01.json`, `_window_02.json`, `_window_03.json`, `MS_context_01_sliding_report.txt`.
Report inspected. Common region 10:00–10:20. Windows 1 and 2 both recognize “Meet Matthew. He's new too. Hi. Hi. This is Pam, Lopez, Bob, and…”; window 3 omits this entire passage in common region. Both successful windows timestamp Meet at 10:10.48, Matthew at 10:10.80, He's at 10:11.36, new at 10:11.68, too at 10:12.08. Other minor timestamp differences exist. Window 3 later produces “Cindy, I can give you a ride too if you need one” vs window 2 “even though” near its end; verify against audio before choosing. Window 3 begins mid-utterance, so its missing initial “up” is not necessarily a recognition failure. Same audio, duration, model and settings, different context; evidence supports overlapping recognition, not a claim about exact internal cause. Agreement is not proof of correctness.

## EXACT NEXT STEP
Build standalone `correlate.py` diagnostic, using the three window JSONs. Ask user to upload these JSONs and current `transcribe_sliding.py` / `word_timing.py` if needed to inspect actual schemas. Do not modify production scripts yet.
- Reconstruct words with lexical timing, normalize for alignment while preserving original punctuation and tokens.
- Use monotonic timestamp-aware sequence alignment, handle repeated words and one-to-many variants; compare only windows actually covering a passage. Distinguish boundary truncation from omissions.
- Produce readable timestamped agreement/disagreement report, including alternatives, supporting windows, window-edge distances, and missing dialogue. No automatic destructive edits.
- Verify report identifies 10:10.48 onward as supported by windows 1/2 and omitted by 3. Preserve minority-only dialogue for review, not automatic rejection. Later extend to full-episode 60s windows with 20s stride and merge individual passages, not entire windows. Runtime roughly three passes, acceptable compared with days of manual work.

## Regression sample inventory
All extracted samples intended in `experiments/audio_samples/`. Only context sample explicitly confirmed extracted; verify others exist. All from Matthew Starr S01E01. For missing samples use `ffmpeg -n -ss HH:MM:SS -i episodes/Matthew_Starr/S01E01.mkv -t 60 -map 0:a:0 -vn -ac 1 -ar 16000 -c:a pcm_s16le experiments/audio_samples/NAME.wav`.

| Sample | Extract range | Episode error time | Observed issue |
|---|---|---|---|
| MS_context_01 | 09:00–11:00 (120s) | ~09:59 and 10:10 | maybe vs made up; missing introduction dialogue |
| MS_music_01 | 20:00–21:00 | 20:27–20:31 | loud music recognition issue |
| MS_music_01 | same | 20:37–20:38 | missing line, background noise |
| MS_music_01 | same | 20:44 | I'll get him down → I'll get us down |
| MS_quiet_01 | 23:30–24:30 | 23:55–23:59 | They just transmitted → I just transmitted |
| MS_clear_01 | 25:00–26:00 | 25:34–25:40 | missing dialogue in completely clear audio |
| MS_clear_01 | same | shortly afterward | two speakers merged, incorrect punctuation |
| MS_omission_01 | 37:00–38:00 | 37:22–37:26 | You laboratory-bred soldiers laugh → You laboratory-bred soldiers are a laugh |
| MS_omission_02 | 41:30–42:30 | 41:57–41:59 | Guide → Guide me; quiet music |

## Series knowledge base (planned)
Organize around entities, with distinct canonical names/aliases, phonetic forms, observed misrecognitions, context, relationships, and confirmed examples. Candidate detection is not unconditional replacement. Preserve actual spoken alias, not normalize to a single character name. Observed errors: Shep → Chef, Chep (Chep near 38:38); D'Hai → DHA; E'Hawke → HeHawk. Provisional spellings from prior discussion: E'Hawke (Matthew), D'Hai (Walt Shepherd), Quadris, Quadrian; verify authoritative spellings before production use. Keep predicted variants separate from observed ones. Context distinguishes chef as profession vs nickname. Local LLM later proposes structured JSON edits with exact source ranges and reasons, validated by deterministic code; never let it invent dialogue or silently rewrite whole transcript.

## Later roadmap
1. Controlled recognition windows and correlation (current).
2. Audio preprocessing: filters, compression, noise reduction, vocal isolation; retain raw control and measure regressions. For separation consider preserving original channels/rate before downmixing.
3. Independent VAD to flag speech with no ASR tokens; cannot reliably detect omitted words within continuous speech. Speaker diarization to detect changes and avoid merging speakers; sherpa-onnx additional models possible.
4. Series knowledge and constrained local LLM correction; secondary ASR for ambiguous regions if useful.
5. Presentation: abbreviations (Mr., Mrs., Dr., etc.) must not trigger sentence endings; keep titles with names; avoid orphan single-word captions by rebalancing within same utterance. Preserve genuine one-word replies. Hard boundaries: speaker changes, significant pauses, confident sentence endings; soft boundaries: line/character limits and phrase balancing. Accuracy before aesthetics. Review minimum cue duration vs overlap; do not modify acoustic timing just to improve display.
6. Automatic English text reference detection via ffprobe; distinguish image subtitles, foreign/unknown streams; explicit override. Later GUI with video seek, waveform, highlighted alternatives, keyboard shortcuts and autosave.
7. Validate on other Matthew Starr episodes, especially noisy ones, held out from development. Final stress test: poor-quality 1970s live-action Spider-Man recording. Do not overfit to first episode.

## Resume prompt
“Here is the DARS project handoff. We stopped after the successful three-window controlled Parakeet experiment. Let's continue with the standalone timestamp-aware correlation diagnostic, keeping production scripts untouched. Please ask for any actual input files you need and provide complete scripts.”

## CAGE — Optional contextual inspection

Status: Experimental; excluded from default production workflow.

CAGE reads SRT subtitles and uses a local Ollama model
to generate timestamped, non-destructive advisories.

Current implementation: cage.py (formerly cage_v3.py).
Earlier implementations are archived locally in archive/cage/.

Experimental results:
- V1: 15 advisories, 22.46 seconds.
- V2: 13 advisories, 20.29 seconds.
- V3: 5 advisories, 11.15 seconds.
- No confirmed new transcription errors discovered.

Future ZOOKEEPER integration:
- Optional full subtitle inspection.
- Selected passage investigation (not yet implemented).
- Experimental model and prompt comparison.

CAGE must never modify subtitles or verified OWL knowledge
without explicit human authorization.

All processing must remain local. Loopback API access
alone does not establish complete network isolation.

## 2026-11-24 — GULP stabilized; SWAN proposed

### GULP
- V4 promoted to gulp.py.
- Independent auditor V2 promoted to gulp_audit.py.
- Content-based format identification.
- SRT and ASS/SSA conversion implemented.
- PGS, VobSub index and MicroDVD recognized but unsupported.
- Preserve dialogue, timing, line breaks, bold, italics
  and hard spaces.
- Angel regression: 415 cues passed the revised audit.
- Initial 44 discrepancies resulted from FFmpeg retaining
  literal ASS hard-space escapes.
- Do not normalize presentation during faithful ingestion.

### SWAN — Subtitle Whitespace And Normalization
Status: Designed, not implemented.

Standalone presentation normalization utility.
Original evidence must remain unchanged.

Experiment 1: Read-only presentation diagnostics.
- Detect all overlapping pairs using a sweep-line algorithm.
- Include nonadjacent and nested overlaps.
- Identify connected conflict groups.
- Measure maximum simultaneous captions.
- Measure longest overlap and total overlapping time.
- Detect insufficient gaps, indentation, line lengths,
  reading speed and out-of-order timestamps.

Initial configurable diagnostic defaults:
- Minimum gap: 24 ms.
- Preferred minimum duration: 600 ms.
- Maximum lines: 2.
- Maximum characters per line: 42.
- Reading speed warning: 20 characters per second.
- Indentation threshold: 2 leading spaces.

Experiment 2: Conservative normalization.
- Convert justified speaker indentation into dialogue markers.
- Resolve timing conflicts locally without cumulative drift.
- Preserve speech synchronization and reading time.
- Escalate irreconcilable conflicts to human review.
- Support dry-run and standalone batch processing.

### SCOOP — Subtitle Cleanup Of Obsolete Products
Status: Concept only.

Reference-aware garbage collection for temporary artifacts.
Preserve original evidence and referenced intermediates.
Require dry-run reporting and explicit deletion authorization.

### Next development steps
1. Implement and test SWAN read-only diagnostics.
2. Test nested and nonadjacent overlap detection.
3. Evaluate real subtitle files before normalization.
4. Implement conservative SWAN normalization.
5. Implement FFprobe-based embedded subtitle discovery.
6. Develop episode scheduling and ZOOKEEPER integration.

All media, transcripts, voice embeddings and dialogue-bearing
diagnostics must remain local.

---

# CURRENT DEVELOPMENT CHECKPOINT — 2026-11-26

This checkpoint supersedes all earlier resume prompts, implementation
status descriptions and immediate next-step instructions in this file.
Earlier sections are retained as historical development records.

## Project identity and working conventions

- Repository: kdx7214/HeHawk.
- Project name: HeHawk.
- Architecture nickname: DARS (Distributed Avian Recognition System).
- Project directory: ~/drive_d/t.
- Operating system: Linux Mint Cinnamon.
- CPU: AMD Ryzen 7 9800X3D, eight physical cores, sixteen threads.
- GPU: AMD Radeon RX 9070 XT, 16 GB VRAM.
- CPU-first development; GPU acceleration is optional future work.
- Core Python environment: .venv.
- Acoustic and speaker-analysis environment: .venv-chirp.
- Always specify the Python interpreter explicitly in commands.
- Always specify exact input and output filenames and relative paths.
- Human-facing timestamps use HH:MM:SS.mmm.
- Include decimal seconds alongside timestamps when useful for commands.
- Provide complete replacement scripts rather than partial Python edits.
- Process one episode at a time.
- Accuracy and maintainability take precedence over execution speed.
- Preserve original media, recognition evidence and human decisions.
- Never silently overwrite or delete existing artifacts.
- Keep media, transcripts, voice embeddings and dialogue-bearing
  diagnostics local. Do not commit them to GitHub.

## Architecture and component inventory

| Component | Responsibility | Current status |
|---|---|---|
| GULP | Faithful subtitle ingestion | Implemented and audited |
| SWAN | Subtitle presentation and timing normalization | Implemented and tested |
| PARAKEET | Primary speech recognition | Operational |
| OWL | Series vocabulary and knowledge | Initial implementation |
| CAGE | Optional local contextual inspection | Experimental |
| CHIRP | Speaker diarization | Experimental |
| BOWERBIRD | Local acoustic and speaker evidence | Experimental |
| LARK | Independent speech probability estimation | Implemented experimentally |
| HUNT | Detection and investigation of recognition omissions | Experimental |
| TERN | Temporal extraction and recognition navigation | Experimental |
| MAGPIE | Multiple Audio-source Gathering, Provenance, Integration and Evaluation | Experimental through 7F |
| ROOK | Recognition of Orthographic Oddities and Knowledge | Proposed |
| NUTCRACKER | Persistent local reviewed evidence corpus | Planned |
| ZOOKEEPER | Dependency-aware orchestration | Planned |
| SCOOP | Reference-aware artifact cleanup | Planned |
| STORK | Final subtitle publishing and preview muxing | Planned |
| WOODPECKER | Installation and environment diagnostics | Proposed |

ALBATROSS is an unofficial mascot representing technical debt,
legacy dependencies and accidentally indispensable obsolete behavior.

## SWAN — Completed initial implementation

SWAN is no longer merely a design proposal.

Implemented standalone diagnostics and conservative timing normalization,
with independent auditing.

Initial presentation defaults:

- Preferred minimum inter-cue gap: 24 ms.
- Preferred minimum cue duration: 600 ms.
- Reading speed warning: 20 characters per second.
- Maximum preferred lines: two.
- Maximum preferred characters per line: 42.

Initial normalization preserves cue starts and dialogue content.
It adjusts cue ends locally without accumulating timing drift.

Angel regression:

- Original cues: 415.
- Original overlapping pairs: 24.
- Remaining overlaps after initial normalization: zero.
- Insufficient gaps: 254 reduced to 31.
- Short cues: 27 reduced to zero.
- Reading speed warnings: 70 reduced to 38.
- Modified cues: 288.
- Independent integrity audit passed.
- Human playback assessment found synchronization satisfactory.

A later reconciliation preview contained 518 cues and one protected
120 ms overlap requiring investigation.

Do not force resolution of complex overlaps at the expense of dialogue
or synchronization. Presentation normalization follows reconciliation.

Whitespace normalization and speaker-marker interpretation remain
future work. Preserve meaningful indentation and raw line boundaries.

## CHIRP and BOWERBIRD

Full-episode diarization and local overlapping-window acoustic
investigations have been performed.

Findings:

- Global diarization can produce excessive speaker transitions.
- Short windows can yield unstable speaker embeddings.
- Longer windows can improve speaker evidence but can also combine
  multiple speakers.
- Speaker count and speaking-turn count are different quantities.
- A-B-A patterns and short interjections must remain representable.
- Acoustic transitions do not necessarily indicate speaker changes.
- Unknown speakers must remain unknown rather than being forced into
  enrolled identities.

Future character voice enrollment should use multiple diverse,
human-verified samples. Keep embeddings and source audio local.

## LARK and HUNT

LARK uses Silero VAD through ONNX to produce independent speech
probabilities at 512-sample intervals for 16 kHz audio.

LARK evidence is probabilistic, not a definitive dialogue transcript.

HUNT compares speech probabilities with recognition word coverage.

Important distinctions:

- Speech probability is not proof of intelligible dialogue.
- Recognition coverage is not proof of correct transcription.
- Missing dialogue can occur inside continuous recognized speech.
- Agreement among recognizers cannot reveal every shared omission.
- Very short gaps can contain meaningful dialogue.
- Do not apply a blanket minimum-duration filter that discards evidence.

HUNT should retain evidence independently of MAGPIE lexical agreement.

## Experiment 6 — TERN segmented recognition

### Segmentation

TERN divides an episode into contiguous recognition segments using
natural pauses where possible.

Initial settings:

- Target segment duration: 15 seconds.
- Preferred minimum: eight seconds.
- Preferred maximum: 20 seconds.
- Pause probability threshold: 0.3.
- Minimum pause duration: 256 ms.

Initial full-episode regression:

- Segments: 170.
- Natural internal boundaries: 164.
- Fallback internal boundaries: five.
- Mean segment duration: approximately 14.748 seconds.
- Shortest segment: approximately 4.763 seconds.
- Longest segment: approximately 19.760 seconds.

### Recognition

Each segment is recognized using a fresh recognition stream.
The model is loaded once.

- CPU provider.
- Eight recognition threads.
- Existing Parakeet TDT 0.6B v2 INT8 model.
- Preserve original segment-relative token timestamps.
- Preserve absolute episode geometry separately.
- Record source and model hashes.
- Retain timing warnings rather than silently clipping raw evidence.

Initial segmented recognition completed in 36.740 seconds.
It recovered some previously omitted dialogue but introduced other
omissions. Segmentation alone is not a universal improvement.

### Padding sensitivity

Controlled experiments demonstrated that recognition can change when
short amounts of audio or synthetic padding are appended.

In one regression case:

- An unmodified segment omitted dialogue near its end.
- Appending 240 ms of real audio recovered the dialogue.
- Appending 240 ms of silence did not recover it.
- Sufficiently strong synthetic noise padding recovered it.

This demonstrates sensitivity to input signal and context.
The exact internal model mechanism remains unverified.

Full-episode padding passes used:

- Baseline: no padding.
- P01: 240 ms of silence.
- P02: 240 ms of synthetic noise, target RMS 0.001.
- P03: 240 ms of synthetic noise, target RMS 0.01.

Synthetic noise is deterministic, with segment-specific seeds.

Different passes recover and omit different dialogue.
Majority voting can discard genuine minority-only speech.
Taking the union without verification can introduce hallucinations.

Human review confirmed that some segments with empty recognition
alternatives contain genuine speech.

A limited bandpass-filter experiment did not recover the target
dialogue. Filtering remains an independent future investigation.

## Experiment 7 — MAGPIE evidence accumulation

### 7A — Incremental corroboration

Compared previously recovered subtitle candidates with fresh
segmented recognition.

- Recovered candidates: 95.
- Corroborated: 84.
- Partial: seven.
- Absent: four.
- Ambiguous exact matches: two.
- Unique exact corroboration candidates: 82.

Corroboration is supporting evidence, not automatic acceptance.

### 7B — Novelty classification

Compared fresh recognition with original and recovered captions.

- Recognition words: 3,769.
- Original-caption-supported words: 2,606.
- Recovered-caption-supported words: 366.
- Competing words: 241.
- Novel words: 556.
- Unresolved words: 797.
- Grouped unresolved candidates: 240.

Original caption support takes precedence for classification.
Original captions are themselves imperfect.

### 7C — Historical recognition evidence

Compared unresolved current recognition with an earlier recognition run.

Of the 797 unresolved words:

- Previously observed: 611.
- Newly observed hypotheses: 186.

Historical agreement does not establish accuracy.
Previously observed evidence is not equivalent to human verification.

### 7D — Multi-pass accumulation

Accumulated four recognition passes over the same 170 segments.

- Observations: 680.
- Unanimous lexical segments: 70.
- Competing lexical segments: 77.
- Lexical segments with empty or nonlexical alternatives: three.
- All-empty segments: 20.
- Disputed segments: 80.
- Distinct lexical segment hypotheses: 267.

Preserve all alternatives, including empty observations.
Same-model passes are correlated evidence, not independent votes.
No automatic acceptance.

### 7E — Initial disagreement localization

Use monotonic, timestamp-aware lexical alignment to identify
common anchors across all recognition passes.

Initial parameters:

- Anchor tolerance: 250 ms.
- Review context: one second on either side.
- Review-window merge gap: 500 ms.

Initial results:

- Disputed segments: 80.
- Common anchors: 1,902.
- Disagreement regions: 116.
- Review windows: 86.
- Full-segment fallbacks: one.
- Raw disagreement coverage: 105.872 seconds.
- Contextual review coverage: 305.808 seconds.
- Potential listening-time reduction: 74.71 percent.

One segment exposed a mismatch between decoded text and token-derived
lexical boundaries, requiring Experiment 7F.

## Experiment 7F — Decoder-aware reconstruction

### Problem

Whitespace and punctuation in raw token streams do not always
correspond directly to lexical boundaries in decoded text.

The legacy word grouping method can also associate lexical tokens
with more than one reconstructed word.

These defects can affect word timing and disagreement localization.

### Normalization investigation

Alternative punctuation-normalization strategies were evaluated.

Aggressive punctuation removal can collapse meaningful distinctions:

- Contractions versus ordinary words.
- Possessives versus plurals.
- Hyphenated versus unhyphenated forms.
- Fictional names containing apostrophes.
- Decimal numbers and comma-separated numbers.
- Speaker markers and interrupted speech.

Keep reconstruction separate from lexical equivalence decisions.

ROOK is proposed as a dedicated orthographic evidence component.

### Decoder-aware reconstruction

Use decoded text to establish candidate lexical boundaries.

Map the case-folded alphanumeric character stream to exact raw token
character positions. Preserve original token and character ownership.

For each reconstructed word:

- Retain original decoded spelling.
- Retain normalized lexical form.
- Record contributing token indices.
- Record exact contributing character positions.
- Derive timing from contributing lexical tokens.
- Preserve shared timing when one token spans multiple words.

Do not invent subtoken timing.

Boundary classifications:

- lexical_agreement
- punctuation_boundary_agreement
- boundary_disagreement
- character_mismatch

Character-stream agreement is not sufficient to establish semantic
or lexical equivalence.

The experimental adapter accepts lexical agreement and punctuation
boundary agreement only after ownership verification and comparison
with the accumulated decoded lexical sequence.

Boundary disagreement and character mismatch require investigation.

Punctuation-boundary agreement remains experimental: distinctions
such as decimal punctuation may require stronger semantic checks.

### Ownership and timing audits

Across 680 observations:

- Reconstructed words: 15,085.
- Verified folded lexical character positions: 58,376.
- Lexical tokens: 24,857.
- Legacy duplicate lexical token associations: 84.
- Remaining shared lexical tokens in this episode: zero.
- Lost lexical character positions: zero.
- Unowned lexical tokens: zero.

Three previously problematic observations were reconstructed.

Timing comparisons identified 36 shortened comparable word spans.
Five unique newly exposed dash-associated timing gaps totaled
640 ms across the union of passes.

A separate 160 ms interval gained recognition coverage.
Human listening confirmed dialogue in that interval, but did not
independently establish exact acoustic word boundaries.

The dash-associated gaps have not been acoustically verified.

### Regression suite

test_magpie_decoder_reconstruct.py contains 51 synthetic tests.

All 51 passed.

Coverage includes contractions, fictional names, repeated words,
speaker markers, interruptions, Unicode case folding, whitespace,
punctuation, shared tokens, invalid timings and negative controls
for corrupted character ownership.

The full episode also passed exact character ownership verification.

These tests establish structural correctness against available
evidence, not universal transcription accuracy.

### 7F.7 — Decoder-aware localization

The experimental adapter replaces the reconstruction function
for one process without modifying the production localizer.

Original alignment parameters were retained.

Results:

| Measurement | 7E | 7F.7 |
|---|---:|---:|
| Disputed segments | 80 | 80 |
| Fallback segments | 1 | 0 |
| Common anchors | 1902 | 1964 |
| Disagreement regions | 116 | 117 |
| Review windows | 86 | 87 |
| Empty alternatives | 50 | 51 |
| Raw disagreement seconds | 105.872 | 89.200 |
| Contextual review seconds | 305.808 | 291.360 |
| Potential listening reduction | 74.71% | 75.90% |

All localization conservation checks passed.

### 7F.8 — Independent differential audit

Compared both localization reports against original 7D evidence.

- Verified segment comparisons: 80.
- Unchanged segments: 78.
- Changed segments: two.
- Added anchors: 62.
- Removed anchors: zero.
- Changed existing anchor timings: two.
- Detected lexical conservation failures: zero.
- Additional raw disagreement coverage: zero.
- Additional contextual review coverage: zero.
- Removed raw disagreement coverage: 16.672 seconds.
- Removed contextual review coverage: 14.448 seconds.

One changed segment contained corrected anchor timings without
changing anchor membership, lexical alternatives or review coverage.

The other changed segment eliminated the original fallback and
localized its disagreements into two short intervals.

Original inputs remained unchanged.

The independent auditor verifies lexical alternative signatures
with multiplicity. It does not independently verify region ordering
or full lexical conservation of the original fallback.

## Current performance interpretation

Test episode duration: 2507.243 seconds (00:41:47.243).

Complete disputed segment duration:
1209.056 seconds (00:20:09.056).

Current contextual review coverage:
291.360 seconds (00:04:51.360).

Potential listening duration eliminated:
917.696 seconds (00:15:17.696).

Potential listening-time reduction: 75.90 percent.

This is an interval-coverage measurement, not a measured reduction
in total human review time.

It excludes shared recognition omissions, independent caption
disagreements and other unresolved evidence categories.

No claim of 75.90 percent transcription accuracy is intended.

## New experimental scripts

TERN:
- tern.py
- tern_recognize.py
- tern_padding.py
- tern_compare.py

HUNT:
- hunt_differential.py

MAGPIE:
- magpie_incremental.py
- magpie_novelty.py
- magpie_history.py
- magpie_accumulate.py
- magpie_localize.py
- magpie_normalization.py
- magpie_decoder_reconstruct.py
- magpie_timing_ownership_audit.py
- magpie_ownership_conservation.py
- magpie_localize_decoder.py
- magpie_localization_diff.py
- test_magpie_decoder_reconstruct.py

These scripts remain experimental until deliberately integrated
into the production workflow.

## Integration cautions

- The decoder-aware localization adapter currently imports
  verification helpers from the regression test module.
- Move reusable verification logic into an appropriate shared
  implementation module before production integration.
- Record reconstruction method and verification settings explicitly
  in localization artifact provenance.
- Preserve raw token evidence and original punctuation.
- Do not equate punctuation-independent character agreement with
  semantic equivalence.
- Investigate concatenated token streams at segment boundaries,
  particularly when the first token lacks a leading space.
- Verify schemas and actual source files before writing consumers.
- Do not silently promote experimental behavior into production.
- Validate reconstruction and localization on additional episodes.

## Local regression artifact inventory

All episode-specific artifacts remain local under episodes/Angel/.

| Artifact | Purpose |
|---|---|
| S03E01_chirp_full.wav | Full episode PCM |
| S03E01_vad_01.json | LARK speech probabilities |
| S03E01_tern_01.json | TERN segmentation |
| S03E01_tern_6c_evidence.json | Baseline segmented recognition |
| S03E01_tern_6j_a.json | Silence-padded recognition |
| S03E01_tern_6j_b.json | Low-noise-padded recognition |
| S03E01_tern_6j_c.json | Higher-noise-padded recognition |
| S03E01_tern_6k.json | Recognition pass comparison |
| S03E01_hunt_05a.json | Historical omission inventory |
| S03E01_hunt_6c.json | Segmented omission inventory |
| S03E01_hunt_6d.json | Differential omission inventory |
| S03E01_gulp_v4.srt | Faithfully ingested original captions |
| S03E01_magpie_01_missing_preview.srt | Recovered caption candidates |
| S03E01.json | Historical recognition |
| S03E01_magpie_7a.json | Incremental corroboration |
| S03E01_magpie_7b.json | Novelty classification |
| S03E01_magpie_7c.json | Historical evidence |
| S03E01_magpie_7d.json | Multi-pass accumulation |
| S03E01_magpie_7e.json | Original localization |
| S03E01_magpie_7f2.json | Normalization comparison |
| S03E01_magpie_7f3.json | Decoder reconstruction |
| S03E01_magpie_7f4.json | Timing ownership audit |
| S03E01_magpie_7f5.json | Ownership conservation |
| S03E01_magpie_7f6.json | Adversarial reconstruction tests |
| S03E01_magpie_7f7.json | Decoder-aware localization |
| S03E01_magpie_7f8.json | Localization differential audit |

These artifacts are not repository deliverables.
Do not upload their contents to GitHub.

## EXACT NEXT STEP — Experiment 7G

Develop a standalone, read-only evidence overlay diagnostic.

Primary inputs:

- episodes/Angel/S03E01_magpie_7b.json
- episodes/Angel/S03E01_magpie_7c.json
- episodes/Angel/S03E01_magpie_7d.json
- episodes/Angel/S03E01_magpie_7f7.json

Inspect actual schemas and source implementations before coding.

Goals:

1. Annotate all 117 localized disagreement regions.
2. Associate original-caption and recovered-caption evidence.
3. Associate historical recognition evidence.
4. Preserve every lexical alternative and supporting pass.
5. Distinguish complete, partial and absent support.
6. Distinguish historical observation from human verification.
7. Identify genuinely novel hypotheses.
8. Preserve source identity, hashes and evidence provenance.
9. Do not eliminate review windows during the initial overlay.
10. Do not automatically accept or reject any dialogue.

Suggested output:
episodes/Angel/S03E01_magpie_7g.json

No recognition or VAD reruns should be necessary for this experiment.

## Subsequent experiments

7H — Independent omission evidence:
Overlay HUNT and LARK evidence, including possible omissions shared
by all recognition passes.

7I — Persistent review queue:
Retain evidence, alternatives, decisions and dependencies.
Use stable evidence-based identities rather than transient window IDs.
Do not repeat human review without a meaningful reason.

7J — Human review evaluation:
Measure actual listening time, replay count, decision time,
correction quality and total human effort.

## Git checkpoint notes

The previous repository checkpoint was commit 3cec31b.

The 17 new experimental scripts are intended for the next commit,
together with this documentation update and ROADMAP.md.

Six older experimental GULP files remain untracked intentionally:

- gulp_audit_v2.py
- gulp_v3.py
- gulp_v4.py
- test_gulp_audit_v2.py
- test_gulp_v3.py
- test_gulp_v4.py

Investigate their regression errors separately.
Do not delete them or include them blindly in this checkpoint.

The combined regression suite must be rerun before committing.

## Current resume prompt

"We are continuing HeHawk after completing Experiment 7F.8.
Decoder-aware reconstruction and differential localization have
passed their experimental checks. Begin Experiment 7G, the
historical and caption evidence overlay. Preserve all alternatives,
keep production scripts unchanged, and inspect actual input schemas
before writing code. Provide complete scripts, explicit interpreter
paths, exact filenames and human-readable timestamps."

## Architectural addendum — Graceful uncertainty handling

Added 2026-11-26, following Experiment 7F.8 and before 7G.

### Motivating edge case

Human-authored captions may use identical presentation conventions
for fundamentally different semantic content.

Synthetic examples:

- [ Door opening ]
- [ On PA: Please come here ]
- [ Whispering ] Get down.
- [ John: Stop that! ]

Bracketed content may contain sound descriptions, speaker
attribution, source attribution, actual dialogue or combinations
of these categories.

Neither unconditional inclusion nor unconditional exclusion
of bracketed text is safe.

Recognition may corroborate dialogue within bracketed spans,
but absence of recognition does not establish that the text
is non-dialogue.

This example represents a broader class of unpredictable
human-authored conventions.

### General uncertainty-handling contract

HeHawk must support uncertainty as an ordinary processing outcome,
not as an exceptional software failure.

Proposed processing outcomes:

| Status | Meaning |
|---|---|
| RESOLVED | A validated rule establishes an acceptable interpretation |
| AMBIGUOUS | Multiple plausible interpretations exist |
| INSUFFICIENT_EVIDENCE | Available evidence cannot establish an interpretation |
| UNSUPPORTED | An encountered convention or structure is not understood |
| CONFLICTING_EVIDENCE | Available evidence supports incompatible interpretations |
| ERROR | An actual software or processing failure occurred |

These names are provisional until a shared result schema is designed.

RESOLVED does not necessarily mean human-verified.
Resolution status and verification provenance must remain separate.

### Required behavior

When reliable interpretation is not possible:

1. Preserve the complete original evidence.
2. Preserve available alternative interpretations.
3. Record the reason automatic resolution was unsuccessful.
4. Identify the smallest reliably isolated affected region.
5. Create a persistent human review requirement.
6. Continue processing unrelated regions where dependencies permit.
7. Prevent uncertain interpretations from silently becoming facts.
8. Do not automatically delete, replace or duplicate dialogue.
9. Do not fabricate a resolution to satisfy downstream requirements.
10. Preserve the ability to resume processing after human intervention.

Actual software errors must remain distinguishable from legitimate
uncertainty. Do not use broad exception handling to disguise
implementation defects as ambiguous input.

If an error compromises source integrity or artifact validity,
stop the affected processing stage and preserve diagnostic evidence.

### Structural versus semantic interpretation

Presentation markup does not establish semantic meaning.

Preserve original caption text, delimiters, line boundaries,
indentation and formatting independently of inferred meaning.

Potential semantic span categories include:

- Dialogue.
- Sound description.
- Speaker attribution.
- Source attribution.
- Delivery description.
- Language attribution.
- Presentation markup.
- Unknown or ambiguous content.

Semantic classifications may be provisional and overlapping.
Do not require every caption to have a single semantic category.

### Human review requirements

A review item should eventually provide:

- Original evidence.
- Relevant timestamps and contextual playback.
- Available recognition alternatives.
- Relevant acoustic and historical evidence.
- Proposed interpretations.
- Reason for escalation.
- Dependencies and affected downstream products.

Supported human outcomes should include:

- Accept.
- Reject.
- Edit.
- Defer.
- Mark as unresolvable with current evidence.

An unresolvable decision is a valid outcome.

NUTCRACKER should preserve such decisions and their provenance.
ZOOKEEPER should not repeatedly reopen them without meaningful
new evidence or an explicit human request.

### Immediate implications for Experiment 7G

- Preserve all original caption content.
- Permit lexical evidence matching within bracketed spans.
- Do not infer semantic roles solely from punctuation or delimiters.
- Distinguish lexical corroboration from semantic interpretation.
- Do not treat unmatched annotation words as confirmed omissions.
- Preserve ambiguous evidence without automatically resolving it.
- Audit existing comparison routines for unsafe assumptions.
- Add synthetic regression cases for unusual caption conventions.

Experiment 7G remains a read-only evidence overlay.
No automatic dialogue acceptance, rejection or review elimination.

### Architectural objective

Do not attempt to anticipate every possible malformed, unusual
or undocumented human-authored convention.

Instead, establish a general, non-destructive path from uncertain
automatic interpretation to persistent human review.

Graceful escalation is successful processing.

## Development checkpoint — 2026-11-26

### MAGPIE 7G — Evidence overlay

Completed and verified against Angel S03E01.

- 117 disagreement regions.
- 258 competing hypotheses, including 51 empty alternatives.
- 77 regions have at least one exact lexical corroboration.
- No automatic acceptance or elimination.
- Original captions, recovered captions, and historical
  recognition remain separate evidence sources.
- Lexical corroboration is not proof of acoustic correctness.

### HUNT 7H — Shared recognition gaps

Initial implementation identified 1661 candidate gaps.

The sample-grid precision audit established that 642
candidates represented zero audio samples and resulted
from floating-point boundary discrepancies.

Experiments 7H.2 through 7H.5 established:

- Primary coverage uses integer sample arithmetic.
- Sample rate: 16000 Hz.
- Provisional recognition boundary guard: 0.050 samples.
- Maximum observed boundary error: 0.020809174 samples.
- Corrected candidate inventory: 1019.
- All 1019 nonzero sample spans conserved exactly.
- Total uncovered samples: 2058240.
- Total uncovered duration: 128.640 seconds.
- Zero nonzero sample spans added or removed.
- Zero zero-sample candidates remain.

Supplementary evidence retains its original timestamps
and raw coverage measurements.

Positive supplementary coverage classification requires
at least one sample duration of overlap.

MAGPIE associations require a positive intersection
of integer sample spans.

The evidence association audit found:

- 29 newly reported MAGPIE associations represented
  zero-sample overlaps.
- 72 supplementary classifications changed when
  requiring meaningful overlap.
- One-sample and one-millisecond sensitivity tests
  produced identical classification counts.

Final HUNT classifications:

- Acoustic only: 181.
- Caption only: 371.
- Historical and caption: 373.
- Historical only: 94.

These are evidence classifications, not confirmed
missing dialogue.

The sample-grid adapter and association transformation
are experimental implementations. Production integration
should explicitly separate primary sample arithmetic
from supplementary timestamp domains.

### NUTCRACKER 7I.1 — Review scheduling

Three progressive review tiers share one evidence
inventory and one persistent decision state.

Final corrected scheduling results:

| Tier | Windows | Listening seconds | Gap coverage |
| --- | ---: | ---: | ---: |
| Focused | 96 | 334.304 | 33.10% |
| Balanced | 183 | 680.704 | 70.19% |
| Comprehensive | 228 | 1306.640 | 100.00% |

All 117 MAGPIE regions are included in every tier.

Both known recognition problem areas remain contained
in every tier.

Balanced scheduling now uses meaningful historical
coverage when available. All seven targeted predicate
tests passed.

Compared with the original schedule, comprehensive
listening duration decreased by 289.392 seconds.

These durations measure scheduled audio coverage,
not actual human review time.

### NUTCRACKER 7I.2 — Persistent review decisions

SQLite implementation completed.

- Shared evidence identities across review tiers.
- Transactional decision updates.
- Persistent decision history.
- Idempotent repeated decisions.
- Explicit correction, rejection, acceptance,
  deferral, and unresolvable states.
- Database integrity and foreign-key checks.
- No automatic decisions from listening or coverage.

Synthetic persistence and revision tests passed.

Current corrected database contains:

- 117 MAGPIE evidence items.
- 1019 HUNT evidence items.
- 1136 pending decisions.
- Zero genuine human decisions.
- Zero decision history events.
- Database integrity: PASS.

Local working database:

episodes/Angel/S03E01_nutcracker_v2.sqlite3

Local supporting reports:

episodes/Angel/S03E01_magpie_7g.json
episodes/Angel/S03E01_hunt_7h5.json
episodes/Angel/S03E01_nutcracker_7i1c.json

These reports and databases must remain local.

### Next development milestone

7I.3: Implement nutcracker_review.py.

Start with a dependency-light terminal interface
using the existing NUTCRACKER decision engine.

FFplay is available at /usr/bin/ffplay.

Required capabilities:

- Chronological review navigation.
- Local audio playback and replay.
- Adjustable listening context.
- Display of competing hypotheses and caption evidence.
- Explicit individual evidence decisions.
- Immediate transactional persistence.
- Resume after interruption.
- Shared decisions across review tiers.
- Measurement of playback and active review time.

7J: Measure actual human review workload and
evaluate practical usefulness.

Prioritize usable review functionality over additional
research tangents. Preserve deferred research in
RESEARCH_BACKLOG.md.

## Development checkpoint — 2026-11-26 (GUI)

### 7I.3a — NUTCRACKER player

Implemented nutcracker_player.py using persistent MPV
playback controlled through local JSON IPC.

All initial player integration tests passed.

### 7I.3b — Graphical reviewer

Implemented nutcracker_review.py using Tkinter.

Architectural decisions:
- Independent review and video windows.
- Support single-monitor and dual-monitor workflows.
- Remember window placement and playback preferences.
- Reuse the existing transactional decision engine.
- Subtitle preview selection does not accept evidence.
- No modifications to original episode media.

Verified development environment:
- X11 under Linux Mint Cinnamon.
- Tkinter 8.6.
- MPV, wmctrl and xwininfo available.
- Primary display: 3840x2160 at 0,0.
- Secondary display: 1920x1080 at 3840,0.

Initial GUI testing identified cramped buttons and
navigation controls disappearing outside the window.

Revised GUI provided with padded buttons, separate
navigation controls and keyboard navigation.

Revised layout still requires practical verification.

### Resume here

Continue GUI usability testing before testing decisions.

Test database:
episodes/Angel/S03E01_nutcracker_gui_test.sqlite3

Production review database:
episodes/Angel/S03E01_nutcracker_v2.sqlite3

Local preferences:
nutcracker_settings.json

Do not commit databases, preferences, media, captions
or episode-specific evidence reports.

Remaining work:
- Refine evidence presentation and GUI usability.
- Verify navigation and window placement persistence.
- Verify cross-tier decision persistence.
- Verify episode-to-video provenance.
- Implement historical recognition previews.
- Implement deferred-item navigation.
- Measure actual human review workload.

No genuine human review decisions have been confirmed.


## Development checkpoint — 2026-11-27 (operational design)

This checkpoint supersedes earlier resume instructions, not experimental results.
GUI implementation is paused by agreement pending operational specifications.
No new production implementation or genuine review decisions are claimed.

### GUI findings and next revision (7I.4)

Initial review GUI was difficult to understand without inspecting raw JSON.
Present one understandable question at a time, why it was flagged, surrounding
context, all actual text alternatives and highlighted differences. Previewing
an alternative must not accept it. Distinguish MAGPIE competing wording from
HUNT speech missing from recognition (not necessarily from original captions).
Support explicit uncertainty, deferral, rejection, acceptance and manual edits.
Audit existing decision semantics before changing schemas; avoid lossy mappings.
Manual correction is first-class: editable multiline text from an alternative
or blank, precise correction scope, punctuation/case/speaker lines preserved,
MPV preview before confirmation, unsaved-change protection and revision history.
Separate dialogue and timing edits; never invent partially understood words.

Keep evidence interval, scheduled review window and playback context separate.
Proposed playback defaults: 10 seconds before and after, independently adjustable.
Use unobtrusive MPV overlay with persistent evidence marker, playhead and timecode;
configurable placement/size/opacity and disable option. No flashing or forced pause.
Independent video/review windows; monitor-aware placement restoration.
Proposed modules: hehawk_gui.py, hehawk_project.py, nutcracker_presentation.py,
nutcracker_player.py, nutcracker_review.py and existing nutcracker.py engine.
Names and schemas remain provisional. Test presentation independently, then playback,
application shell, GUI, persistence and practical usability. Use the isolated GUI
test database; preserve the real review database. Test with minimal instruction.

### Resume here

First define operational contracts for media ingestion/project initialization,
resource acquisition, persistent identity, storage validation and processing stages.
Then resume the human-oriented review redesign. Keep advanced controls hidden
until requested. Do not start deferred research or batch implementation yet.
See ROADMAP.md, operational architecture addendum, for today's requirements.
Existing regression files and databases listed in the preceding checkpoint remain
local. Do not commit media, captions, embeddings, dialogue-bearing evidence,
local configuration or review databases. Use exact relative filenames, explicit
interpreter paths and human-readable timestamps with decimal seconds when needed.


## Development checkpoint — 2026-11-27 (CLI integration)

This checkpoint supersedes the preceding implementation order, not its requirements
or experimental results. GUI development remains paused. No new code or tests
are claimed complete.

Next: implement hehawk.py incrementally, beginning with read-only FFprobe media
inventory from a single video filename. Test against the actual mounted CIFS
library, with explicit local workspace configuration before generating artifacts.
Then establish project identity, optional series NFO import, track selection,
resource extraction, GULP integration, evidence preparation, reconciliation,
review scheduling and CANARY diagnostic output. Use a fresh isolated workspace
so existing research artifacts cannot conceal missing dependencies. Preserve all
existing research files and review databases.

The media library is a source, never a workspace. Never open source media or NFO
for writing, rename, delete or create intermediates alongside them. STORK creates
separate output; any later publication is explicit. Prefer OS-enforced read-only
access where practical. No silent storage fallback. For a Season 3 episode,
tvshow.nfo is one directory above the containing season directory (two parent
steps from the video file itself).

The CLI is a single-episode prototype of the eventual unattended batch backend,
not a separate implementation. CANARY (Caption Annotation and Narrative Anomaly
Review utilitY) produces a separate annotated SRT and local audit, not corrections.
Warn, don't correct; inform, don't obstruct. See ROADMAP for details.

Resume with media inspection only: no recognition models, GUI or source writes.
Use explicit interpreter and exact filenames in commands. Keep media, dialogue,
local configuration, embeddings, reports and databases out of Git.
