
# Deferred research — 2026-11-26

These investigations are intentionally deferred until
a usable single-episode captioning workflow exists.
Deferred does not mean rejected or abandoned.

## ROOK — Caption interpretation

- Lossless structural annotation with character ownership.
- Nested, unmatched and mismatched delimiters.
- Separation of structural and semantic interpretation.
- Caption convention profiling by episode, track,
  release, caption provider and season.
- Detection of changes in caption conventions.
- Distinguishing dialogue, speaker identification,
  delivery instructions, sound descriptions and
  mixed-content annotations.
- Series-specific terminology and fictional languages.
- Caption-derived speaker evidence for CHIRP.

## GULP — Parser consolidation

- Consolidate duplicated caption interpretation logic.
- Preserve source records and original formatting.
- Recover valid records following malformed records
  when boundaries can be established reliably.
- Explicitly report discarded or unsupported content.
- Investigate deficiencies identified by Experiment 7G.0.
- Verify actual conversion behavior independently
  of parser behavior.

## Research evidence

Experiment 7G.0:
- rook_caption_audit.py
- rook_caption_audit_7g0.json
- 110 synthetic fixtures.
- 330 parser invocations.
- 20 lexical disagreements.
- 13 cue-count disagreements.
- 19 observed parser exceptions.
- Integrity verification passed.

These results characterize parser behavior, not
real-world frequency or semantic correctness.

## Development priority

Complete Experiments 7G through 7J and integrate
a usable single-episode workflow.

Resume deferred investigations when actual use
demonstrates a need, or when dedicated research
time becomes available.

Research findings should inform development without
unnecessarily blocking usable releases.


## Additional deferred investigations — 2026-11-27

### FINCH — Frequency Investigation and Noise Characterization Helper (proposed)

- Time-indexed acoustic characterization, using native audio where appropriate.
- Noise floor/SNR estimates with uncertainty; nonstationary noise and quiet speech.
- Hum, hiss, clipping, transients, pitch, music, competing speech and reverberation.
- Use LARK probabilities where useful; do not assume non-speech means pure noise.
- Separate automatic measurements from human observations and overrides.
- Evaluate optional preprocessing independently against raw audio; never assume
  filtering improves recognition. Target detailed analysis where justified.

### Speaker references and transitions

- Measure reference-assisted identification and short speaker transition accuracy.
- Evaluate diverse deliveries, noise conditions, modified voices and cross-language
  embeddings; separate enrollment from evaluation to avoid leakage.
- Investigate reuse of embeddings and targeted reassessment after knowledge changes.
- Evaluate cue splitting and speaker-marker proposals for reading comfort.

### Multilingual dialogue (explicitly deferred)

- Spoken language identification at interval level, including uncertainty.
- Multilingual recognition and English translation as optional new subtitles.
- Distinguish transcription, translation, language attribution and fictional speech.
- Preserve original text and evidence; avoid fabricated translations or changing
  deliberately untranslated narrative content without human approval.
- Evaluate cross-language speaker identification.

Current scope is Unicode preservation and conservative pass-through protection
for foreign symbologies, not language identification or translation.

### Later engineering investigations

- Cross-platform volume identity and missing-mount detection.
- Actual temporary/cache behavior of third-party tools.
- Efficient source verification and selective extraction timeline conservation.
- Persistent unattended season queue, resource limits, recovery and reassessment.

These are deferred implementation/validation topics, not claims of existing
capability. Keep current single-episode workflow development the priority.


## Further deferred investigations — 2026-11-27 (CLI checkpoint)

- Human-directed translation: select interval and spoken language (unknown allowed),
  request English translation, review/edit/accept/reject; preserve originals and
  narrative intent. Reuse interval UI and series context. No automatic whole-episode
  translation or language classification required now.
- Alternate release alignment: offsets, scaling, piecewise mappings, exclusive scenes,
  PAL speed/pitch differences and their effects on fingerprints, ASR, FINCH and speaker
  embeddings. Do not infer speedup from frame rate alone.
- Multi-reference source lineage and alignment, including partial hand-authored SRTs.
- Optional attribution/administrative text classification and recurring confirmed
  patterns; manual deletion suffices initially. Distinguish legitimate on-screen text.
- Overlapping speech, sound/music events, human-verified acoustic event recognition,
  optional source separation and engine-specific evidence adapters.
- Versioned knowledge dependencies, targeted reassessment, grouped undo, reproducible
  exports, transactional migrations, backup/restore and portability.
- Resource-aware scheduling, model reuse/prefetch, CPU/RAM/disk/network limits and
  user reserves; validate accessibility and output profiles in practical use.

Immediate priority is now the single-filename CLI integration prototype ending in
CANARY diagnostic output, before resuming GUI redesign. These investigations must
not block that prototype. No new research or production capability is claimed.
