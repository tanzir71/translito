"""Atomic replacement tolerating brief Windows scanner sharing locks."""
import time


def atomic_replace(source, target):
    for attempt in range(6):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(.01 * 2 ** attempt)
