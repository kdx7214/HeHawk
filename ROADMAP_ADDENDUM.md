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
