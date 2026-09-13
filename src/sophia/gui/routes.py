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

DASHBOARD_SURFACE_PATH = "/app/dashboard"
REVIEW_SURFACE_PATH = "/app/review"
QUICKSTART_SURFACE_PATH = "/app/quickstart"
"""Where a learner is sent for the three high-traffic non-study surfaces.

Phase 4a (issue #99) moved dashboard, quickstart and review to SvelteKit. Same
arrangement as study: the NiceGUI pages stay registered, so ``/legacy/`` and
``/legacy/review`` still resolve for anyone holding a link, and every call to
action in this app points at ``/app`` instead. Deleting the pages is phase 5's
job, not this constant's.
"""
