# Public Saudi-English fallback measurements

Measured 2026-11-02 UTC / 2026-11-03 Bangladesh time. These are public proxy
measurements, not Tanzir's private meeting acceptance. The owner waived supplying
private clips; that waiver remains in effect.

## Inputs and protocol

- [Perle-ai/ASR_Code_Switch](https://huggingface.co/datasets/Perle-ai/ASR_Code_Switch),
  revision `1cc5950241e02500c43e39e8f37cce93c2dca5fb`, Saudi subset, MIT.
  The [paper, section 3.2](https://arxiv.org/pdf/2605.19069) describes native
  Najdi/Hijazi contributors delivering supplied conversational transcripts in
  quiet indoor settings. This is recorded speech, with a scripted collection
  protocol; it does not establish noisy/spontaneous meeting performance.
- A selection fixed before inference takes 15 publisher-labelled female and 15
  male recordings, evenly spaced by ensemble-score rank within each group,
  filename as tie-breaker. Only mixed-script reference rows qualify. This is
  difficulty/gender coverage, not a population sample or the full 300-clip set.
- Thirty source MP3s were checked against pinned repository blob hashes and
  decoded to mono 16 kHz PCM16 WAV. Total input is **272.166 seconds**, with
  **755 normalized reference words** and **186 Latin-word occurrences**.
  Source/WAV hashes and IDs are in the checked-in provenance receipt.
- The real desktop VAD emitted 30 segments, totalling 267.944 seconds. Both
  recognizers use `FastWhisperASR`, CPU int8, five CTranslate2 threads and the
  desktop guards. Arabic is forced for these mixed Arabic-matrix clips.
  Pair LID, glossary hotword prompts and MT are outside this component probe.
- Main source was `ca1970a941813c7ff0d448a60bc4df354ba78e92`, no tracked changes.
  Python 3.13.17, Torch 2.13.0+cpu, Transformers 5.22.1, faster-whisper 1.2.1,
  CTranslate2 4.8.4 and Silero 6.2.3; six physical CPU cores. Each candidate ran
  separately; model/VAD setup is excluded from decoder RTF. Inference sockets/DNS
  were blocked. No audio/text upload, provider account or paid call was used.

## ASR results

WER is micro word error rate, summed within clips; punctuation, NFC, case and
whitespace are normalized. Arabic spelling/diacritics remain significant. These
numbers are not a reproduction of the paper's provider rankings.

| Candidate | Beam | WER | English recall | Decode / speech RTF | Peak RSS GiB |
|---|---:|---:|---:|---:|---:|
| Existing app Small cache | 3 | 65.83% | 8/186 = 4.30% | 0.389 | 0.674 |
| Code-switch Medium | 3 | 54.30% | 112/186 = 60.22% | 1.051 | 1.449 |
| Code-switch Medium, Fast | 1 | 56.03% | 109/186 = 58.60% | 0.974 | 1.337 |

Raw decoder times were 104.279s, 281.618s and 260.981s. No candidate emitted an
empty segment or a fourfold repetition loop. Applying the shared text cleanup
and read-only glossary afterwards changed Small to WER 65.17% / recall 7.53%,
and Balanced code-switch to WER 54.44% / recall 60.22%; Fast was unchanged.
These are post-hoc text forms, not full controller replays.

Only Small passed the component RTF <0.7 headroom gate, with very poor English
retention. Neither code-switch preset passed live headroom or reached 70% recall
here. This does not test the required primary Cohere recognizer. The component
results establish no four-second end-to-end, LID-accuracy or chrF acceptance.

### Weight provenance

The Small baseline is the app's existing quantized cache: 248,203,797-byte
`model.bin`, SHA-256
`ca732cb1379efc49417d028465f543d83a39de2c61f3027678de103dc404ce73`.
An encoder-width check confirmed 768 and runtime compute `int8_float32`.
Its bytes differ from the current public Systran bundle; pretrained weight
lineage was not established. The benchmark's requested Systran alias must not
be read as proof that the override is byte-identical to that snapshot.

The [code-switch conversion](https://huggingface.co/Seif-Eldeen-Sameh/whisper-medium-arabic-codeswitched-ct2)
was fetched at `7676461a26fc6d62d1d852f54749c24d9cc383f7`; its card declares MIT.
The 774,731,149-byte weight hash is
`1bbc9ac07f1dc576295805b81505681b0b6a184e268194659a04ca15733f7d4f`.
Its [source/tokenizer](https://huggingface.co/Seif-Eldeen-Sameh/whisper-medium-arabic-codeswitched)
at `8693f1d8e60a77cd34869055defbe6d08f50e1d7` declares Apache-2.0. All inference
files were verified against pinned hashes, all tokenizer/vocabulary IDs matched,
and both model cards were retained. This Egyptian-tuned model was downloaded
anonymously into an isolated D: test cache; it was not selected in user settings
or bundled into an installer.

## Actual local MT protection

The cached ar→en Marian adapter translated the 30 publisher reference texts with
its normal four-beam/protection/fallback path, sockets blocked and Torch threads
set to one. No English reference translations were invented; chrF is unavailable.

- **All 30** protected attempts lost at least one bracket-index placeholder and
  used the specified unmasked fallback. None raised a pipeline exception.
- Exact-case Latin-run multiset survival passed **17/30 lines (56.67%)** and
  **171/185 occurrences (92.43%)**. The Latin-run tokenizer differs from the ASR
  Latin-word metric. This fails the 98% line target. It does not measure semantic
  adequacy, token alignment, glossary punctuation or the reverse direction.
- Development-only whole-sentence marker pilots passed 23/30 first attempts for
  numeric IDs, 4/30 for ASCII IDs, 0/30 for visible bracketed words and 19/30 for
  quoted words. Reusing the recorded deterministic unmasked results for failed
  cases yields 26, 19, 17 and 23 passing lines respectively. These pilots used
  Latin-run boundaries, without the complete glossary phrase grouping; they are
  not drop-in adapter validation. Numeric failures included omitted final
  clauses, which cannot be repaired by marker-format normalization.
- No pilot was promoted. A disjoint 30-text holdout was prespecified but not run,
  since none passed the development gate. Production translation behavior and
  the installed 1.1.1 binary remain unchanged.

P0 now measures MT Latin-run survival separately from ASR recall and records
fixed, key-free Opus unmasked-fallback counts. Missing instrumentation is n/a.
It never guesses native clip-only target alignment. Seven additional regression
cases cover case/count changes, incomplete MT, scope, real warning propagation,
cached streaming callbacks and per-clip reset. The full suite passed **358 tests**.

A socket-blocked real bilingual controller replay at
`c0f519f3eb3d0e8149b95c536b6ec6f7ea6cdb41` verified the new report fields: EN → AR →
EN, two English pass-through rows, one MT request, one recorded Opus unmasked
fallback and one preserved Latin-run row (`Jerry`), with no pipeline errors.
It uses synthetic English plus public MSA; its protection result is not Saudi
acceptance. The earlier functional replay ran concurrently with the MT probe and
is not used for latency acceptance.

## Retained local artifacts

- Inputs/selection/scripts: `D:\CodexBuilds\Translito-quality\saudi-public-30-20261103`.
- Pinned model receipt: `D:\CodexBuilds\Translito-quality\codeswitch-public-20261102`.
- Balanced comparison: `D:\CodexBuilds\Translito-quality\saudi-public-30-bench\20261102T181237.779933Z`.
- Fast comparison: `D:\CodexBuilds\Translito-quality\saudi-public-30-fast-20261103`.
- Real MT outputs: `D:\CodexBuilds\Translito-quality\saudi-public-30-mt-20261103`.
- Rejected marker pilots/holdout: `marian-marker-pilot-20261103` and
  `marian-visible-span-pilot-20261103`, under the same build root.
- Instrumented controller: `D:\CodexBuilds\Translito-quality\mt-instrumented-bilingual\20261102T190159.544036Z`.

Primary Cohere/Gemma model access, configured/tested free cloud accounts, approved
paid-account allocation/winner selection and physical VB-CABLE acceptance remain
pending. These public fallback measurements do not waive those requirements.
