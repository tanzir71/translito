from pathlib import Path

from PIL import Image

from tools.build_icons import ICO_SIZES, build_windows

ROOT = Path(__file__).resolve().parents[1]


def assert_transparent(image):
    image = image.convert("RGBA")
    w, h = image.size
    assert all(image.getpixel(p)[3] == 0 for p in ((0, 0), (w-1, 0), (0, h-1), (w-1, h-1)))
    assert image.getchannel("A").getextrema() == (0, 255)


def test_generated_windows_and_web_assets(tmp_path):
    build_windows(tmp_path)
    for root in (ROOT, tmp_path):
        icon = Image.open(root / "installer/Translito.ico")
        assert icon.ico.sizes() == {(n, n) for n in ICO_SIZES}
        for size in ICO_SIZES:
            frame = icon.ico.getimage((size, size))
            assert frame.size == (size, size)
            assert_transparent(frame)
        for size in (32, 64):
            for state in ("idle", "listening", "paused"):
                image = Image.open(root / f"engines/data/tray/{state}-{size}.png")
                assert image.size == (size, size)
                assert_transparent(image)
        web = Image.open(root / "website/static/translito-icon.png")
        assert web.size == (512, 512)
        assert_transparent(web)


def test_tray_image_changes_with_session_and_budget_state():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from gui import TranslatorGUI
    tray = SimpleNamespace(icon=None, update_menu=Mock())
    app = SimpleNamespace(tray_icon=tray, tray_images={s: object() for s in ("idle", "listening", "paused")},
                          current_status="Ready", transcriber=None)
    for status, session, state in (("Ready", None, "idle"), ("Listening", object(), "listening"),
                                   ("Budget reached", object(), "paused")):
        app.current_status, app.transcriber = status, session
        TranslatorGUI.refresh_tray_menu(app)
        assert tray.icon is app.tray_images[state]


def test_macos_assets_have_transparent_margins():
    assets = ROOT / "native_macos/DesktopAudioTranslator/DesktopAudioTranslator/Assets.xcassets/AppIcon.appiconset"
    for path in [ROOT / "native_macos/branding/Translito-AppIcon-1024.png", *assets.glob("*.png")]:
        icon = Image.open(path)
        assert_transparent(icon)
        assert icon.getpixel((icon.width // 2, 0))[3] == 0
    icon = Image.open(ROOT / "native_macos/branding/Translito.icns")
    for size in icon.info["sizes"]:
        assert_transparent(icon.icns.getimage(size))
