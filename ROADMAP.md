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

---

## 10. Development checkpoint — 2026-11-26

This section updates the implementation status and near-term
priorities described above.

See DARS_PROJECT_HANDOFF.md for detailed experimental results,
regression artifact filenames and exact resume instructions.

### Completed experimental milestones

- GULP faithful ingestion and independent auditing.
- SWAN presentation diagnostics and conservative timing adjustment.
- CHIRP full-episode diarization baseline.
- BOWERBIRD local acoustic and speaker investigations.
- LARK independent speech probability estimation.
- HUNT recognition omission inventory and differential comparison.
- TERN natural-pause segmentation and segmented recognition.
- Controlled recognition padding experiments.
- MAGPIE incremental caption corroboration.
- MAGPIE novelty and historical evidence classification.
- MAGPIE multi-pass recognition accumulation.
- MAGPIE localized disagreement detection.
- Decoder-aware lexical reconstruction.
- Exact token character ownership verification.
- Independent timing ownership and conservation audits.
- Decoder-aware localization differential audit.
- Fifty-one passing synthetic reconstruction regression tests.

Experimental completion does not imply production integration.

### 10.1 TERN — Recognition geometry and controlled alternatives

Retain natural-pause segmentation as an experimental recognition
strategy rather than assuming it universally improves accuracy.

- Preserve contiguous source sample geometry.
- Preserve segment-relative and episode-relative timing separately.
- Record padding parameters, seeds and actual input geometry.
- Compare alternate recognition passes without destructive merging.
- Preserve empty observations.
- Retain minority-only recognition hypotheses.
- Investigate boundary omissions and interior omissions separately.
- Do not assume silence padding and noise padding are equivalent.
- Do not infer unverified internal model mechanisms.
- Evaluate preprocessing techniques independently.

### 10.2 LARK and HUNT — Independent omission investigation

Speech detection and recognition coverage are separate evidence layers.

- Investigate speech-like intervals lacking recognition coverage.
- Investigate omissions shared by multiple recognition passes.
- Retain short gaps and possible interjections.
- Avoid blanket minimum-duration rejection rules.
- Distinguish acoustic uncertainty from lexical uncertainty.
- Preserve negative and inconclusive experimental results.
- Allow unresolved evidence to remain unresolved.

HUNT must not depend exclusively on MAGPIE disagreements.
Unanimous recognition can still omit genuine dialogue.

### 10.3 MAGPIE — Evidence-driven reconciliation

The current experimental system localizes lexical disagreements
across multiple recognition passes.

The next development sequence is:

#### 7G — Historical and caption evidence overlay

- Associate original captions with localized alternatives.
- Associate recovered caption candidates.
- Associate historical recognition observations.
- Preserve complete and partial supporting evidence.
- Distinguish historical observation from human verification.
- Identify genuinely novel hypotheses.
- Retain every alternative, including empty alternatives.
- Initially annotate evidence without eliminating review windows.

#### 7H — Independent omission evidence

- Overlay HUNT and LARK evidence.
- Identify possible shared recognition omissions.
- Include original-caption disagreements not represented in
  multi-pass lexical disagreements.
- Preserve punctuation and speaker-boundary uncertainty.
- Keep independent evidence categories visible.

#### 7I — Persistent human review queue

- Use stable evidence-based identities.
- Retain accept, reject, edit, defer and unresolved decisions.
- Retain exact evidence and proposal versions.
- Distinguish previously reviewed evidence from new hypotheses.
- Reopen decisions only when meaningful new evidence warrants it.
- Preserve conflicting evidence and decision history.
- Support contextual playback without requiring repeated
  full-episode listening.

#### 7J — Human review evaluation

Measure:

- Actual listening time.
- Number of playback repetitions.
- Decision time.
- Total human review effort.
- Dialogue completeness.
- Correction accuracy.
- Synchronization quality.
- Reading comfort.
- Previously resolved cases unnecessarily reopened.

Potential interval-coverage savings are useful diagnostics,
but are not substitutes for measured human review effort.

### 10.4 Decoder-aware reconstruction integration

Before promoting experimental reconstruction:

- Separate reusable verification helpers from test modules.
- Record reconstruction method in artifact metadata.
- Preserve original decoded text and raw token streams.
- Preserve exact character and token ownership.
- Preserve shared token timing without inventing subtoken timing.
- Validate punctuation-boundary classifications.
- Escalate ambiguous lexical boundary changes.
- Verify segment concatenation boundaries.
- Retain the original implementation until regression testing
  supports a deliberate migration.
- Validate on additional episodes and recording conditions.

### 10.5 ROOK — Orthographic evidence

Proposed component:
Recognition of Orthographic Oddities and Knowledge.

Responsibilities:

- Preserve meaningful apostrophes and hyphens.
- Distinguish contractions, possessives and ordinary words.
- Handle fictional names and series-specific vocabulary.
- Preserve numeric punctuation and meaningful lexical distinctions.
- Distinguish orthographic variants from competing hypotheses.
- Preserve raw line boundaries and speaker-marker evidence.
- Support contextual spelling proposals without forced replacement.

Character equivalence, lexical equivalence and semantic equivalence
are distinct concepts.

A normalization strategy must not silently collapse meaningful
alternatives merely to improve apparent recognition agreement.

### 10.6 ZOOKEEPER — Evidence dependency management

Extend the planned artifact dependency graph to distinguish:

- Immutable source evidence.
- Raw recognition observations.
- Acoustic observations.
- Reconstructed lexical and timing evidence.
- Derived interpretations.
- Proposed corrections.
- Human review decisions.
- Final presentation artifacts.

A change in reconstruction should invalidate affected derived
localization products without requiring unnecessary recognition reruns.

A change in presentation settings should not invalidate underlying
recognition or human dialogue decisions.

Preserve reusable evidence across interrupted sessions.

### 10.7 SCOOP — Cleanup safety

Never infer that an artifact is obsolete solely because a newer
artifact exists.

- Historical recognition can remain useful evidence.
- Negative experiments can prevent repeated failed investigations.
- Earlier hypotheses can corroborate later observations.
- Human decisions may reference older artifact versions.
- Require dependency-aware cleanup and explicit authorization.
- Preserve regression and curated evidence.

### 10.8 NUTCRACKER — Reviewed evidence and regression corpus

Retain examples of:

- Confirmed dialogue omissions.
- Confirmed recognition substitutions.
- Correct minority-only recognition.
- Incorrect unanimous recognition.
- Speaker-boundary ambiguity.
- Punctuation-boundary ambiguity.
- Timing ownership defects.
- Recognition sensitivity to context and padding.
- Successful and unsuccessful preprocessing.
- Human-confirmed unresolved or unintelligible passages.

Keep episode-specific evidence local.

Do not treat uncertain or automatically corroborated observations
as human-verified training examples.

### 10.9 Experimental benchmark

The current Angel regression produced:

- 170 recognition segments.
- Four recognition passes.
- 680 observations.
- 80 disputed segments.
- 117 localized disagreement regions.
- 87 contextual review windows.
- Zero remaining localization fallbacks.
- Zero detected lexical conservation failures.

Potential listening duration decreased from 1209.056 seconds
of complete disputed segments to 291.360 seconds of contextual
review windows, a reduction of 75.90 percent.

This is not a transcription accuracy measurement.
It does not include all possible omission or caption discrepancies.
Actual human review savings remain to be measured.

### 10.10 Operational priorities

- Process one episode at a time.
- Prefer reliable CPU implementations before optional GPU tuning.
- Prioritize accuracy, reproducibility and maintainability.
- Use explicit interpreter paths and artifact filenames.
- Use human-readable timestamps in diagnostic output.
- Preserve original media and manual corrections.
- Keep experimental code separate from production behavior.
- Keep all dialogue-bearing evidence local.
- Maintain documentation at successful experimental checkpoints.

---

## 11. Graceful uncertainty handling

Permanent architectural requirement, added 2026-11-26.

HeHawk must recognize the limits of its own interpretations.

Human-authored subtitles can contain unpredictable, inconsistent
or undocumented conventions. Recognition systems can also produce
unexpected, ambiguous or contradictory evidence.

It is neither practical nor desirable to encode a special-case
solution for every possible input.

### 11.1 General requirements

- Treat uncertainty as an ordinary processing outcome.
- Distinguish uncertainty from software failure.
- Preserve original evidence and alternative interpretations.
- Separate structural markup from inferred semantic meaning.
- Separate automatic resolution from human verification.
- Localize uncertainty wherever reliably possible.
- Continue independent work when dependencies permit.
- Escalate unresolved interpretations to human review.
- Never silently discard information to simplify processing.
- Never fabricate certainty to satisfy downstream components.

### 11.2 Component responsibilities

GULP:
Preserve original content and structural information without
assuming that presentation conventions establish semantic roles.

ROOK:
Represent ambiguous orthographic and semantic interpretations.
Do not force unsupported conventions into known categories.

MAGPIE:
Retain competing interpretations and supporting evidence.
Do not confuse lexical agreement with semantic certainty.

LARK and HUNT:
Preserve acoustic uncertainty independently of lexical evidence.
Do not infer absence of speech solely from absent recognition.

CHIRP and BOWERBIRD:
Permit unknown speakers, ambiguous transitions and insufficient
acoustic evidence without forcing assignments.

SWAN:
Preserve unresolved presentation conflicts for review rather
than damaging dialogue or synchronization to satisfy formatting rules.

NUTCRACKER:
Persist human decisions, including deferred and unresolvable cases.
Preserve decision provenance and relevant evidence versions.

ZOOKEEPER:
Coordinate partial completion, review requirements and dependencies.
Do not repeatedly process unchanged unresolved cases.
Distinguish recoverable uncertainty from actual processing errors.

SCOOP:
Preserve evidence required by unresolved review items and
historical human decisions.

STORK:
Clearly distinguish provisional previews from approved final output.
Do not silently present unresolved corrections as verified results.

### 11.3 Validation requirements

Develop synthetic regression cases covering:

- Bracketed dialogue.
- Mixed dialogue and non-dialogue annotations.
- Unusual speaker and source attribution.
- Ambiguous punctuation and lexical boundaries.
- Inconsistent conventions within one episode.
- Unsupported but structurally preservable input.
- Conflicting evidence.
- Insufficient evidence.
- Human-confirmed unresolvable cases.
- Actual processing errors.

Verify that uncertain input does not cause:

- Silent information loss.
- Duplicate dialogue insertion.
- Unsupported automatic correction.
- Unnecessary termination of independent processing.
- Loss of previously completed work.
- Repeated review requests without meaningful new evidence.
- Software defects being concealed as ordinary uncertainty.

### 11.4 Success criteria

A component that correctly identifies its inability to resolve
an interpretation and safely escalates it has succeeded.

Human intervention is a supported part of the architecture,
not a workaround for architectural failure.

The objective is not to eliminate human judgment.
The objective is to use human judgment where it is genuinely needed.

## Progress checkpoint — 2026-11-26

- [x] 7G: MAGPIE evidence overlay.
- [x] 7H: HUNT shared recognition gap inventory.
- [x] 7H.1: Sample-grid precision audit.
- [x] 7H.2: Integer sample coverage experiment.
- [x] 7H.3: Independent sample conservation audit.
- [x] 7H.4: Evidence association sensitivity audit.
- [x] 7H.5: Corrected evidence associations.
- [x] 7I.1: Progressive review scheduling.
- [x] 7I.2: Persistent SQLite review decisions.
- [ ] 7I.3: Interactive local review interface.
- [ ] 7I.4: Practical cross-tier review verification.
- [ ] 7J: Actual human review workload measurement.
- [ ] Production integration of experimental adapters.
- [ ] Apply reviewed decisions to caption output.
- [ ] Final timing and readability verification.

Experimental completion does not imply production
readiness or verified acoustic correctness.

The immediate priority is interactive human review.
Additional research remains documented in
RESEARCH_BACKLOG.md.


## 12. Operational architecture — 2026-11-27

Design requirements and proposals; not implemented or validated unless stated.
This section refines earlier operational priorities. Task-oriented UI,
evidence-oriented backend. Opening media is distinct from processing it.

### 12.1 Media identity and discovery

One configurable read-only media library root contains Movies, Series and
MusicVideos (ignored initially). Example relative paths:
- Movies/Aladdin (1992).mkv
- Series/Angel (1999)/Season 3/S03E01.mkv
- Series/Angel (1999)/tvshow.nfo

The library is a single CIFS share; mounting/authentication belongs to the OS.
Store portable relative paths with forward slashes, preserving original spelling.
Resolve against configured absolute roots using platform-aware path handling.
Support explicit absolute paths without relying on shell tilde expansion.
Parse terminal parenthesized year, season and episode where reliable; never rename
sources. Support arbitrary local files and absent or malformed metadata.
Read optional Kodi NFO, cache provenance and original metadata, import namespaced
external IDs and character/actor candidates. No internet dependency. External IDs,
paths and titles are not internal identity. Distinguish series/movie, episode,
media release/version and audio/subtitle track identity. Different releases may
have different timelines. Do not silently transfer timing or decisions.
Resolve ambiguity explicitly when needed. Source fingerprint and verification
policy remains to be designed, including cost of full network reads.

### 12.2 Storage and resource acquisition

User environment: 1 TB system drive, 4 TB secondary SSD, existing workspace
~/drive_d/t. Do not assume these paths or capacities on other installations.
Independently configurable media, workspace, persistent data, model, cache,
temporary and export roots. Resolve and validate paths and expected volumes.
Detect missing mounts even when mount-point directories still exist; never silently
fall back to root filesystem or /tmp. Check permissions, available space and
configurable reserve per actual filesystem. Estimate peak concurrent usage.
Configure subprocess and library temporary/cache locations before initialization
where supported (TMPDIR/TEMP/TMP, Python tempfile, model caches, SQLite temporary
storage, logs). Test actual third-party behavior; configuration alone is not proof.
Use operation-specific temporary directories and incomplete-file markers; verify
before publication. Recover safely from cancellation, crashes and disk exhaustion.

Full local MKV staging is optional. Prefer selective FFmpeg extraction from the
network for unattended audio/subtitle analysis; use one read pass where practical.
Inventory streams with ffprobe, preserve native subtitle formats including unsupported
bitmap tracks, retain track metadata and original timeline mapping. Preserve suitable
native audio/channel information when needed; derive 16 kHz mono for recognition.
Do not assume extraction saves network bandwidth: interleaved streams may require
reading most of the source. Reuse verified extracted resources. MPV may play the
network source or a verified local copy. Remuxing requires original media access.
Proposed policies: extract-only, full staging, automatic. Modules request resources
rather than assume a local MKV. Exact extraction formats and timestamp verification
remain open. Do not mix commentary, alternate language or unrelated audio tracks.

### 12.3 Persistent data and cleanup

Separate application preferences/models, movie or series knowledge, season/release/
track conventions and episode-specific evidence, review and exports. A mirrored
hierarchy with project manifests and SQLite knowledge/review databases is proposed,
not a finalized schema. Persist source provenance, dependency versions and review
position. Save confirmed decisions immediately; preserve revision history.
Keep human decisions and curated references protected; retain reusable evidence
unless explicitly removed; allow controlled cleanup of regenerable resources only
when no active dependency requires them. Never clean original media. Export to
network is a separate explicit operation. Support independent data backups.

### 12.4 Processing lifecycle and batch scheduling

Lightweight open: identify media, discover existing project and metadata, inspect
streams as needed, restore work and present task choices. Do not automatically
run acoustic analysis merely because a video is opened.
Process Video exposes desired outcomes (generate, repair, timing, audit), a recommended
plan and optional advanced settings. Speaker references and export are separate tasks.
ZOOKEEPER manages a dependency graph, not a mandatory linear pipeline. Each stage
needs a contract: purpose, inputs, outputs, consumers, execution conditions,
invalidation, uncertainty and human involvement. Timing-only tasks need not run ASR.
Track individual operation states; derive project status from them. Preserve valid
completed stages and checkpoints, support cancellation and restart. Never silently
replace human decisions when new evidence becomes available.

Future batch scheduling: persistent queue of individual episode jobs, initially
serial execution with intra-episode parallelism. Automated evidence preparation
must run independently of GUI and human review. Prepare a season overnight, then
present episode-level review queues and actionable exceptions. No unattended human
acceptance. Defer ambiguous track selection or corrupt episodes and continue independent
jobs; suspend affected work on storage or integrity failure. Reuse valid checkpoints
and available local resources during network outages. Allow explicit retention policy
for staged copies. Batch is a scheduling feature, not a separate processing engine.
Single-episode development remains the immediate priority.

### 12.5 Speaker enrollment and transition review

Optional preparation before batch processing: mark video/audio intervals and assign
known characters, using NFO candidates when available. Also enroll during normal
review. Preserve local series/movie reference library, source track and interval,
provenance, model version and revision history. Distinguish character identity from
acoustic voice profile and sample conditions (recasting, possession, modified voices).
Support apparent emotion, delivery, voice type, pitch, apparent vocal age, optional
language, noise degree, music, competing speech, echo/hiss/hum/distortion and notes.
Unknown values are valid; avoid hard exclusions based on voice descriptors.
Keep enrollment and evaluation samples separate. Noisy examples may be useful.
FINCH should eventually supply automatic acoustic measurements to reduce manual
annotation burden, preserving human observations separately from measured estimates.

Distinguish speaker change detection from speaker identification. CHIRP transitions,
BOWERBIRD references, PARAKEET word timing, LARK pauses, ROOK caption markers and
FINCH noise evidence can support proposed changes within one subtitle. Evidence
sources may be correlated. NUTCRACKER should present speaker transition decisions;
propose speaker markers or cue splits only with timing/readability evidence. Do not
blindly split at acoustic boundaries. Preserve embeddings and intervals for targeted
reassessment after new references or terminology become available. Protect confirmed
decisions. Reference-assisted accuracy and short-transition reliability need testing.

### 12.6 Foreign text preservation (current scope)

Preserve Unicode throughout ingestion, comparison, review and export. Pass foreign
text using other language symbologies through without automatic textual changes;
protect affected spans from English ASR-based corrections, preserve surrounding
English where reliably separable, allow explicit manual editing and non-destructive
timing analysis. Character repertoire is not language identification: accented names
and ASCII-only foreign dialogue are counterexamples. Conservative protection rules
and regression tests remain to be defined. Preserve raw text independently of
comparison normalization. Do not introduce language detection, multilingual models
or translation now. See deferred research backlog.

### 12.7 Near-term implementation order

Specify media ingestion and project initialization first, then stage contracts and
persistent state. Resume 7I.4 human-oriented presentation, playback and application
shell, validate review semantics and persistence, then measure actual human effort
(7J). Keep technical controls behind progressive disclosure. Preserve experimental
results and avoid expanding research scope before a usable workflow exists.


## 13. CLI integration and additional operational requirements — 2026-11-27

Proposed requirements; not implemented. This section supersedes the immediate
implementation order in 12.7 while preserving its GUI requirements.

### 13.1 Single-file integration prototype

Accept one required video filename (absolute or relative), with independently
configured local storage. Incrementally validate: FFprobe inventory; project
identity and initialization; optional tvshow.nfo discovery/import; audio and
subtitle selection; extraction; GULP normalization; acoustic and recognition
evidence; MAGPIE/HUNT/SWAN analysis; NUTCRACKER scheduling; CANARY export.
Use actual network library paths and a fresh isolated workspace. NFO is optional,
series-shared and provenance-bearing; malformed/missing metadata must not block
independent work. Test movies, episodes, DVD/Blu-ray, foreign-language media,
missing subtitles and ambiguous tracks. Defer ambiguity rather than guess.
Test restart, reuse, interruption, missing intermediates, changed settings and
storage failure. GUI and future batch queue invoke the same backend. No unattended
human acceptance. Begin with inventory only; no expensive processing yet.

Source media and NFO are immutable inputs. Never write, rename, move or delete
them or place intermediate files beside them. Prefer OS read-only access where
practical. All working outputs use validated local roots; no silent fallback.
STORK produces separate files, not in-place changes. Explicit publication remains
separate from processing. Correct NFO discovery for Series/Angel (1999)/Season 3/
S03E01.mkv is Series/Angel (1999)/tvshow.nfo.

### 13.2 CANARY diagnostic presentation

CANARY: Caption Annotation and Narrative Anomaly Review utilitY. Produce a separate
viewing SRT and local generation audit from the integrated workflow. Preserve
baseline caption text; identify suspected competing wording and speech gaps with
short readable warnings and evidence IDs. Distinguish speech absent from recognition
from speech absent from captions; do not assert confirmed omissions. Focused tier
initially, with balanced/comprehensive available later. Avoid overlapping cues,
obscured dialogue and excessive reading burden; report undisplayed warnings.
Do not accept evidence or modify originals. Evaluate warning usefulness, false
positives and distraction during ordinary full-episode viewing. Exact annotation
placement and timing remain experimental. CANARY is an integration test, not a
replacement for persistent review or final export.

### 13.3 Shared editing engine

Guided review and unrestricted manual editing share the same validation, persistence
and revision rules. Support add, edit, delete, split, merge, retime and restore on
any caption, not only flagged ones. Deletion is reversible exclusion from the working
track, not destruction of evidence; prevent automatic reinsertion of deliberately
deleted content. Preserve attribution/provenance and applicable attribution obligations.
Recognize that source credits, administrative text and on-screen text may be unspoken;
absence of speech does not justify deletion. Dedicated attribution detection is not
required initially. Manual editing without ASR is a valid workflow and integration test.
Focus on fidelity, completeness, timing, readability and accessibility, not feature
parity with Subtitle Edit or elaborate karaoke/typesetting/disc authoring.

### 13.4 Track relationships and imported references

Audio language, subtitle language and relationship are independent. Same-language
subtitles may translate the original rather than transcribe a dub. Support explicit
transcription, translation, mixed and unknown relationships. Declare component
capabilities; disable unsupported English ASR and incompatible lexical comparisons
for foreign audio. Timing/manual editing remain useful; acoustic and speaker analysis
require validation. HUNT gaps in translated captions are not proof of omissions.
No automatic language detection or multilingual models in the initial workflow.

Support multiple independent reference subtitle imports, including partial manually
created SRTs, downloaded files, embedded tracks and previous exports. Preserve original
bytes, hash, origin, language, release association and lineage; duplicates and derived
sources are not independent corroboration. No reference is infallible. Initial import
and manual association precede advanced alignment. Distinguish work, edition, asset
and track; reuse series knowledge but transfer dialogue decisions only after validated
alignment. Release-specific timing stays separate. Country of origin is not required.
Timeline mappings may be identity, offset, scale, scale plus offset, piecewise or
unmapped for exclusive scenes. Preserve source timestamps; avoid cumulative rounding.
PAL 24-to-25 speedup is a possible scale of 0.96, not inferred from frame rate alone.

### 13.5 Evidence and presentation durability

Separate overlapping timeline events from output cue limitations; timestamps are not
unique word identities. Preserve raw engine observations and versioned common evidence;
confidence scores across engines are not assumed comparable. Output profiles may later
include faithful restoration, dialogue-only, accessible sound/speaker annotations,
readability, translation and diagnostic preview. Preserve human decisions, undo/grouped
revisions, dependencies and export provenance. Use transactional schema migrations,
backups and selective regeneration; protect irreplaceable human work. Accessible UI:
no essential information conveyed only by audio or color; keyboard and adjustable
text/contrast/playback. Resource-aware scheduling and disaster recovery remain design
requirements, not immediate implementation scope.


## 14. Discovery checkpoint and Phase 5 — 2026-11-27

Phases 1–4c: discovery, optional NFO parsing, workspace initialization and
preliminary track selection implemented. Ten real-media regression tests passed.
See DARS_PROJECT_HANDOFF.md for inventory and resume instructions.

Phase 5 next: define resource identity, provenance, source verification, native
compressed audio and subtitle preservation, timestamp mapping, derived PCM,
peak storage accounting, incomplete output handling, verification and reuse.
Prefer selective extraction from the mounted library; no full-video copy by
default. Preserve all subtitle streams, including unsupported bitmap formats.
Do not assume container flags establish dialogue language or caption purpose.
Do not authorize English ASR solely from an untagged audio selection.
Validate mount and storage before processing; route temporary files and model
caches to configured local storage, not the boot drive. Test actual decoder and
third-party behavior. Extraction, cache routing and recovery are not yet complete.

Future manual interval operations should share player selection, original-media
time mapping and review persistence: language identification, language-specific
recognition and eventually human-reviewed translation. These are not Phase 5
requirements. No automatic translation or multilingual model loading now.

## 15. 2026-11-27 — Phase 5B completion

Phase 5A: resource planning, workspace validation,
transactional publication and recovery implemented.

Phase 5B: native audio extraction implemented.
AAC, AC3, EAC3, MP3 and TrueHD specimens passed
native preservation and reusable qualification tests.

Verification schema 3 distinguishes native preservation,
decoded equivalence and decoder integrity.
Timeline mapping remains unverified.

Phase 5C next: native subtitle preservation.
Preserve all embedded subtitle streams, including
unsupported, foreign-language and bitmap streams.
Choose resource containers by verified compatibility.
Never silently transcode native resources.

Remaining Phase 5 sequence:
- 5C: Native subtitle preservation.
- 5D: Derived recognition PCM.
- 5E: Timeline verification.
- 5F: Resource reuse and selective invalidation.
- 5G: Interruption and recovery integration.
- 5H: Integrated regression testing.

## 2026-11-27 — Phase 5C interim checkpoint

Native subtitle preservation experiments have passed
for five codecs across six real-media specimens:

- ASS
- MOV_TEXT
- PGS
- VobSub (SD and HD)
- SubRip (embedded SRT)

Use Matroska subtitle resources (.mks) for qualified
ASS, PGS, VobSub and SubRip streams.

Use MP4 for qualified MOV_TEXT streams. The tested
FFmpeg configuration requires -write_btrt 0 to avoid
adding initialization data absent from the source.

These are specimen-specific qualification results,
not universal codec compatibility guarantees.

The shared packet verifier is implemented and committed.
The dedicated subtitle verifier has passed all six
specimens and 35 automated regression tests.

A separate controlled ASS initialization experiment
also passed. Permanent regression integration remains
pending.

Production subtitle extraction and publication,
external SRT ingestion, independent qualification
modules and timeline verification remain incomplete.

### Revised remaining Phase 5C sequence

- 5C.9: Complete verifier regression tests.
- 5C.10: Transactional native subtitle extraction.
- 5C.11: External SRT preservation.
- 5C.12: Independent codec qualification suite.
- 5C.13: Documentation and completion.

### Subtitle processing modes

Provide three independent processing modes:

1. Presentation normalization of existing subtitles.
2. Evidence-assisted subtitle repair.
3. Subtitle generation where captions are absent.

Presentation normalization must not require audio
extraction, audio decoding, ASR, diarization or
recognition model loading.

Support future unattended batch presentation auditing
and preparation of normalized subtitles for review.

### Accessible presentation

Prefer clean SRT as the default accessible text export.

Allow the playback application and viewer to control
font, size, outline, contrast and placement.

Avoid unnecessary explicit font specifications,
positioning, colors, indentation and animation.

Preserve meaningful emphasis, speaker distinctions,
sound descriptions and dialogue completeness.

Intelligent capitalization restoration is a separate,
optional and reversible normalization operation.
Do not apply naive case conversion to uppercase
legacy captions.

Preserve native resources and human decisions.
Never automatically replace source media or publish
unreviewed derived captions into the media library.

Detailed case restoration and presentation auditing
remain deferred research topics.
