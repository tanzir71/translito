"""Shared dark input and Windows chrome styling, including readonly states."""
import sys
from windows_icons import apply_window_icon


def button_style(style, name, colors, normal, hover, pressed, *, foreground="text",
                 hover_foreground=None, disabled="surface", **options):
    """Map every clam paint option; disabled wins over pointer states."""
    c = colors
    states = [("disabled", c[disabled]), ("pressed", "!disabled", c[pressed]),
              ("active", "!disabled", c[hover])]
    style.configure(name, background=c[normal], foreground=c[foreground],
                    bordercolor=c["border"], lightcolor=c[normal], darkcolor=c[normal],
                    focuscolor=c["blue"], relief="flat", padding=(12, 6), **options)
    style.map(name, **{key: states for key in ("background", "lightcolor", "darkcolor")},
              foreground=[("disabled", c["tertiary"]),
                          ("active", "!disabled", c[hover_foreground or foreground]),
                          ("!disabled", c[foreground])],
              bordercolor=[("focus", "!disabled", c["blue"]),
                           ("!disabled", c["border"])],
              focuscolor=[("!disabled", c["blue"])])


def apply_theme(root, style, colors):
    """One shared theme for the application and its Toplevel dialogs."""
    try:
        style.theme_use("clam")
    except Exception:
        pass
    c = colors
    root.option_add("*Font", "{Segoe UI} 10")
    input_styles(root, style, c)
    root.after_idle(lambda: (dark_titlebar(root), apply_window_icon(root)))
    root.bind("<Map>", lambda event: apply_window_icon(root) if event.widget is root else None, add="+")
    for key, value in (("background", c["field"]), ("foreground", c["text"]),
                       ("selectBackground", c["blue"]), ("selectForeground", c["on_accent"])):
        root.option_add(f"*TCombobox*Listbox.{key}", value)
    for name, background in (("TFrame", "bg"), ("Dark.TFrame", "bg"), ("Surface.TFrame", "surface")):
        style.configure(name, background=c[background])
    for name, background, foreground in (("TLabel", "bg", "text"), ("Dark.TLabel", "bg", "text"),
            ("Secondary.TLabel", "bg", "secondary"), ("Surface.TLabel", "surface", "text"),
            ("SurfaceSecondary.TLabel", "surface", "secondary")):
        style.configure(name, background=c[background], foreground=c[foreground])
    for name in ("TButton", "Mac.TButton", "Icon.TButton"):
        button_style(style, name, c, "surface_2", "field", "border")
    for name, normal, hover in (("Primary.TButton", "blue", "blue_hover"), ("Stop.TButton", "red", "red_hover")):
        button_style(style, name, c, normal, hover, normal, foreground="on_accent", disabled="field")
    button_style(style, "SegmentActive.TButton", c, "field", "field", "field")
    button_style(style, "SegmentInactive.TButton", c, "surface", "surface_2", "field",
                 foreground="secondary", hover_foreground="text")
    for name in ("TCheckbutton", "TRadiobutton", "Treeview.Heading", "Models.Treeview.Heading", "Terms.Treeview.Heading"):
        button_style(style, name, c, "surface", "surface_2", "field", foreground="secondary", hover_foreground="text")
        style.map(name, indicatorbackground=[("disabled", c["surface"]), ("selected", c["blue"]), ("!selected", c["field"])])
    for name in ("Treeview", "Models.Treeview", "Terms.Treeview"):
        style.configure(name, background=c["field"], fieldbackground=c["field"], foreground=c["text"], rowheight=34)
        style.map(name, background=[("selected", c["blue_bg"])], foreground=[("selected", c["text"])])
    for axis in ("Vertical", "Horizontal"):
        for name in (f"{axis}.TScrollbar", f"Dark.{axis}.TScrollbar"):
            button_style(style, name, c, "field", "border", "tertiary")
            style.configure(name, troughcolor=c["bg"], arrowcolor=c["text"], borderwidth=0, arrowsize=10)
    for name in ("Horizontal.TProgressbar", "Dark.Horizontal.TProgressbar"):
        button_style(style, name, c, "blue", "blue", "blue", foreground="on_accent")
        style.configure(name, troughcolor=c["field"], background=c["blue"], foreground=c["on_accent"],
                        bordercolor=c["field"], lightcolor=c["blue"], darkcolor=c["blue"])


def input_styles(root, style, colors):
    for widget in ("Entry", "Spinbox", "Text", "Listbox"):
        for option, value in (("background", colors["field"]), ("foreground", colors["text"]),
                              ("selectBackground", colors["blue"]), ("selectForeground", colors["on_accent"]),
                              ("insertBackground", colors["text"]), ("highlightBackground", colors["border"]),
                              ("highlightColor", colors["blue"]), ("disabledBackground", colors["surface"]),
                              ("disabledForeground", colors["tertiary"]), ("readonlyBackground", colors["field"])):
            root.option_add(f"*{widget}.{option}", value)
    for name in ("TEntry", "TCombobox", "TSpinbox", "Dark.TEntry", "Dark.TCombobox"):
        style.configure(name, fieldbackground=colors["field"], background=colors["field"],
            foreground=colors["text"], insertcolor=colors["text"], arrowcolor=colors["secondary"],
            bordercolor=colors["border"], lightcolor=colors["border"], darkcolor=colors["border"], padding=6)
        style.map(name,
            background=[("disabled", colors["surface"]), ("!disabled", colors["field"])],
            bordercolor=[("focus", "!disabled", colors["blue"]), ("active", "!disabled", colors["tertiary"]), ("!disabled", colors["border"])],
            fieldbackground=[("disabled", colors["surface"]), ("readonly", colors["field"]), ("!disabled", colors["field"])],
            foreground=[("disabled", colors["tertiary"]), ("!disabled", colors["text"])],
            selectbackground=[("!disabled", colors["field"])], selectforeground=[("!disabled", colors["text"])])


def dark_titlebar(window, *, dwm=None, user32=None):
    if sys.platform != "win32" and dwm is None:
        return
    import ctypes
    try:
        dwm = dwm or ctypes.windll.dwmapi
        user32 = user32 or ctypes.windll.user32
        handle = user32.GetParent(window.winfo_id()) or window.winfo_id()
        for attribute, value in ((20, 1), (35, 0x1f1f1f), (36, 0xf5f3f3)):
            number = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(handle, attribute, ctypes.byref(number), ctypes.sizeof(number))
    except (AttributeError, OSError):
        pass  # Older Windows versions retain their system chrome.
