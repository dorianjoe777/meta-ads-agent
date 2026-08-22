#!/usr/bin/env python3
"""Optional Admira runtime hooks for subprocesses launched with src on PYTHONPATH."""
import builtins
import os


def _install_runtime_patches():
    """Apply Admira hooks even when Hermes imports its transport later.

    Python loads ``sitecustomize`` before the Hermes package.  The NVIDIA
    request wrapper depends on ``agent.chat_completion_helpers`` and therefore
    used to miss the CLI process entirely: the initial ``apply()`` call ran
    too early, returned successfully because unrelated hooks were installed,
    and never retried after Hermes loaded the helper module.  Keep a tiny
    import bridge so the provider hook is installed at the first valid import.
    """
    try:
        import admira_hermes_runtime_patch as runtime_patch

        runtime_patch.apply()
        original_import = getattr(builtins, "__admira_original_import__", None)
        if original_import is None:
            original_import = builtins.__import__
            builtins.__admira_original_import__ = original_import

            def admira_import(name, globals=None, locals=None, fromlist=(), level=0):
                module = original_import(name, globals, locals, fromlist, level)
                if (
                    str(name or "").startswith("agent.chat_completion_helpers")
                    or (str(name or "") == "agent" and "chat_completion_helpers" in (fromlist or ()))
                    or str(name or "") == "run_agent"
                ):
                    try:
                        runtime_patch._patch_nvidia_request_gate()
                    except Exception:
                        # Runtime compatibility hooks must never prevent
                        # Hermes from starting; the canary diagnostics expose
                        # an unpatched request if this fails.
                        pass
                # ``gateway.run`` is imported after sitecustomize during
                # normal Hermes startup. Retry the GatewayRunner patch at
                # the point where the class has actually been defined.
                if str(name or "") == "gateway.run":
                    try:
                        runtime_patch._patch_gateway_chatgpt_slash_commands()
                    except Exception:
                        pass
                    try:
                        runtime_patch._patch_gateway_generated_media_delivery()
                    except Exception:
                        pass
                    try:
                        runtime_patch._patch_gateway_reset_campaign_scope()
                    except Exception:
                        pass
                return module

            builtins.__import__ = admira_import

        # If a host/runtime preloaded the helper before sitecustomize, patch
        # it immediately rather than waiting for a second import.
        if "agent.chat_completion_helpers" in __import__("sys").modules:
            runtime_patch._patch_nvidia_request_gate()
    except Exception:
        # Buyer-facing subprocesses must keep starting even if a defensive
        # compatibility patch cannot be applied to the installed Hermes
        # version. The provider can still return a normal diagnostic.
        pass


if os.environ.get("ADMIRA_HERMES_RUNTIME_PATCHES") == "1":
    _install_runtime_patches()
