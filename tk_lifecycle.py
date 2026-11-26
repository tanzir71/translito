"""Keep Tcl finalizers on the UI thread while background workers allocate."""
import gc
import threading

_ui_active = False
_collection_requested = threading.Event()


def collect_on_ui():
    if _ui_active and threading.current_thread() is not threading.main_thread():
        _collection_requested.set()
    else:
        gc.collect()


def confine_tk_collection(root):
    global _ui_active
    _ui_active = True
    # Tk Variables make Tcl calls from __del__. Python's automatic cyclic GC
    # can run in a download/settings worker, so the Tk loop owns collection.
    gc.disable()
    ticks = [0]
    def collect():
        if not root.winfo_exists():
            return
        ticks[0] += 1
        if _collection_requested.is_set() or ticks[0] % 20 == 0:
            _collection_requested.clear()
            gc.collect(2)
        else:
            gc.collect(0)
        root.after(500, collect)
    root.after(500, collect)
