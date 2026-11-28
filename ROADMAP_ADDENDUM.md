# HeHawk — Roadmap addendum (2026-11-25)

Read alongside ROADMAP.md. These are planned capabilities unless explicitly marked experimental.

## BOWERBIRD / NUTCRACKER
- Assisted collection and manual collection prototypes exercised successfully. Manual collection has no diarization prerequisite or minimum duration. Preserve immutable collections and explicit provenance.
- Series-wide character profiles with episode provenance; prioritize underrepresented voices and varied conditions rather than only long passages. Distinguish character identity, vocal persona, speech/singing and emotional delivery. Keep unknown and mixed examples as negative/diagnostic evidence.
- GUI: video playback, waveform, subtitle context, precise adjustable selections, A/B looping, character selection and verification, assisted and manual modes. Support brief guest-character utterances.
- Audit source overlap before validation; hold out independent recordings. Record source/track/interval, model revision, settings, quality and vocal coverage. Preserve raw audio locally for future models. Do not equate elapsed time with vocal duration.
- Compare individual short-utterance embeddings, normalized embedding aggregation and concatenated audio as separate experimental methods. Never replace original fragments with concatenations. Test singing separately and account for accompaniment.
- Compare individual samples, centroids, nearest neighbors and multiple-neighbor agreement; no fixed acceptance threshold until independently validated. Optional reference-assisted diarization; avoid self-reinforcing provisional labels.

## CHIRP refinement
- Sliding windows at multiple durations; compare raw and stabilized assignments, distinguish speaker activity from turn changes. Evaluate temporal persistence, oscillation, lexical alignment and independent acoustic evidence. No blanket deletion of short events.
- Iterative global clustering, temporary high-quality episode profiles, targeted local reanalysis and comparison. Keep verified profiles separate from provisional clusters. Stop on stability, no improvement, review requirement or resource limit.
- Controlled context experiment: compare same early passage with increasing surrounding context, with/without independent verified profiles. Global offline clustering is not necessarily chronological learning.
- Report false and missed transitions, boundary accuracy, attribution uncertainty and coverage. Human review before splitting cues.

## Integration and reproducibility
- GULP faithful ingestion; independent recognition; MAGPIE reconciliation informed by CHIRP; SWAN final presentation and audit; STORK optional publishing. ZOOKEEPER dependency graph and resumability; SCOOP reference-aware cleanup with authorization, never curated evidence.
- Capture environment versions, pin model revisions, document installation and clean-install validation. CPU default eight threads provisional; optional GPU only after compatibility and quality testing.
- Preserve original README, handoff, roadmap and bibliography. Current checkpoint supersedes historical resume instructions. No new literature claims in this addendum; existing REFERENCES.md remains unchanged.

## 2026-11-27 — Phase 5B completion

### Resource dependency hierarchy

1. Immutable original media.
2. Verified native extracted resources.
3. Derived working resources.
4. Recognition evidence and human review decisions.
5. Approved deliverables.

Derived resources should record upstream identities,
hashes, algorithm versions and processing parameters.
Invalidate only affected dependencies.
Preserve human corrections and independent evidence.

SCOOP must distinguish regenerable intermediates
from irreplaceable resources and human decisions.

### Subtitle representation

Preserve native timing, formatting and positioning.
Independent simultaneous events remain independent.

OWL recognizes bitmap content without assuming
screen placement. NUTCRACKER retains spatial and
temporal evidence. GULP normalizes working text.
SWAN resolves presentation conflicts when required
by the destination format or playback environment.

Native preservation and readable export are separate
operations. Never discard spatial evidence merely
because SRT cannot faithfully represent it.

### Deliverable staging

Future configurable staging directory, separate from
projects and the original media library.

Mirror the source library's relative directory
hierarchy. Stage only explicitly approved, verified
deliverables. Preserve export provenance.

Never automatically write to the original media
library, even when it is writable. Final transfer
remains a manual user operation.

SCOOP must not automatically remove staged deliverables.

## 2026-11-27 — Phase 5C interim checkpoint

### Accessible presentation principle

The subtitle author controls what is communicated.
The viewer controls how it is displayed.

Preserve faithfully.
Interpret intelligently.
Present consistently.

### Component responsibilities

- OWL: native preservation verification and future
  bitmap recognition.
- ROOK: structural and semantic caption interpretation.
- GULP: working text normalization, presentation
  auditing and optional contextual case restoration.
- MAGPIE: independent recognition and terminology
  evidence where available.
- NUTCRACKER: evidence provenance, uncertainty,
  review decisions and reversible corrections.
- SWAN: readable output grouping, timing and
  presentation conflict resolution.
- ZOOKEEPER: dependency-aware processing modes,
  scheduling and selective execution.
- SCOOP: authorized cleanup of regenerable resources.

Presentation-only processing must not trigger
unnecessary acoustic or recognition dependencies.

Preserve original styles, positioning and colors
as potential evidence, even when the accessible
export omits them.

Do not infer speaker identity solely from formatting.

Clean SRT should delegate font selection, size,
outline and placement to the playback application.

Preserve meaningful emphasis and speaker distinctions.
Avoid unnecessary styling and artificial indentation.

Case restoration is distinct from formatting removal.
It must remain optional, independently reversible
and subject to evidence-aware review.

### Embedded and external SubRip

Embedded SubRip and external SRT files require
different native preservation contracts.

Embedded SubRip:
- Preserve native packets in a qualified container.
- Verify packet timing, payload and initialization.
- Retain source stream metadata and provenance.

External SRT:
- Preserve exact original bytes and file hash.
- Do not normalize encoding, BOM or line endings
  during native ingestion.
- Preserve source association and lineage.
- Treat parsing and normalization as derived operations.
- Report malformed records and encoding uncertainty.
- Support partial, manually authored, downloaded and
  previously exported reference subtitles.
- Validate release-specific alignment before reuse.

Do not assume external SRT timing matches the
associated media merely because filenames match.

Protect confirmed human corrections from automatic
recognition-based replacement.

These are planned ingestion requirements. External
SRT production ingestion is not yet implemented.
