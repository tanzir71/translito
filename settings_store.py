"""One process-wide, preserving settings writer per absolute config path."""
from copy import deepcopy
from pathlib import Path
import queue
import threading
import time

LOCK = threading.RLock()
_stores = {}


def _values(config):
    return {(section, key): value for section in config.sections() for key, value in config.items(section, raw=True)}


class SettingsStore:
    def __new__(cls, path=None, **kwargs):
        from app_config import _path
        path = _path(path).resolve()
        with LOCK:
            if path not in _stores:
                instance = super().__new__(cls)
                instance.path = path
                _stores[path] = instance
            return _stores[path]

    def __init__(self, path=None, *, writer=None, sleep=time.sleep):
        with LOCK:
            if hasattr(self, "config"):
                return
            from app_config import _read_config, _write_config
            self.config = _read_config(self.path)
            self.writer, self.sleep = writer or _write_config, sleep
            self.events, self.timer = queue.Queue(), None
            self.dirty, self.deleted, self.error = False, set(), ""
            self.revision = 0
            self.stamp = self._stamp()

    def _stamp(self):
        try:
            stat = self.path.stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None

    def read(self):
        with LOCK:
            if not self.dirty and self._stamp() != self.stamp:
                from app_config import _read_config
                self.config, self.stamp = _read_config(self.path), self._stamp()
            result = deepcopy(self.config)
            result._translito_baseline = _values(result)
            return result

    def update(self, changes, *, remove=(), delay=0, sync=False):
        with LOCK:
            changed = False
            for (section, key), value in changes.items():
                value = str(value)
                if self.config.get(section, key, fallback=None, raw=True) != value:
                    if any(c in section + key + value for c in "\r\n"):
                        raise ValueError("Multiline settings cannot be replaced; the existing config was preserved")
                    if section not in self.config:
                        self.config[section] = {}
                    self.config[section][key] = value
                    self.deleted.discard((section, key))
                    changed = True
            for section, key in remove:
                if self.config.remove_option(section, key) if self.config.has_section(section) else False:
                    self.deleted.add((section, key))
                    changed = True
            if not changed:
                return
            self.dirty = True
            self.revision += 1
            if self.timer:
                self.timer.cancel()
            if not sync:
                self.timer = threading.Timer(delay, self._write)
                self.timer.daemon = True
                self.timer.start()
        if sync:
            self._write()

    def commit(self, config):
        baseline = getattr(config, "_translito_baseline", {})
        current = _values(config)
        changes = {key: value for key, value in current.items() if baseline.get(key) != value}
        self.update(changes, remove=set(baseline)-set(current), sync=True)

    def _write(self):
        for attempt in range(6):
            try:
                with LOCK:
                    if not self.dirty:
                        return
                    config = deepcopy(self.config)
                    config._translito_deleted = set(self.deleted)
                    self.writer(config, self.path)
                    self.stamp, self.dirty, self.error = self._stamp(), False, ""
                    self.deleted.clear()
                    self.events.put(("saved", time.monotonic()))
                return
            except PermissionError:
                reason = "the settings file is locked"
                self.events.put(("retrying", reason))
                if attempt < 5:
                    self.sleep(.1 * 2**attempt)
                    continue
            except OSError:
                reason = "the settings folder could not be written"
            except ValueError:
                reason = "a setting could not be saved"
            self.error = reason
            self.events.put(("error", reason))
            return

    def flush(self):
        with LOCK:
            if self.timer:
                self.timer.cancel()
        self._write()

    def retry(self):
        with LOCK:
            self.dirty = True
        thread = threading.Thread(target=self._write, daemon=True)
        thread.start()

    def migrate(self, *, language_code=lambda value: value):
        from settings_schema import CONTROL_SCHEMA
        config, changes, remove = self.read(), {}, []
        if config.getboolean("MIGRATION", "settings_201", fallback=False):
            return
        for name, entry in CONTROL_SCHEMA.items():
            if not config.has_option("UI", name):
                continue
            value = config.get("UI", name, raw=True)
            remove.append(("UI", name))
            if name in {"offline_only", "engine_profile"}:
                continue
            if name in {"listen_source", "listen_target", "speak_source", "speak_target", "conversation_other", "my_language", "audience_language"}:
                value = language_code(value)
            if name == "quality":
                value = value.lower()
            changes[entry.section, entry.key] = value
        offline = any(config.get(section, key, fallback="0").lower() in {"1", "true"} for section, key in
                      (("UI", "offline_only"), ("RUNTIME", "offline_only")))
        profiles = {"Custom": "cloud", "Free (recommended)": "free", "Offline (private)": "local"}
        fresh = not any(config.has_section(s) for s in ("UI", "ENGINES", "LANGUAGE", "RUNTIME", "MIGRATION"))
        if fresh:
            changes["UI", "setup_offer_seen"] = "0"
        choice = profiles.get(config.get("UI", "engine_profile", fallback="")) or config.get("ENGINES", "engine_choice", fallback="") or ("local" if fresh or offline or
            config.get("ENGINES", "profile", fallback="free") == "offline" else "free")
        changes["ENGINES", "engine_choice"] = "local" if offline else choice
        changes["ENGINES", "profile"] = {"cloud": "custom", "local": "offline", "free": "free"}.get(changes["ENGINES", "engine_choice"], "free")
        changes["NETWORK", "block_all"] = config.get("NETWORK", "block_all", fallback="0")
        changes["MIGRATION", "settings_201"] = "1"
        remove.append(("RUNTIME", "offline_only"))
        from engines.settings import PROVIDERS
        for provider in PROVIDERS:
            prefix = provider.replace("-", "_") + "_"
            if config.has_option("ENGINES", prefix + "account_kind"):
                if config.get("ENGINES", prefix + "account_kind") == "unconfirmed" and config.get("ENGINES", prefix + "monthly_cap_usd", fallback="0") == "0":
                    changes["ENGINES", prefix + "monthly_cap_usd"] = ""
                remove.append(("ENGINES", prefix + "account_kind"))
        self.update(changes, remove=remove, sync=True)
