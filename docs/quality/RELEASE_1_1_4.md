# Windows 1.1.4 runtime repair

The startup dialog reported WinError 126 for `torch/lib/shm.dll`. A comparison
against the retained 1.1.3 build found just one missing installed file:
`torch/lib/torch_cpu.dll` (305,081,856 bytes). Its dependent DLLs matched the
build. C: had zero free bytes, and another runtime archive recorded a subsequent
installation after the earlier successful upgrade. No matching Windows Defender
detection event was found in the preceding two days.

The missing DLL was restored with an NTFS hard link to the identical preserved
runtime copy after verifying its SHA-256 against the retained build. Fresh
native loads of `c10.dll`, `torch_cpu.dll`, `shm.dll` and `torch_python.dll` passed.
The DLL SHA-256 is
`ac7cfa1b31556e7ae60381ad4bd9df4286a4f82738c3120045c6a7803aab5fe5`.

Two older runtime archives (`20261102-210737`, `20261102-234438`) were relocated
from the installation's runtime-history directory to
`D:\TranslitoRuntimeHistory`. All 13,311 files passed size and SHA-256 checks
after relocation. This recovered about 1.8 GB on C: without removing models,
settings or transcripts. The other runtime archives were retained in place.

## Prevention and verification

- The installer measures the complete packaged app and requires that amount
  plus 256 MiB free before archiving the previous runtime. The normal overwrite
  estimate cannot count retained runtime files as reclaimed space.
- Builds run the actual frozen EXE in `--check-runtime` mode before producing
  either downloadable artifact. The offline probe imports the required native
  dependencies, resolves Transformers' lazy pipeline and executes a CPU tensor
  calculation. It does not open the GUI, capture audio or download models.
- Frozen startup errors direct users to check disk space and repair with the
  Windows installer. Source development retains its pip instructions.
- The full suite passed: **401 tests, one existing Torch JIT deprecation warning**.
  Tests include failed import reporting, report preservation and packaged repair
  guidance. Existing model-manager tests continue to pass.

Production source revision: `4ea8f0f68ab5b4c7ea1350ef75a1b3c57a3aaad3`.
Build, upgrade and test receipts are retained under
`D:\TranslitoReleases\1.1.4`.

The frozen EXE passed all eight dependency probes, including Torch 2.13.0+cpu,
Transformers 5.22.1 and the CPU calculation. A separate fixture used hard links
to the frozen files but omitted `torch_cpu.dll`. That EXE returned **1**, recorded
the expected WinError 126 and left the production stage intact. The fixture and
JSON receipts remain on D:; this check did not remove an installed DLL.

The landing page built successfully with Hugo, and its rendered Windows 1.1.4
installer/portable links and unchanged latest macOS link were checked locally.

## Installed build

The installer exited **0**, installed ProductVersion **1.1.4** and requested no
restart. The installed EXE's offline runtime check exited **0**. The main window
opened normally to **Ready**, and Settings opened and closed without starting
audio capture or changing controls.

All **6,395** packaged files matched the production stage by SHA-256. Settings,
all **nine** original transcripts and usage state remained unchanged; all
**6,391** previous runtime files matched their retained copies in
`runtime-history\20261103-162542`.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| TranslitoSetup-1.1.4.exe | 256,366,311 | `4b55729e6b542446bd7336dc82acc85302e502bf9991ea76ed7fd272ab993c62` |
| TranslitoPortable-1.1.4.zip | 373,799,645 | `031b1794ffb8787d0eeb681d7ca261e054beeb941de716e1f76f92900b1e36c8` |

The portable ZIP passed its CRC integrity check and includes the complete
305,081,856-byte `torch_cpu.dll`. Installed EXE SHA-256:
`524347e523b0e78450e5f072a1daef41bdd708d1443b6f1e2f4a89d987f27107`.

This release also includes the model manager and Windows audio COM changes from
the pending 1.1.2/1.1.3 branches. It does not establish Saudi speech accuracy,
physical VB-CABLE routing after reboot or real cloud-account acceptance.
