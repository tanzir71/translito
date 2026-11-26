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
