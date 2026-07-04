#!/usr/bin/env python3
"""Optional Admira runtime hooks for subprocesses launched with src on PYTHONPATH."""
import os


if os.environ.get("ADMIRA_HERMES_RUNTIME_PATCHES") == "1":
    try:
        from admira_hermes_runtime_patch import apply

        apply()
    except Exception:
        # Buyer-facing subprocesses must keep starting even if a defensive
        # compatibility patch cannot be applied to the installed Hermes version.
        pass
