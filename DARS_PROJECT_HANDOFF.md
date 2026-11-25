# DARS — Distributed Avian Recognition System

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
