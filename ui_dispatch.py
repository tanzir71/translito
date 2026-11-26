"""Background producers enqueue callbacks; only Tk's main loop executes them."""
def post(owner, callback):
    if hasattr(owner, "_ui_events"):
        owner._ui_events.put(callback)
    else:
        # Headless controller tests inject a synchronous fake root.
        owner.root.after(0, callback)
