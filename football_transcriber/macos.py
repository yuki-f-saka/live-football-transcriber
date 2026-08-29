"""macOS-specific window tweaks via PyObjC (issue #6).

Qt's ``WindowStaysOnTopHint`` only keeps the overlay above windows in the
*same* Space. A fullscreen app (browser, video player) lives in its own Space,
so the subtitle bar disappears behind it. Cocoa's collection behaviour flags
fix this: ``CanJoinAllSpaces`` makes the window follow you to every Space and
``FullScreenAuxiliary`` lets it sit on top of fullscreen apps.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def make_visible_over_fullscreen(widget) -> bool:
    """Configure the NSWindow behind a shown QWidget to appear on all Spaces and
    above fullscreen apps. Returns False (and logs why) when PyObjC is missing.
    Must be called *after* ``widget.show()`` so the native window exists.
    """
    try:
        import objc
        from AppKit import (
            NSScreenSaverWindowLevel,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorIgnoresCycle,
            NSWindowCollectionBehaviorStationary,
        )
    except ImportError:
        log.warning("PyObjC not installed — overlay will not show over fullscreen apps "
                    "(pip install pyobjc-framework-Cocoa)")
        return False

    try:
        # QWidget.winId() is the NSView* on macOS; its window() is the NSWindow.
        view = objc.objc_object(c_void_p=int(widget.winId()))
        ns_window = view.window()
        if ns_window is None:
            log.warning("Native window not available yet; fullscreen overlay not applied")
            return False
        ns_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        # Above fullscreen apps and the menu bar; still click-through.
        ns_window.setLevel_(NSScreenSaverWindowLevel)
        ns_window.setIgnoresMouseEvents_(True)
        ns_window.setHidesOnDeactivate_(False)
        log.info("Overlay configured to show on all Spaces and over fullscreen apps")
        return True
    except Exception:
        log.exception("Failed to apply macOS fullscreen overlay behaviour")
        return False
