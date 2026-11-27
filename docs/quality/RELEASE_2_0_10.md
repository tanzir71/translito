# Windows 2.0.10

Desktop captions keep the existing previous/current translation flow: the older
translation is grey and smaller, and the current translation is white at the
configured text size. Original-language text remains optional and off by default,
including source drafts before the first translation.

Long captions now wrap and scroll inside a window bounded to the selected
monitor work area. New text follows the latest line; periodic refreshes preserve
a reader's manual scroll. The window also fits when reply cards or hover controls
appear, on smaller displays and monitors with negative coordinates. Caption and
dialog monitor APIs no longer share mutable ctypes function signatures.

Reply suggestions expose a visible manual action after speech arrives, explain
the question-triggered automatic mode, and request suggestions when enabled with
existing context. A new source row no longer discards an in-flight request or its
results. Background requests snapshot settings on the UI thread, isolate their
provider events from the live caption engine, and fall back to free quick replies
when an optional reply provider is unavailable. Pending requests stay visible;
completed suggestions respect the normal caption fade setting.

Model inspection and inventory use the same Windows snapshot-link repair as the
downloader. Valid immutable Hugging Face blob links become regular hard links
without downloading or copying weights during inspection. Access failures are
reported separately from damaged metadata; a runtime load failure no longer
permanently marks a model corrupt. Ready files take priority over stale download
job errors. Inventory avoids scanning unrelated shared snapshots through the SDK.
All seven existing cached models on the verification machine reported Ready with
Windows RedirectionGuard enabled after the repair.

The installer removes recognized obsolete packaged runtimes after a successful
upgrade and on uninstall. Cleanup stays within this installation's runtime-history
folder, leaves unknown files alone, and does not follow links into external data.
Settings, credential storage, transcripts and shared model caches retain their
locations. Upgrade/uninstall/reinstall behavior was checked in a private
installation with a unique AppId; the user's running installation was untouched.

The cloud language-filter default now matches the existing opt-in behavior;
explicitly saved choices remain effective. Downloads still use the existing
pause, resume and cancel implementation, with cache-link repair shared across
readers and download workers.

The Windows packages remain unsigned. The macOS 1.0 DMG is retained.

Verification passed 822 application checks and 64 landing-page checks. A further
77 focused UI checks passed against the final caption/reply changes. The frozen
Windows build passed all 21 dependency checks. Its real Soniox run used only the
bundled public Arabic sample, produced a translation in 15.85 seconds without
loading local speech models, returned from Stop in 0.23 seconds and reached Ready
in 2.39 seconds while packaging was running. The same build rendered three quick
replies, preserved them across a new source row, kept long captions scrollable
inside a 720 by 480 pixel window, and reported all seven cached models Ready under
Windows RedirectionGuard. No customer audio was captured and no Tk callback
errors occurred.

Eight embedded application modules were rebuilt; 9,743 other PYZ modules and 14
root archive entries retained their bytecode. The native runtime was retained
from the verified Windows dependency build.

The portable ZIP passed a full CRC check and all staged file-size checks. All
31 inspected module entries (including both GUI entry points and every changed
module) match source. Bundled engine data and VB-CABLE resources match source.

The final download suite passed 29 checks in 29.03 seconds, for 915 application,
download and landing-page checks overall. During concurrent installer compilation,
earlier runs exceeded the existing child timeout or UI heartbeat threshold. The
final download run used a byte-identical source copy on C: after compilation;
source and test thresholds were unchanged.

Both Windows executable version resources report 2.0.10 and Authenticode reports
NotSigned. The installer compiled successfully and passed the isolated lifecycle
checks. Source commit: `f3eb55348c59f35e03a3d681d45a93a642347e9f`.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.10.exe | 256,960,457 | `be7b6141c18f25e02c9d4158cc9e02c2c412b1ee6b0db5f157f5a8c23fed7586` |
| TranslitoPortable-2.0.10.zip | 374,116,888 | `ade11bf4895a454857407b38a985dc23a4dff257ed2027d268f8c91589440f07` |
