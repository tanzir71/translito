# Local model management

Windows 1.1.3 adds **Settings → Speech recognition → Manage models…**. The old
Download Models shortcut now opens this manager. It has All models, Downloaded
and Available / partial filters, with model name, speech/translation purpose,
download status, disk use, storage location and the selected path.

The catalog covers the supported Whisper CT2 sizes (including the base LID
model), Arabic/English code-switch fallback, Cohere Arabic, TranslateGemma 4B
and verified Lite translation pairs. It also discovers cached original OpenAI
Whisper and other Opus models left by earlier versions. Each existing cache copy
has its own row, so removing an app cache does not remove a shared-cache copy.
Inventory reads current app configuration and standard/configured Hugging Face
caches without network calls. It does not scan every drive or arbitrary folders.

## Downloads and deletion

- **Download** fetches inference files for the selected public model without
  implicit HF login or loading the model into RAM. Translation downloads prefer
  safetensors when available instead of downloading both weight formats. Offline
  mode blocks downloads. Cohere/Gemma use the existing setup windows, preserving
  explicit terms/token consent and Gemma's integrity/RAM checks.
- **Delete cached files…** confirms the model, cached-copy path and size, with
  an additional shared-cache notice. All revisions of that selected repository
  copy are removed via the installed Hugging Face cache API; its shared-blob
  reference checks retain files still used elsewhere. Interrupted downloads
  without a complete revision can also be removed. Gemma deletion removes only
  the selected GGUF/partial file, preserving neighboring models and notes.
- Active sessions and concurrent model loads block mutation. Idle model
  references are released before file deletion; a maintenance gate prevents a
  preload from racing it. Automatic GUI preloading also respects the busy state.
  The next session reloads its needed model, or needs a new download if removed.
- Recursive targets are checked as absolute descendants of their known cache
  root, with Windows junction/symlink-directory checks. Settings, usage and the
  configured transcript folder are protected. Arbitrary external Whisper model
  folders are visible but cannot be recursively deleted here. Closing the
  manager while a download runs does not leave the host's controls locked.

Cache sizes can include shared data; removing one copy does not necessarily
reclaim all displayed bytes if other cached models still reference those files.
The feature does not remove model files simply by opening the manager, and does
not enable cloud providers, alter model terms consent or delete transcripts.

## Verification

**391 tests passed**, one existing Torch JIT warning (37.27 seconds). Temporary
cache fixtures exercise local/shared duplicate copies, partial downloads,
protected paths, selected-file GGUF deletion, cross-model revision collisions,
legacy cache discovery, offline/terms gates, anonymous download arguments,
single-format translation weights and SDK error redaction. Thread tests cover
maintenance versus model loading and cleanup after failure. Tk widget tests
cover filters, displayed sizes, confirmation cancellation, active/busy/preview
guards and the gated setup route. The Tk tests share a hidden root to avoid a
transient display-creation skip seen in the first full run.

A final confirmation-time recheck prevents deletion if a session/model operation
starts while the dialog is open. All **nine focused UI tests pass** after this
guard, including two regressions covering that change in activity.

A read-only inventory on the owner's PC found 28 catalog/cache rows, including
app/shared Small copies and older original Whisper caches. No existing model
weights were downloaded or deleted during implementation; mutation tests used
temporary fixtures only. Audio-driver post-reboot acceptance and the earlier
Saudi quality/account work are separate and remain incomplete.
