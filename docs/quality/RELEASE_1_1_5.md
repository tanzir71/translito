# Windows 1.1.5 model action visibility

The owner reported that the model manager had no Delete option. Inspection of
the installed 1.1.4 window confirmed that the list consumed the available height
and pushed the entire action row below the visible window. The list and selected
model path were visible, while Download, Delete and Open folder were clipped.

Version 1.1.5 places **Download**, **Delete model…** and **Open folder** in a fixed
row above the model list. A weighted grid lets only the list absorb changes in
height. The dialog supports 680×400 windows, chooses a smaller default on short
screens, and centering clamps requested coordinates to the desktop bounds.
Deletion still requires selecting a cached model, an idle session and
explicit confirmation of the model/path. No owner model is removed by this fix.

The full suite passed: **406 tests**, one existing Torch JIT deprecation warning
(56.82 seconds). Regression tests map the actual Tk widgets at 680×400 and
900×580, select a downloaded temporary fixture and verify that the enabled Delete
button and all other actions remain fully inside the window above the list.
Three edge-position cases verify that centering keeps dialogs on screen.

## Installed and published build

The installer exited **0**, installed ProductVersion **1.1.5**, and requested no
restart. The installed native dependency/CPU probe exited **0**. All **6,395**
packaged files matched the stage by SHA-256. Settings, all **nine** transcripts
and usage state remained unchanged; all **6,391** previous runtime files match
their retained copies in `runtime-history\20261103-165242`.

The actual installed GUI opened to Ready. Settings → Speech recognition →
Manage models opened the new action row above the list. After positioning the
dialog fully on screen and selecting the downloaded Whisper tiny cache, the
**Delete model…** button was visibly enabled. The manager was left open for the
owner; no delete action or confirmation was invoked. The native check verifies
action visibility, while the desktop-edge coordinate checks above are unit tests.

Three older archives (`20261103-022508`, `20261103-132347`, `20261103-144904`)
were moved intact to `D:\TranslitoRuntimeHistory` to make room for the upgrade.
All **19,173** files passed size and SHA-256 verification after relocation.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| TranslitoSetup-1.1.5.exe | 256,397,816 | `9c0270743879f2a817d3569699b0554706ddfdb66e23e4cd47a5fd16c204f638` |
| TranslitoPortable-1.1.5.zip | 373,799,213 | `60d99f99c3873077d07c934d4dc461f7f050bd140c3c231b86f16c51f7428f90` |

Installed EXE SHA-256:
`68b29d1926aec85393b6bdbcd48b7dac375d69467d5a683e03a3a9bc3c006fd0`.
The portable ZIP passed its CRC integrity check. The frozen EXE runtime probe
also passed before packaging.

[Windows 1.1.5](https://github.com/tanzir71/translito/releases/tag/v1.1.5) is
published as latest. All four uploaded asset sizes/SHA-256 digests match local
files, including the unchanged macOS DMG and SHA256SUMS.txt. Its tag targets
`f7f8fa3255f4ae8618972e55565ed61ee64e4cc0`; production code is unchanged from
the source below. Landing links and the Pages workflow target 1.1.5.

Production source: `3a7d44daf1dbc406ba30f1446984e6e9d245aeec`.
Build and validation receipts are retained under
`D:\TranslitoReleases\1.1.5`.

The existing installer space guard and frozen dependency/CPU probe are retained.
This layout fix does not establish Saudi speech accuracy, post-reboot physical
VB-CABLE routing or cloud-account acceptance.
