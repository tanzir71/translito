# Windows 1.1.5 model action visibility

The owner reported that the model manager had no Delete option. Inspection of
the installed 1.1.4 window confirmed that the list consumed the available height
and pushed the entire action row below the visible window. The list and selected
model path were visible, while Download, Delete and Open folder were clipped.

Version 1.1.5 places **Download**, **Delete model…** and **Open folder** in a fixed
row above the model list. A weighted grid lets only the list absorb changes in
height. The dialog supports 680×400 windows, chooses a smaller default on short
screens, and centering keeps it within the desktop even when its parent is near
an edge. Deletion still requires selecting a cached model, an idle session and
explicit confirmation of the model/path. No owner model is removed by this fix.

The full suite passed: **406 tests**, one existing Torch JIT deprecation warning
(56.82 seconds). Regression tests map the actual Tk widgets at 680×400 and
900×580, select a downloaded temporary fixture and verify that the enabled Delete
button and all other actions remain fully inside the window above the list.
Three edge-position cases verify that centering keeps dialogs on screen.

Production source: `3a7d44daf1dbc406ba30f1446984e6e9d245aeec`.
Build and validation receipts are retained under
`D:\TranslitoReleases\1.1.5`.

The existing installer space guard and frozen dependency/CPU probe are retained.
This layout fix does not establish Saudi speech accuracy, post-reboot physical
VB-CABLE routing or cloud-account acceptance.
