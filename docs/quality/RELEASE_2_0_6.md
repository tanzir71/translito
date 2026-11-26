# Windows 2.0.6

Browsing an unconnected cloud provider no longer replaces the saved route. A
successful primary-provider connection saves recognition and translation together,
matching the route described in the picker. Soniox uses native translation;
ElevenLabs and Speechmatics use local translation. The inline and advanced
connection windows share route activation. Rechecking an active key preserves
custom translation stages. Pair-specific activation retains other pairs and
global defaults.

Cancel stops every unfinished attempt for the same model, clears its warning and
dismisses the main progress controls. Historical Ready jobs cannot resurrect a
cancelled request during setup reconciliation. Partial files remain resumable in
Models. Already cancelled rows offer Resume without a redundant Cancel action;
the optional Gemma dialog also supports Resume after cancellation.

Cache checks retry transient filesystem failures before the queue's existing
bounded backoff. Complete caches skip unnecessary free-space checks, and file
size sampling tolerates concurrent renames. Remaining failures retain the exact
operation, errno and Windows error number without paths, tokens or SDK URLs.

## Reported installation

The saved route selected ElevenLabs and DeepL without configured keys, while the
Soniox key was present and matched its tested fingerprint. The route on the
reported PC was corrected to Soniox for both stages. A live metadata check passed;
the session plan admitted Start and the runtime factory constructed Soniox with
native translation. No audio was sent by this check.

Two instrumented download workers in the installed GUI completed successfully.
The previously recorded `check_cache:OSError` was intermittent and did not recur
under instrumentation; its exact Windows cause has not been established. The
new retries, complete-cache path and precise diagnostics address the observed
failure boundary without claiming an unobserved root cause.

## Verification

The full regression run passed **878 tests**. A subsequent run of the final UI
passed **37 checks**, including the added advanced-provider connection case and
the final picker synchronization. All **21 frozen runtime checks** passed.

The build reuses the verified 2.0.5 native runtime, rebuilding eight Python
modules. The other 9,743 Python modules and 15 archive entries are unchanged.
New imports resolve to modules already bundled in that runtime.

Frozen application and package results are recorded with the release artifacts.
Checks cover provider browsing, both connection windows,
existing-key rechecks, pair scope, Cancel, duplicate history, retryable cache
errors and complete-cache behavior. The native dark theme and window dimensions
are unchanged. Windows signing is unchanged; the macOS 1.0 DMG is retained.

A fresh-cache Whisper Base transfer completed in the actual frozen executable,
with 17 progress samples, Pause/Resume and Cancel/Resume. Cancel remained stopped
through setup reconciliation before explicit Resume. The final files passed
verification. The frozen GUI used the real credential vault with a private copy
of the reported configuration: Start was admitted with Soniox, browsing two
unconnected providers retained Soniox, and Cancel cleared the warning and hid
the main progress panel. No meeting audio was sent during these checks.

The landing page passed **64 checks** with the updated 2.0.6 download links.

The portable archive passed full CRC verification. Every staged file's size
matches the archive, all 22 checked production modules and the importable GUI
match the source, and bundled engine data and VB-CABLE resources match their
sources. Both Windows binaries report version 2.0.6 and remain unsigned.
The release source commit is `8ca09c7996d4794ccbe3b8c4cdd19a93f91c1645`.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.6.exe | 256,935,161 | `e307f70dd86fcb6d68e61669d337a0e481759a8763d2fd6bb22919386b9e8145` |
| TranslitoPortable-2.0.6.zip | 374,102,265 | `ecb9e763efb6343bc413acee019c6fdf63e00584b03c2a6152ada5c672164e83` |
| Translito.dmg (retained 1.0) | 6,044,398 | `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73` |
