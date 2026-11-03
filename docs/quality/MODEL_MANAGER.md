# Local model management

Windows 1.1.3 adds **Settings → Speech recognition → Manage models…**. The old
Download Models shortcut now opens this manager. It has All models, Downloaded
and Available / partial filters, with model name, speech/translation purpose,
download status, disk use, storage location and the selected path.

Windows **1.1.5** fixes an action-row clipping bug in the initial layout.
**Download**, **Delete model…** and **Open folder** stay above the list, including
at 680×400. Select a downloaded model to enable Delete, then review its path and
confirm removal. See RELEASE_1_1_5.md for the layout regression checks.

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
- **Delete model…** confirms the model, cached-copy path and size, with
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
  configured transcript folder are protected. Transcript-folder protection is
  refreshed at deletion time if that setting changed. Arbitrary external Whisper model
  folders are visible but cannot be recursively deleted here. Closing the
  manager while a download runs does not leave the host's controls locked.

Cache sizes can include shared data; removing one copy does not necessarily
reclaim all displayed bytes if other cached models still reference those files.
The feature does not remove model files simply by opening the manager, and does
not enable cloud providers, alter model terms consent or delete transcripts.

## Verification

**394 tests passed**, one existing Torch JIT warning (41.34 seconds). Temporary
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
guard, including two regressions covering that change in activity. A separate
fixture changes the transcript folder after the manager opens and verifies that
its newly protected data is preserved.

One intervening run hit UsageUnavailable in an existing multiprocess usage-ledger
test while packaging was active. The targeted rerun passed (27 tests), followed
by the quiet full-suite pass above. No metering implementation was changed.

A read-only inventory on the owner's PC found 28 catalog/cache rows, including
app/shared Small copies and older original Whisper caches. No existing model
weights were downloaded or deleted during implementation; mutation tests used
temporary fixtures only. Audio-driver post-reboot acceptance and the earlier
Saudi quality/account work are separate and remain incomplete.

## Packaged and installed Windows build

The final 1.1.3 build uses source
`3535ce06d81207bd6ffff2a064877596fe4f22ab`, stage
`D:\CodexBuilds\Translito-quality\.p\4cd06a43\d\Translito`, retained artifacts
`D:\TranslitoReleases\1.1.3\build-02`. The earlier build-01 and interrupted
incremental build are retained and superseded.

The packaged-code inspection confirms the settings button, manager/backend and
Hugging Face cache API are included, along with both confirmation-time activity
checks and the deletion-time transcript-folder refresh. This is archive/code
inspection plus Tk widget tests, not a claim of deleting real owner models.

The installer exited **0** and installed ProductVersion **1.1.3**. Its EXE matches
the verified stage (SHA-256
`67a9b4dc5fe7873931897a51a715ed0c2226d6f432026e08229d50f971ad3211`).
The 1,804-byte settings file, all **nine** current original transcripts and usage
state match the fresh pre-upgrade baseline. All 160 prior runtime metadata files
match their retained copies in `runtime-history\20261103-132347`. No existing
model files were removed by the upgrade, and no restart was requested.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| TranslitoSetup-1.1.3.exe | 256,377,357 | `a0da5272aa1bac4392f36499d4b83b6fc7bf1c9d05e724ce26c0ea59d6891e9f` |
| TranslitoPortable-1.1.3.zip | 373,797,211 | `983bea676cd8799adc6dcb0aa1b5c42a7d4ccce78077c4f9faab5198bcda178d` |

Local receipts, final test output and the archive-inspection script are under
`D:\TranslitoReleases\1.1.3\validation-01`.

The initial 1.1.3 publication was blocked by GitHub API timeouts. It is superseded
by published [Windows 1.1.4](https://github.com/tanzir71/translito/releases/tag/v1.1.4),
which includes this manager, an installer disk-space guard and a frozen runtime
probe. See RELEASE_1_1_4.md for the later full-drive repair, installed checks and
preserved runtime archives. The landing links now target 1.1.4.
