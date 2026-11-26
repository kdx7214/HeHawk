# HeHawk external dependencies

Last reviewed: 2026-11-26

HeHawk gratefully acknowledges the developers, researchers and
organizations whose software and models make this project possible.

## Scope

This document identifies the principal external dependencies used
during HeHawk development.

Listed versions describe the current development environment,
not established minimum requirements.

License information is drawn from installed package metadata,
upstream project documentation and published model cards.

This is a preliminary dependency and licensing inventory,
not a completed redistribution compliance audit.

## Core environment

Python virtual environment: `.venv`

| Dependency | Installed version | Upstream URL | License | Purpose |
|---|---|---|---|---|
| Python | 3.12.3 | https://www.python.org/ | PSF-2.0 | Runtime |
| NumPy | 2.5.5 | https://github.com/numpy/numpy | BSD-3-Clause; additional bundled licenses | Numerical and audio processing |
| SoundFile | 0.14.0 | https://github.com/bastibe/python-soundfile | BSD-3-Clause | Audio file access |
| Metaphone | 0.6 | https://github.com/oubiwann/metaphone | BSD; exact variant pending verification | Phonetic comparison |
| sherpa-onnx | 2.0.3 | https://github.com/k2-fsa/sherpa-onnx | Apache-2.0 | Speech recognition |
| sherpa-onnx-core | 2.0.3 | https://github.com/k2-fsa/sherpa-onnx | Apache-2.0 | Native recognition implementation |

See [DEPENDENCIES_CORE.md](DEPENDENCIES_CORE.md) for the complete
installed Python package inventory.

## Acoustic and speaker-analysis environment

Python virtual environment: `.venv-chirp`

| Dependency | Installed version | Upstream URL | License | Purpose |
|---|---|---|---|---|
| Python | 3.12.3 | https://www.python.org/ | PSF-2.0 | Runtime |
| NumPy | 2.5.5 | https://github.com/numpy/numpy | BSD-3-Clause; additional bundled licenses | Numerical processing |
| SoundFile | 0.14.0 | https://github.com/bastibe/python-soundfile | BSD-3-Clause | Audio loading |
| PyTorch | 2.15.0+cpu | https://github.com/pytorch/pytorch | Multiple licenses; see below | Model inference |
| TorchAudio | 2.11.1+cpu | https://github.com/pytorch/audio | BSD; exact variant pending verification | Audio ecosystem dependency |
| TorchCodec | 0.17.0 | https://github.com/meta-pytorch/torchcodec | BSD-3-Clause (upstream) | Media decoding dependency |
| pyannote.audio | 4.1.1 | https://github.com/pyannote/pyannote-audio | MIT | Speaker diarization and embeddings |
| Silero VAD | 6.3 | https://github.com/snakers4/silero-vad | MIT | Voice activity detection |
| ONNX Runtime | 1.32.0 | https://github.com/microsoft/onnxruntime | MIT | ONNX model inference |
| Hugging Face Hub | 2.4.0 | https://github.com/huggingface/huggingface_hub | Apache-2.0 | Model acquisition |

See [DEPENDENCIES_CHIRP.md](DEPENDENCIES_CHIRP.md) for the complete
installed Python package inventory.

Not every installed package is necessarily required by HeHawk.
Direct and transitive runtime requirements will be established
during installation and packaging development.

## System executables and native libraries

| Dependency | Installed version | Upstream URL | License | Purpose |
|---|---|---|---|---|
| FFmpeg | 6.1.1-3ubuntu5 | https://ffmpeg.org/ | GPL-2.0-or-later for installed executable | Audio extraction and media processing |
| FFprobe | Pending confirmation | https://ffmpeg.org/ | Build-dependent | Media inspection |
| libsndfile | Pending confirmation | https://github.com/libsndfile/libsndfile | LGPL-2.1-or-later (upstream) | Native audio file access |

FFmpeg licensing depends on the options and libraries included
in a particular build.

Official licensing documentation:
https://ffmpeg.org/legal.html

The current FFmpeg executable reports GPL-2.0-or-later.
Its build configuration includes `--enable-gpl`.

The installed FFmpeg also reports a library configuration mismatch.
The libavcodec configuration includes `--enable-version3` and
additional libraries.

The full licensing implications of the installed native library
combination have not yet been reviewed.

No assumption should be made that every FFmpeg build has the same
license or redistribution requirements.

## Machine-learning models

Model weights are licensed separately from inference software.

| Model | Upstream URL | License | Purpose |
|---|---|---|---|
| NVIDIA Parakeet TDT 0.6B v2 | https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2 | CC-BY-4.0 | Speech recognition |
| sherpa-onnx Parakeet INT8 conversion | https://github.com/k2-fsa/sherpa-onnx | Original weights CC-BY-4.0; conversion artifact pending verification | Local ONNX speech recognition |
| Silero VAD bundled model | https://github.com/snakers4/silero-vad | MIT expected; bundled model verification pending | Voice activity detection |
| pyannote speaker-diarization-community-1 | https://huggingface.co/pyannote/speaker-diarization-community-1 | CC-BY-4.0 expected; verification pending | Speaker diarization |
| WeSpeaker VoxCeleb ResNet34-LM | https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM | CC-BY-4.0 | Speaker embeddings |

Current Parakeet model directory:

`models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/`

The original model and its converted or quantized implementation
must retain appropriate licensing and attribution information.

Model revision identifiers, acquisition URLs and checksums should
be recorded in future installation manifests.

Hosted model access conditions should also be reviewed separately
from the model license.

## Compound package licenses

Installed package metadata may identify additional licenses for
third-party material included in a distributed package.

NumPy 2.5.5 declares:

`BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`

PyTorch 2.15.0+cpu declares:

`Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib`

These expressions are retained as declared by the installed
distributions. They have not been independently validated against
every bundled component.

Do not substitute a project's primary source license for the
complete licensing information applicable to a distributed binary.

## Dependencies requiring further licensing review

The following installed packages lack usable license declarations
in their installed Python metadata.

| Package | Version | Upstream URL | Review status |
|---|---|---|---|
| pyannote-core | 6.1.0 | https://github.com/pyannote/pyannote-core | MIT on upstream development branch; exact version pending |
| pyannote-database | 6.3.0 | https://github.com/pyannote/pyannote-database | Pending |
| pyannote-metrics | 4.2.0 | https://github.com/pyannote/pyannote-metrics | MIT indicated upstream; exact version pending |
| pyannote-pipeline | 4.1.0 | https://github.com/pyannote/pyannote-pipeline | Pending |
| pyannoteai-sdk | 0.4.0 | https://github.com/pyannote/pyannoteAI-python-sdk | MIT indicated upstream; exact version pending |
| TorchCodec | 0.17.0 | https://github.com/meta-pytorch/torchcodec | BSD-3-Clause upstream; exact version pending |

Missing metadata does not imply that a package is unlicensed.
It indicates that additional verification is required.

## Upstream license references

- sherpa-onnx:
  https://github.com/k2-fsa/sherpa-onnx/blob/master/LICENSE

- TorchCodec:
  https://github.com/meta-pytorch/torchcodec/blob/main/LICENSE

- pyannote-core:
  https://github.com/pyannote/pyannote-core/blob/develop/LICENSE

- NVIDIA Parakeet:
  https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2

- WeSpeaker model:
  https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM

- Creative Commons Attribution 4.0:
  https://creativecommons.org/licenses/by/4.0/

## Planned and optional dependencies

Potential future dependencies are not included in the current
runtime requirements.

Local language-model runtimes, additional recognition engines,
GPU acceleration frameworks and GUI frameworks will be documented
when selected and integrated.

## Redistribution and attribution

Before distributing HeHawk with bundled third-party components:

- Verify the exact version and license of each component.
- Retain required copyright notices and license texts.
- Provide required model attribution.
- Identify modifications and model conversions where required.
- Review native libraries included in binary distributions.
- Review applicable source-code availability obligations.
- Review model-specific access and redistribution conditions.
- Establish a complete software bill of materials (SBOM).

This document does not replace required third-party license notices.

## Privacy

HeHawk is intended to process media and recognition evidence locally.

The installation of network-capable packages does not authorize
the transmission of media, dialogue, speaker embeddings or other
private evidence.

Model acquisition and any telemetry behavior must be reviewed
independently of dependency licensing.

## Regenerating environment inventories

The repository includes `dependency_inventory.py`, which uses
Python's standard library to inspect installed distribution metadata.

Core inventory:

```bash
./.venv/bin/python dependency_inventory.py \
    --environment core \
    --output DEPENDENCIES_CORE.md
```

Acoustic and speaker-analysis inventory:

```bash
./.venv-chirp/bin/python dependency_inventory.py \
    --environment chirp \
    --output DEPENDENCIES_CHIRP.md
```

The generator deliberately refuses to overwrite existing reports.
Preserve or rename the previous reports before generating replacements.

The inventories are environment snapshots, not installation lockfiles.

License uncertainty must be recorded explicitly rather than
resolved through unsupported assumptions.
