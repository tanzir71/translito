# Windows 1.1.0 release validation

The final build is installed, verified and
[published](https://github.com/tanzir71/translito/releases/tag/v1.1.0).
Phase PRs #5–#11 are merged; main's application tree matches release commit
`fa15ebc28eedd1935ca12cc33c8e20cac31cb1e2`. GitHub Pages
[deployment succeeded](https://github.com/tanzir71/translito/actions/runs/41471389984).

## Completed checks

- 286 Python tests pass. The added regression holds PortAudio reinitialization
  inside a fake blocked driver while the GUI caller returns; its completion is
  scheduled back on Tk. Idle refresh never requests a PortAudio reset.
- Native x64 process capture builds from checked-in source, with source/binary
  hashes, static CRT, ABI and notices. Own-tone INCLUDE/EXCLUDE and Stop passed.
- Build-time asset checks compare every engine-data file in the frozen app with
  its source. The first startup attempt caught missing `opus_pairs.json`; spec
  collection now uses an absolute source directory before package helpers run.
- Inno's first attempt hit a 279-character dependency-license path. Compact,
  unique staging and path checks fix this; existing output files remain intact.
- A rebuilt frozen EXE opened from `C:\Windows\System32` with engine data and
  version 1.1.0. The installer then compiled successfully using compact staging.
- The in-place upgrade exposed old `tokenizers`/Hugging Face distribution metadata
  beside the new packages, failing Transformers' startup version check. A fresh
  staged runtime works. The installer now archives the entire previous `_internal`
  directory intact under a unique `runtime-history` path, then installs a fresh
  runtime. It verifies absolute targets remain within the chosen app directory,
  refuses reparse points and preserves/restores backups on interruption where no
  replacement directory exists. The revised installer upgraded successfully,
  retained all 42 previous metadata files unchanged in its archive, and the
  installed app now opens normally. The failed earlier app never reached settings
  migration.
- The frozen app captured the public 8.16-second FLEURS Arabic clip from a selected
  Python process tree (wrapper PID 34444, rendering child 30988), displayed Arabic
  source followed by English Marian output, and returned to Ready on Stop. It
  saved a new 716-byte transcript in an isolated profile. This used cached local
  Whisper-small/Marian and the Offline profile, with no microphone or cloud key.
  Its fallback wording is weak; this is functional smoke evidence, not Saudi
  accuracy or latency acceptance.
- Runtime inspection of the installed older app found its Tk thread stuck in
  `sounddevice._initialize` during idle auto-refresh, with no capture/ASR/save
  worker. The release removes repeated resets from idle polling and runs manual
  reset on a background thread. The old idle process was closed only after this
  check. Original config bytes and hashes for all five existing transcript files
  are retained locally for post-install comparison.
- Hugo builds the prepared page; local HTTP serves it successfully and exposes
  both direct Windows 1.1.0 download links. Production links are not switched
  until release assets are verified. The old macOS DMG was obtained unchanged
  and its SHA-256 matches the existing release, preserving the latest-download
  URL when the new Windows release becomes latest.

## Release status and remaining acceptance

- The final idle-refresh build opens and remains responsive through normal
  device polling, with its installed copy and retained user data checked. The final
  staged build has already displayed Arabic and English from public playback,
  saved a new 701-byte transcript on Stop and stayed responsive under normal
  polling with preview mode disabled. The installed app's additive migration
  grows config from 427 to 1,782 bytes; every original byte/value is retained and
  all five original transcripts remain byte-identical. No real usage file was
  created. The app remains open with its existing source/model choices.
- All four release assets have matching local/server SHA-256 values and sizes.
  Installer, portable and latest macOS download URLs return HTTP 200. Both
  `localarabic.com` and the GitHub Pages route serve direct Windows 1.1.0 links.
- Physical VB-CABLE installation/tone routing and real meeting/browser sessions
  remain unverified. Driver consent, Windows prompts and any restart are user
  actions; the unattended app upgrade does not install the optional driver.
- Paid booster selection, live cloud accounts, gated Cohere/Gemma acceptance and
  Saudi quality targets remain outside the available evidence. Private Saudi
  evaluation clips were waived by the owner.

Release recheck also found that DeepL API Free is now a legacy plan. The current
adapter remains for existing Free keys; its new Developer lifetime trial is not
treated as a resetting monthly quota. The README documents this and recommends
Azure F0 for new free text setup. See `CLOUD_CONTRACTS.md` for primary references.

## Final artifacts

- Installer: `TranslitoSetup-1.1.0.exe`, 256,376,858 bytes,
  SHA-256 `df3a927fb8e0be930bfc9b13232baee11b67c375065096c1c97c704a53488a10`.
- Portable ZIP: `TranslitoPortable-1.1.0.zip`, 373,771,870 bytes,
  SHA-256 `bd520da8358c0e232380135041db2deef141640a0ac0f9d3aa8d0580e3460999`.
- Existing macOS DMG carried unchanged:
  SHA-256 `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73`.

The runtime/installer are CPU-only, with models downloaded separately. The silent
upgrade installed no optional driver and requested no reboot.
