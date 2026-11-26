# HeHawk — Research references

This living bibliography records research relevant to HeHawk's design. Published findings, engineering hypotheses and local validation results must remain distinct. A citation is not a substitute for testing our models.

## CHIRP: speech duration and speaker attribution

### R001 — Temporal structure of spontaneous English

Greenberg, S., Carvey, H., Hitchcock, L., & Chang, S. (2003). Temporal properties of spontaneous speech—a syllable-centric perspective. *Journal of Phonetics*, 31(3–4), 465–485. https://doi.org/10.1016/j.wocn.2003.09.005

**Published findings:** Analysis of 45 minutes of annotated SWITCHBOARD telephone conversation describes a broad American English syllable-duration range of 50–400 ms. Mean unstressed vowel durations are 55–75 ms; stress strongly affects duration.

**HeHawk implication:** Short speech events must not be excluded solely because of duration. Syllable duration is not a minimum independent utterance duration or a speaker-identification threshold.

### R002 — Perception of brief speech fragments

Harding, S., & Cooke, M. (2008). Perception of speech properties from extremely brief segments. *Acoustics 08 Paris*. https://dael.euracoustics.org/confs/acoustics2008/data/articles/000723.pdf

**Published findings:** Listeners classified selected vowel and fricative fragments lasting 2.5–80 ms. Fitted perceptual thresholds were 3.0 ms for vowel/fricative discrimination, 6.7 ms for voicing, 11.9 ms for phoneme identification and 15.3 ms for gender identification.

**HeHawk implication:** Even very short segments can carry useful acoustic information. These task-specific thresholds do not establish reliable individual speaker attribution, complete utterance recognition or conversational turn detection in noisy mixed audio.

### R003 — Backchannels and conversational turns

Reece et al. (2023). The CANDOR corpus: Insights from a large multimodal dataset of naturalistic conversation. *Science Advances*. https://pmc.ncbi.nlm.nih.gov/articles/PMC10065445/

**Published findings:** The study estimates around 1,000 backchannel words per hour of conversation. Its Backbiter representation records listener responses alongside primary turns rather than necessarily fragmenting those turns.

**HeHawk implication:** Distinguish speaker activity, conversational floor changes, overlapping speech and subtitle segmentation. A short response may be important without ending the primary speaker's turn.

## Engineering hypotheses — not validated thresholds

CHIRP's local experiments show rapid alternating assignments at approximately 16.875 ms increments. This is consistent with frame-level instability, but the model's precise temporal resolution has not been independently verified.

Candidate duration bands for descriptive analysis (not deletion rules):

| Duration | Investigation focus |
|---|---|
| <25 ms | Frame-level instability |
| 25–50 ms | Brief acoustic/phonetic events |
| 50–100 ms | Potential meaningful speech |
| 100–200 ms | Possible short interjections |
| >=200 ms | Ordinary analysis; still uncertain |

Evaluate persistence, alternation patterns, lexical alignment, nearby speaker activity and independent acoustic transition evidence. Preserve raw assignments and alternative interpretations separately. Do not infer silence from absent diarization or discard background speech based on unknown identity.

## Local validation plan

- Compare candidate stability interpretations with human-reviewed NUTCRACKER examples, including stable single speakers, false oscillations, genuine transitions, short interjections and overlapping speech.
- Measure false transitions and missed real transitions separately; include uncertainty and incomplete coverage.
- Compare speaker attribution with and without verified BOWERBIRD voice samples at varied sample lengths and noise conditions.
- Use held-out examples to evaluate thresholds; avoid tuning and reporting accuracy on the same examples.
- Keep episode media, dialogue, voice samples and dialogue-bearing diagnostics local. This bibliography contains public research and general engineering notes only.

## Open research questions

- What is the distribution of durations for independently intelligible English interjections and backchannels?
- How does individual speaker attribution accuracy vary with duration, noise, overlap and availability of reference samples?
- Which temporal instability patterns are characteristic of the actual CHIRP model rather than human speech?

No source above establishes a universal minimum duration for an independent English vocalization or a reliable speaker transition.
