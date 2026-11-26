
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
