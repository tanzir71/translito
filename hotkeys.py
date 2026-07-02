from app_config import DEFAULT_HOTKEYS


class GlobalHotkeyManager:
    def __init__(self, callbacks, on_error=None):
        self.callbacks = callbacks
        self.on_error = on_error
        self._handles = []
        self._keyboard = None

    def register(self, hotkeys):
        self.unregister()
        try:
            import keyboard

            self._keyboard = keyboard
            for action, combo in (hotkeys or DEFAULT_HOTKEYS).items():
                combo = normalize_hotkey(combo)
                callback = self.callbacks.get(action)
                if combo and callback:
                    self._handles.append(keyboard.add_hotkey(combo, callback))
        except Exception as exc:
            if callable(self.on_error):
                self.on_error(str(exc))

    def unregister(self):
        if not self._keyboard:
            return
        for handle in self._handles:
            try:
                self._keyboard.remove_hotkey(handle)
            except Exception:
                pass
        self._handles = []


def normalize_hotkey(combo):
    return "+".join(
        part.strip().lower()
        for part in (combo or "").replace("-", "+").split("+")
        if part.strip()
    )


def format_tk_key_event(event):
    keysym = (getattr(event, "keysym", "") or "").lower()
    if keysym in {
        "shift_l",
        "shift_r",
        "control_l",
        "control_r",
        "alt_l",
        "alt_r",
        "menu",
    }:
        return ""
    state = int(getattr(event, "state", 0) or 0)
    parts = []
    if state & 0x0004:
        parts.append("ctrl")
    if state & 0x0008 or state & 0x20000:
        parts.append("alt")
    if state & 0x0001:
        parts.append("shift")
    key = keysym.replace("prior", "pageup").replace("next", "pagedown")
    if len(key) == 1 or key.startswith("f") or key in {"space", "tab", "escape"}:
        parts.append(key)
    elif key:
        parts.append(key)
    return normalize_hotkey("+".join(parts))
