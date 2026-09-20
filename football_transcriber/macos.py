"""macOS-specific window tweaks via PyObjC (issues #6, #33).

Qt's ``WindowStaysOnTopHint`` only keeps the overlay above windows in the
*same* Space. A fullscreen app (browser, video player) lives in its own Space,
so the subtitle bar disappears behind it. Three things are needed to float
above *another application's* fullscreen Space:

1. ``CanJoinAllSpaces`` so the window follows you to every Space, and
   ``FullScreenAuxiliary`` so it may sit on top of a fullscreen one.
2. An *accessory* activation policy. A regular app owns a Dock icon and a
   Cmd-Tab entry and is not treated as an overlay utility; neither is wanted
   here, and the overlay is click-through so it never needs to be activated.
3. Re-applying (1) whenever Qt recreates the native NSWindow. Qt's default is
   ``FullScreenPrimary`` — precisely the behaviour that puts the window in its
   own Space — so a silent recreation undoes the fix with nothing in the log.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# NSWindowCollectionBehavior bits. Declared here (rather than only imported from
# AppKit) so the intended value is unit-testable without a GUI session, and so a
# mismatch with the real AppKit constants is caught at runtime instead of
# silently changing behaviour.
_BITS: dict[str, int] = {
    "CanJoinAllSpaces": 1 << 0,
    "MoveToActiveSpace": 1 << 1,
    "Managed": 1 << 2,
    "Transient": 1 << 3,
    "Stationary": 1 << 4,
    "ParticipatesInCycle": 1 << 5,
    "IgnoresCycle": 1 << 6,
    "FullScreenPrimary": 1 << 7,
    "FullScreenAuxiliary": 1 << 8,
    "FullScreenNone": 1 << 9,
}

#: What the overlay window's collectionBehavior must be.
#:
#: ``Stationary`` is deliberately *not* included: Apple documents it as keeping
#: the window "visible and stationary, like the desktop window", which is the
#: symptom reported in #33, and it is orthogonal to the all-Spaces goal.
OVERLAY_BEHAVIOR = _BITS["CanJoinAllSpaces"] | _BITS["FullScreenAuxiliary"] | _BITS["IgnoresCycle"]


def describe_behavior(value: int) -> str:
    """'0x101 = CanJoinAllSpaces | FullScreenAuxiliary' — for logs and diagnosis."""
    names = [name for name, bit in _BITS.items() if value & bit]
    unknown = value & ~sum(_BITS.values())
    if unknown:
        names.append(f"0x{unknown:x}")
    return f"0x{value:x} = {' | '.join(names) if names else '(none)'}"


class _LogOnce:
    """Gate that only lets a *changed* state through.

    ``reapply_if_reverted`` runs every two seconds. Without this, a window whose
    behaviour AppKit refuses to change would write the same two lines to the log
    forever, which is exactly the noise that made #33 hard to see in the first
    place.
    """

    def __init__(self) -> None:
        self._last: object = None

    def is_new(self, state: object) -> bool:
        if state == self._last:
            return False
        self._last = state
        return True

    def reset(self) -> None:
        self._last = None


def pyobjc_available() -> bool:
    """True when the Cocoa bindings the overlay needs can be imported.

    Distinguishes "PyObjC is missing, nothing will ever work" from "this attempt
    failed", so the caller knows whether retrying is worth anything.
    """
    try:
        import AppKit  # noqa: F401
        import objc  # noqa: F401
    except ImportError:
        return False
    return True


def _ns_window(widget):
    """The NSWindow behind a shown QWidget, or None."""
    import objc

    # QWidget.winId() is the NSView* on macOS; its window() is the NSWindow.
    return objc.objc_object(c_void_p=int(widget.winId())).window()


def use_accessory_activation_policy() -> bool:
    """Run as an accessory (LSUIElement) app: no Dock icon, no Cmd-Tab entry.

    A regular app's windows are not treated as overlay utilities by the window
    server, which is one reason the bar stayed on the desktop Space (#33).
    Must be called *after* the QApplication exists, because Qt sets the policy
    to Regular when it initialises NSApplication.
    """
    try:
        from AppKit import NSApp, NSApplicationActivationPolicyAccessory
    except ImportError:
        return False
    try:
        app = NSApp()
        if app is None:
            log.warning("NSApp not available yet; activation policy unchanged")
            return False
        if app.activationPolicy() == NSApplicationActivationPolicyAccessory:
            return True
        if not app.setActivationPolicy_(NSApplicationActivationPolicyAccessory):
            log.warning("setActivationPolicy(Accessory) was refused")
            return False
        log.info("Activation policy set to Accessory (no Dock icon / Cmd-Tab entry)")
        return True
    except Exception:
        log.exception("Failed to set the accessory activation policy")
        return False


def make_visible_over_fullscreen(widget) -> bool:
    """Configure the NSWindow behind a shown QWidget to appear on all Spaces and
    above fullscreen apps. Returns False (and logs why) when PyObjC is missing.
    Must be called *after* ``widget.show()`` so the native window exists.
    """
    try:
        import AppKit
    except ImportError:
        log.warning("PyObjC not installed — overlay will not show over fullscreen apps "
                    "(pip install pyobjc-framework-Cocoa)")
        return False

    # Catch an AppKit whose constants ever stop matching the values above.
    for name, bit in _BITS.items():
        actual = getattr(AppKit, f"NSWindowCollectionBehavior{name}", None)
        if actual is not None and actual != bit:
            log.error("NSWindowCollectionBehavior%s is 0x%x, expected 0x%x — "
                      "the overlay behaviour may be wrong", name, actual, bit)

    try:
        ns_window = _ns_window(widget)
        if ns_window is None:
            log.warning("Native window not available yet; fullscreen overlay not applied")
            return False
        ns_window.setCollectionBehavior_(OVERLAY_BEHAVIOR)
        # Above fullscreen apps and the menu bar; still click-through.
        ns_window.setLevel_(AppKit.NSScreenSaverWindowLevel)
        ns_window.setIgnoresMouseEvents_(True)
        ns_window.setHidesOnDeactivate_(False)
        # Trust nothing: read back what AppKit actually kept (#33 was a silent failure).
        applied = ns_window.collectionBehavior()
        if applied != OVERLAY_BEHAVIOR:
            log.warning("Collection behaviour not applied as intended: wanted %s, got %s",
                        describe_behavior(OVERLAY_BEHAVIOR), describe_behavior(applied))
            return False
        log.info("Overlay configured to show on all Spaces and over fullscreen apps (%s)",
                 describe_behavior(applied))
        return True
    except Exception:
        log.exception("Failed to apply macOS fullscreen overlay behaviour")
        return False


_repair_log = _LogOnce()


def reapply_if_reverted(widget) -> bool:
    """Re-apply the overlay behaviour if the native window lost it.

    Qt recreates the NSWindow on some screen/Space changes, which resets
    ``collectionBehavior`` to its default (``FullScreenPrimary``) and silently
    breaks the overlay. Returns True when a revert was found **and the repair
    was verified**; a re-apply AppKit did not honour returns False rather than
    reporting a fix that did not happen.
    """
    try:
        import AppKit

        ns_window = _ns_window(widget)
        if ns_window is None:
            return False
        current = ns_window.collectionBehavior()
        if current == OVERLAY_BEHAVIOR:
            _repair_log.reset()
            return False
        first_time = _repair_log.is_new(current)
        if first_time:
            log.info("Overlay behaviour reverted to %s — re-applying %s",
                     describe_behavior(current), describe_behavior(OVERLAY_BEHAVIOR))
        ns_window.setCollectionBehavior_(OVERLAY_BEHAVIOR)
        ns_window.setLevel_(AppKit.NSScreenSaverWindowLevel)
        ns_window.setIgnoresMouseEvents_(True)
        ns_window.setHidesOnDeactivate_(False)
        # Same rule as make_visible_over_fullscreen(): read it back, never assume.
        applied = ns_window.collectionBehavior()
        if applied != OVERLAY_BEHAVIOR:
            if first_time:
                log.warning("Re-apply did not take: wanted %s, got %s",
                            describe_behavior(OVERLAY_BEHAVIOR), describe_behavior(applied))
            return False
        _repair_log.reset()
        log.info("Overlay behaviour repaired (%s)", describe_behavior(applied))
        return True
    except Exception:
        log.exception("Failed to re-apply macOS fullscreen overlay behaviour")
        return False
