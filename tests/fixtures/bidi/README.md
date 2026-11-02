# Windows Tk bidi reference

`windows-tk-bilingual.jpg` was captured from the actual Windows Tk app's
development preview on 2026-11-02, after visual verification. It contains only
synthetic test sentences. It is a manual rendering regression reference, not
an exact-pixel assertion across different Windows fonts/DPI settings.

- EN source: `The API works. Check the deployment dashboard.` No duplicate
  translation line should appear.
- MIX source: `هخلص ال deployment بعد ال meeting`. The Arabic words read right
  to left, and `deployment`/`meeting` remain intact Latin words.
- AR source: `هذه جملة عربية فيها API حتى نراجع ترتيب الكلمات.`

Tk showed FSI/PDI as visible missing-glyph boxes. Applying bidi ordering without
Arabic shaping reversed the letters inside words. The verified fallback shapes
Arabic first with `arabic-reshaper`, resolves isolates with `python-bidi`, removes
isolate controls from the display copy, and right-aligns Arabic-matrix rows.
The EN/AR/MIX badge, raw source and translated text are separate widgets.

`test_bidi_display.py` covers display-only isolation and Latin-term retention;
`test_transcript_preservation.py` verifies saved files retain logical raw text.
Neither test alone establishes correct glyph rendering: use this screenshot
and a real Windows preview when changing fonts, bidi code or transcript labels.
