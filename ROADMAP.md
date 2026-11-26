# HeHawk — Development Roadmap

Living planning document. This is a statement of intended direction, not a claim that all capabilities are implemented. Priorities may change as experiments provide evidence.

## 1. Guiding principles

- Accuracy first, followed by reliability, reproducibility, maintainability and performance.
- Process one episode at a time; support resumable work rather than requiring batch processing.
- Keep source media and original subtitle evidence immutable. Never overwrite originals.
- Separate observations, interpretations and human decisions. Preserve uncertainty; never treat model agreement as proof.
- Keep audio, transcripts, voice embeddings and dialogue-bearing diagnostics local.
- Record source hashes, model and tool versions, parameters, actual processing backend and artifact dependencies.
- Preserve human review decisions and regenerate derived artifacts when upstream evidence changes.
- Support episodes with incomplete captions and episodes with no captions at all.

## 2. Near-term development

### CHIRP — Speaker transition evidence

- Complete full-episode automatic diarization baseline on Angel S03E01.
- Compare global diarization against overlapping local windows and independent acoustic transition evidence.
- Investigate automatic speaker-count estimation and optional alternative count hypotheses. Forced counts are diagnostic evidence, not ground truth.
- Compare transition locations rather than assuming speaker labels persist across windows.
- Focus on transitions within subtitle cues, including original captions and generated captions.
- Distinguish speaker count from speaking-turn count; support A-B-A patterns, interjections and overlapping speech.
- Preserve short speech evidence and incomplete coverage; avoid blanket duration filters.
- Flag potential multi-speaker cues for human review rather than automatically splitting them.
- Retain separate acoustic, linguistic and speaker evidence rather than hiding disagreement in a single confidence score.

### MAGPIE — Dialogue reconciliation

- Continue recovery of missing dialogue and reconciliation of competing reference and recognition evidence.
- Integrate CHIRP evidence into boundary reconstruction and review.
- Preserve original wording where supported; consider phonetic similarity, contextual anchors and series vocabulary without forcing matches.
- Keep review decisions persistent and tied to the exact evidence and proposal version.
- Validate insertions and replacements before final presentation normalization.

### SWAN — Subtitle presentation

- Retain standalone diagnostics and conservative timing normalization.
- Apply final timing normalization after dialogue reconciliation, not before.
- Preserve speech timing separately from display timing; avoid cumulative timing drift.
- Prefer a 24 ms gap, readable durations and sensible line lengths without sacrificing meaningful dialogue or speaker separation.
- Develop whitespace and indentation normalization after reconciliation is stable.
- Preserve meaningful line breaks and intentional multi-speaker formatting.
- Retain independent integrity audits and escalate irreconcilable overlaps for review.

### GULP — Subtitle ingestion

- Maintain faithful extraction and independent auditing.
- Add embedded subtitle discovery and evaluate additional subtitle formats, including bitmap formats, as needed.
- Keep presentation normalization separate from ingestion.

## 3. ZOOKEEPER — Pipeline orchestration

- Coordinate the flock through an explicit dependency graph and artifact manifest.
- Resume interrupted work and reuse valid cached artifacts.
- Invalidate downstream products when inputs, settings or review decisions change.
- Schedule components with appropriate resource limits; avoid unnecessary simultaneous inference workloads.
- Support both existing-caption reconciliation and transcription-only workflows.
- Provide understandable progress, diagnostics and recovery from failed stages.

### SCOOP — Artifact cleanup

- Reference-aware cleanup of obsolete derived products.
- Dry-run preview and explicit authorization before deletion.
- Never remove immutable sources, persistent review decisions or curated training/regression evidence.

## 4. NUTCRACKER — Local reviewed evidence corpus

- Preserve selected audio snippets with surrounding context, original captions, recognition output, timing, speaker evidence, human decisions and corrected subtitles.
- Organize evidence by series; retain positive and negative examples and provenance.
- Use the corpus for regression tests, series vocabulary, acoustic evaluation and review prioritization.
- Explore optional character voice enrollment using several clean single-speaker samples with varied delivery.
- Retain individual embeddings locally and allow unknown speakers; do not force identity assignments.
- Evaluate reference-assisted diarization and, later, target-speaker extraction against held-out examples.

## 5. Compute backends and resource management

### CPU

- Use eight threads as the provisional default on the current eight-core / sixteen-thread Ryzen 7 9800X3D; retain explicit overrides.
- Benchmark eight versus sixteen threads using identical inputs and settings. Compare output quality as well as runtime.
- Tune Parakeet (ONNX Runtime) and CHIRP (PyTorch) independently.
- On other systems, use physical core count as an initial default, subject to benchmarking and resource limits.

### Optional GPU acceleration

- CPU-only operation remains fully supported; a GPU is never a prerequisite.
- Detect hardware and test actual backend compatibility at runtime, including device availability and VRAM where accessible.
- Investigate NVIDIA CUDA and AMD ROCm support separately for each inference engine and model.
- Allow automatic, CPU-only and GPU-preferred modes, with advanced per-component device selection.
- Provide configurable CPU fallback and preserve completed work if GPU inference fails.
- Record the actual backend, device and relevant settings in artifact provenance.
- Validate GPU results against CPU regression cases before recommending accelerated operation.
- ZOOKEEPER coordinates resource allocation; individual components remain independently usable.

## 6. Final GUI

- Make single-episode processing, progress, resume and human review accessible without command-line knowledge.
- Provide automatic hardware detection, supported-device reporting and optional GPU use.
- Expose CPU thread limits, fallback preferences and advanced per-component settings.
- Remember user preferences; clearly distinguish requested settings from the actual backend used.
- Present original captions, proposed changes, timing and supporting evidence in a review interface.
- Provide contextual playback and persistent accept/reject/edit decisions.
- Keep advanced configuration out of the normal workflow.

### Publishing (working name: STORK)

- Export final SRT and optionally create a separate preview or delivery MKV without re-encoding.
- Preserve original media; use descriptive subtitle track names and correct language metadata.
- Keep working evidence and subtitle artifacts authoritative outside the container.
- Validate final playback in Kodi as well as controlled MPV tests.

## 7. Installation and documentation

- Capture the working Python environments and model versions before they drift.
- Document separate core and CHIRP dependencies, model acquisition, authentication requirements and local storage.
- Planned files: INSTALL.md, requirements.txt, requirements-chirp.txt, setup.sh and a diagnostic utility (working name: WOODPECKER).
- Document architecture, models, troubleshooting and user workflow.
- Validate a clean installation; document CPU-only operation and optional GPU setup separately.
- Maintain DARS_PROJECT_HANDOFF.md for current status and ROADMAP.md for future direction.

## 8. Validation progression

1. Angel S03E01 — incomplete original captions, dialogue recovery, timing, speaker transitions and controlled regression cases.
2. The Powers of Matthew Starr — no original subtitles, older noisy audio and rapid dialogue.
3. 1970s Spider-Man — degraded archival audio/video stress test.
4. Earth: Final Conflict — final stress test: quiet dialogue, loud music, competing voices and interjections.

Explore alternate recognition passes, sliding windows, noise reduction, dialogue filtering, compression, center-channel extraction where applicable, neural dialogue isolation and optional speaker-targeted extraction. Preserve the raw evidence and evaluate each technique independently before combining them.

## 9. Success criteria

The objective is not perfect automatic transcription or speaker identification. The objective is readable, trustworthy subtitles and sufficient evidence for a human to resolve uncertain cases efficiently, without repeatedly performing work that the software can do reliably.
