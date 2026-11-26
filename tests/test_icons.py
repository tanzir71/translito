from pathlib import Path

from PIL import Image

from tools.build_icons import ICO_SIZES, TRAY_SIZES, build_windows, mark, tray_frame, contact_sheet

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
            assert frame.convert("RGBA").tobytes() == mark(size).tobytes()
        for state in ("idle", "listening", "paused"):
            tray = Image.open(root / f"engines/data/tray/{state}.ico")
            assert tray.ico.sizes() == {(n,n) for n in TRAY_SIZES}
            for size in TRAY_SIZES:
                assert tray.ico.getimage((size,size)).convert("RGBA").tobytes() == tray_frame(size,state).tobytes()
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


def test_native_window_icons_use_dpi_metrics_and_wm_seticon():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from ui_theme import apply_window_icon
    api = SimpleNamespace(GetDpiForSystem=lambda: 144, GetSystemMetricsForDpi=Mock(side_effect=lambda metric,dpi: 48 if metric in {11,12} else 24),
        GetParent=lambda handle: 100, LoadImageW=Mock(side_effect=[201,202]), SendMessageW=Mock(), DestroyIcon=Mock())
    window = SimpleNamespace(winfo_id=lambda: 1, iconbitmap=Mock(), bind=Mock())
    apply_window_icon(window, user32=api, path=ROOT/"installer/Translito.ico")
    assert [(c.args[3],c.args[4]) for c in api.LoadImageW.call_args_list] == [(48,48),(24,24)]
    assert [c.args for c in api.SendMessageW.call_args_list] == [(100,0x80,1,201),(100,0x80,0,202)]
    assert all(c.args[1] == 144 for c in api.GetSystemMetricsForDpi.call_args_list)


def test_tray_asks_for_the_exact_small_icon_and_falls_back_when_private_api_is_missing():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from windows_icons import tray_icon_class
    class Backend:
        def _assert_icon_handle(self):
            self.fallback = True
    api = SimpleNamespace(GetDpiForSystem=lambda:120, GetSystemMetricsForDpi=lambda metric,dpi:20,
                          LoadImageW=Mock(return_value=900))
    cls = tray_icon_class(Backend,user32=api,directory=ROOT/"engines/data/tray")
    icon = cls()
    icon._icon_handle = None
    icon._assert_icon_handle()
    assert icon._icon_handle == 900
    assert api.LoadImageW.call_args.args[3:5] == (20,20)
    assert api.LoadImageW.call_args.args[1].endswith("idle.ico")
    assert tray_icon_class(object,user32=api) is object


def test_shared_shell_identity_no_tray_iconphoto_and_contact_sheet(tmp_path):
    from app_identity import APP_USER_MODEL_ID
    include = (ROOT/"installer/app_identity.iss").read_text()
    assert f'"{APP_USER_MODEL_ID}"' in include
    installer = (ROOT/"installer/Translito.iss").read_text()
    assert installer.count('AppUserModelID: "{#AppUserModelID}"') == 2
    assert "iconphoto" not in (ROOT/"gui.py").read_text(encoding="utf-8")
    path = contact_sheet(tmp_path)
    assert path.is_file() and Image.open(path).size == (720,390)
