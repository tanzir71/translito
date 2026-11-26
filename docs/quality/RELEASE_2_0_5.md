# Windows 2.0.5

Saved download failures no longer override models already available in the cache.
Startup and subsequent setup reconciliation use the model inventory to retire
obsolete paused/queued jobs, clear their old errors and show them as Ready.
Incomplete, corrupt and unverified files still require setup. Gated GGUF first-load
verification is preserved.

Startup renders saved jobs without replaying old error banners or model-ready
notifications. New failures notify once; Resume clears an owned download warning
without erasing unrelated hints. Unexpected setup failures retain a safe phase
and exception-class code, with actionable messages for blocked folders, disk
space and missing runtime components. No raw SDK URLs, credentials or paths are
included in these diagnostics.

The reported installed 2.0.4 executable matched the published build. All four
reported model jobs had complete cached inference files while their saved queue
records still showed failed/paused state. A copy of that real queue recovered all
four jobs to Ready offline with the corrected reconciliation.
The actual saved engine/language plan also reported no missing required or backup
models. The frozen GUI repeated the queue recovery with internet explicitly
blocked: all four jobs were Ready, the download panel was hidden, the hint was
empty and no Tk callback errors occurred.

Runtime verification now also exercises the Hugging Face dependency and native
TLS initialization used by model downloads. The existing macOS 1.0 DMG is
retained, and Windows signing is unchanged.

## Package checks

All 21 runtime checks passed. The portable archive passed full CRC verification;
every packaged file's size matches the staged runtime. All 20 checked production
modules and the importable GUI copy match the source. Bundled engine data and
VB-CABLE files match their sources. The release reuses the verified 2.0.4 native
runtime, rebuilding three Python modules; 9,748 Python modules and 15 archive
entries remain unchanged. No new module imports were introduced.

The final complete regression run passed **868 tests**, and the updated landing
page passed **64 checks**. Earlier runs during packaging hit child-startup timing
deadlines; the isolated worker recheck and the complete rerun after packaging
passed. The verified cached-job recovery also passed in the frozen GUI with
internet blocked.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.5.exe | 256,926,157 | `f623b3863a51c845e2e45ef022af484a3db68b8e3c3d9afafdef066f67534164` |
| TranslitoPortable-2.0.5.zip | 374,097,964 | `7115ad1a9a1667960a41ddcb53822c7af62f4d9a20aebc53a39001d155035efb` |
| Translito.dmg (retained 1.0) | 6,044,398 | `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73` |
