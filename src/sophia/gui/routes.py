"""Where the legacy GUI's calls to action point.

Kept apart from ``layout`` so the navigation, the keyboard shortcuts and the
quickstart wizard can agree on a destination without importing each other.
"""

from __future__ import annotations

STUDY_SURFACE_PATH = "/app/study"
"""Where a learner is sent to study.

The SvelteKit surface replaced this app's study page in phase 3 (issue #98).
The NiceGUI page stays registered so an existing ``/legacy/study`` link keeps
resolving until phase 5 retires it, but nothing here sends anyone there.
"""
