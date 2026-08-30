#!/usr/bin/env python3
"""Small, explicit canary for the hosted central-image path.

``synthetic`` starts an in-process broker with a fake provider.  It verifies
the request contract, tenant isolation, reference snapshots and request
idempotency, but it does *not* verify external ChatGPT/Codex authentication.

``real`` talks to the already configured hosted broker for one tenant.  It is
the only mode that exercises the external provider, and it returns a blocked
status when central authentication/entitlement is not ready.  The command
never accepts or prints a provider token; central credentials stay owned by
the broker service.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from deploy.contabo.central_codex_account_pool import CentralCodexAccountPool
from deploy.contabo.central_image_service import CentralImageServer
from deploy.contabo.image_broker import ImageBroker, sign_request
from src.hosted_central_image_client import maybe_generate_central_image


PNG = b"\x89PNG\r\n\x1a\nsynthetic-central-canary"


def _wait_for_socket(path: Path, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not path.exists():
        raise RuntimeError("central_image_socket_not_ready")


def run_synthetic_canary() -> dict[str, Any]:
    """Run broker/client checks with a deterministic fake image provider."""
    with tempfile.TemporaryDirectory(prefix="admira-central-canary-") as raw:
        root = Path(raw)
        tenants = root / "tenants"
        keys = root / "keys"
        exchange = root / "exchange"
        socket_path = root / "run" / "broker.sock"
        tenants.mkdir(mode=0o700)
        keys.mkdir(mode=0o700)
        exchange.mkdir(mode=0o700)

        # Exercise the release's account selector without using a real
        # credential. The first isolated slot reports an image quota failure;
        # the second must be tried exactly once and must produce the output.
        auth_root = root / "central-auth"
        auth_root.mkdir(mode=0o700)
        accounts = []
        for account_id in ("primary", "secondary"):
            home = auth_root / account_id
            home.mkdir(mode=0o700)
            auth = home / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            auth.chmod(0o600)
            accounts.append({"id": account_id, "codex_home": str(home)})
        account_calls: list[str] = []

        def fake_account_provider(prompt: str, **kwargs: Any) -> dict[str, Any]:
            account_calls.append(kwargs["codex_home"].name)
            if len(account_calls) == 1:
                return {
                    "ok": False,
                    "failure_category": "chatgpt_images_limit",
                    "stderr": "synthetic-secret-that-must-not-escape",
                }
            image = Path(kwargs["output_root"]) / "pool-canary.png"
            image.write_bytes(PNG)
            return {"ok": True, "image_path": str(image), "stdout": "synthetic-secret"}

        pool_work = root / "pool-work"
        pool_work.mkdir(mode=0o700)
        pool_result = CentralCodexAccountPool(accounts, provider=fake_account_provider).generate(
            "synthetic private prompt", output_root=pool_work, output_name="pool-canary",
        )
        if not pool_result.get("ok") or account_calls != ["primary", "secondary"]:
            raise AssertionError("central_account_pool_fallback_failed")
        if Path(str(pool_result.get("image_path"))).read_bytes() != PNG:
            raise AssertionError("central_account_pool_output_failed")
        if "synthetic-secret" in repr(pool_result) or "private prompt" in repr(pool_result):
            raise AssertionError("central_account_pool_result_leaked")
        outputs: dict[str, Path] = {}
        access: dict[str, Path] = {}
        client_keys: dict[str, Path] = {}
        references: dict[str, Path] = {}
        tenant_key_material: dict[str, bytes] = {}
        for tenant in ("tenant-one", "tenant-two"):
            output = tenants / tenant / "output"
            output.mkdir(mode=0o700, parents=True)
            outputs[tenant] = output
            key_file = keys / tenant
            # Deliberately use a different HMAC secret per tenant.  Sharing a
            # key here would make the isolation check weaker than production.
            key = (tenant.encode("ascii") + b"-central-canary-key")[:64].ljust(64, b"!")
            tenant_key_material[tenant] = key
            key_file.write_bytes(key + b"\n")
            key_file.chmod(0o600)
            client_key = root / "client-keys" / tenant
            client_key.parent.mkdir(mode=0o700, exist_ok=True)
            client_key.write_bytes(key + b"\n")
            client_key.chmod(0o600)
            client_keys[tenant] = client_key
            reference = root / f"{tenant}-reference.png"
            reference.write_bytes(PNG + b"-" + tenant.encode("ascii"))
            reference.chmod(0o600)
            references[tenant] = reference
            access_file = root / "access" / f"{tenant}.json"
            access_file.parent.mkdir(mode=0o700, exist_ok=True)
            access_file.write_text(json.dumps({
                "tenant_id": tenant,
                "route": "central_sponsored",
                "central_ready": True,
                "update_id": "synthetic-canary",
            }) + "\n", encoding="utf-8")
            access_file.chmod(0o600)
            access[tenant] = access_file

        provider_calls: list[dict[str, Any]] = []

        def fake_provider(body: dict[str, Any], workdir: Path) -> bytes:
            provider_references = [Path(item) for item in body.get("references", [])]
            if any(not item.is_relative_to(workdir) for item in provider_references):
                raise AssertionError("provider_reference_left_private_workdir")
            if len(provider_references) != 1:
                raise AssertionError("provider_reference_missing")
            snapshot = provider_references[0]
            if stat.S_IMODE(snapshot.stat().st_mode) != 0o600:
                raise AssertionError("provider_reference_not_private")
            tenant = str(body.get("tenant_id"))
            if snapshot.read_bytes() != PNG + b"-" + tenant.encode("ascii"):
                raise AssertionError("provider_reference_bytes_mismatch")
            if snapshot == references[tenant]:
                raise AssertionError("provider_received_original_reference")
            provider_calls.append({"tenant_id": tenant, "workdir": workdir,
                                   "reference": snapshot})
            return PNG

        broker = ImageBroker(
            tenants, keys, fake_provider,
            lambda tenant, purpose: "central_sponsored"
            if purpose == "image_generation" and tenant in outputs else "blocked",
            max_global=2,
        )
        server = CentralImageServer(broker, socket_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        _wait_for_socket(socket_path)
        try:
            wrong_key_body = {
                "tenant_id": "tenant-two", "request_id": "wrong-key-001",
                "prompt": "Synthetic central image canary", "purpose": "image_generation",
                "aspect": "square", "references": [],
            }
            wrong_key = sign_request(
                tenant_key_material["tenant-one"], wrong_key_body,
                timestamp=int(time.time()), nonce="c" * 32,
            )
            if broker.submit(wrong_key, now=wrong_key["timestamp"])["error_code"] != "invalid_signature":
                raise AssertionError("cross_tenant_key_accepted")
            results: dict[str, list[dict[str, Any]]] = {}
            for tenant in ("tenant-one", "tenant-two"):
                # In production the exchange bind mount resolves to this
                # tenant's output root; keeping that relationship here also
                # verifies the client can consume the broker's opaque ref.
                with _tenant_env(tenant, access[tenant], client_keys[tenant], outputs[tenant], socket_path):
                    first = maybe_generate_central_image(
                        "Synthetic central image canary", output_root=outputs[tenant],
                        output_name="canary", reference_image_paths=[references[tenant]],
                        update_id="same-request", timeout=5,
                    )
                    second = maybe_generate_central_image(
                        "Synthetic central image canary", output_root=outputs[tenant],
                        output_name="canary", reference_image_paths=[references[tenant]],
                        update_id="same-request", timeout=5,
                    )
                results[tenant] = [first or {}, second or {}]
                if not first or not first.get("ok") or first != second:
                    raise AssertionError(f"synthetic_idempotency_failed:{tenant}")
                image = Path(str(first["image_path"])).resolve()
                if not image.is_relative_to(outputs[tenant].resolve()):
                    raise AssertionError(f"tenant_output_escape:{tenant}")
                if image.read_bytes() != PNG:
                    raise AssertionError(f"synthetic_output_mismatch:{tenant}")
            if [call["tenant_id"] for call in provider_calls] != ["tenant-one", "tenant-two"]:
                raise AssertionError("provider_called_more_than_once_per_request")
            return {
                "mode": "synthetic",
                "ok": True,
                "provider_calls": len(provider_calls),
                "tenants_verified": ["tenant-one", "tenant-two"],
                "distinct_tenant_keys_verified": len(set(tenant_key_material.values())) == 2,
                "cross_tenant_key_rejected": True,
                "reference_snapshots_verified": True,
                "idempotency_verified": True,
                "account_pool_fallback_verified": True,
                "account_pool_size_verified": len(accounts),
                "external_provider_verified": False,
            }
        finally:
            server.close()
            thread.join(timeout=2)


class _tenant_env:
    def __init__(self, tenant: str, access: Path, key: Path, exchange: Path, socket_path: Path):
        self.values = {
            "ADMIRA_TENANT_ID": tenant,
            "ADMIRA_HOSTED_IMAGE_ACCESS_FILE": str(access),
            "ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE": str(key),
            "ADMIRA_CENTRAL_IMAGE_EXCHANGE_ROOT": str(exchange),
            "ADMIRA_CENTRAL_IMAGE_SOCKET": str(socket_path),
        }
        self.previous: dict[str, str | None] = {}

    def __enter__(self):
        for name, value in self.values.items():
            self.previous[name] = os.environ.get(name)
            os.environ[name] = value

    def __exit__(self, _type, _value, _traceback):
        for name, old in self.previous.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def run_real_canary(prompt: str, output_root: Path, update_id: str) -> dict[str, Any]:
    """Exercise one configured tenant through the external central provider."""
    result = maybe_generate_central_image(
        prompt, output_root=output_root, output_name="canary", update_id=update_id, timeout=300,
    )
    if not result:
        return {"mode": "real", "ok": False, "status": "not_configured",
                "message": "Hosted central-image entitlement/socket is not configured."}
    if result.get("ok") is not True:
        return {"mode": "real", "ok": False, "status": "blocked",
                "error": result.get("reason", "provider_failed")}
    return {"mode": "real", "ok": True, "status": "provider_verified",
            "request_id": result.get("request_id"), "asset_id": result.get("asset_id")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("synthetic", "real"), default="synthetic")
    parser.add_argument("--prompt", default="Admira central image canary")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/admira-central-canary"))
    parser.add_argument("--update-id", default="manual-canary")
    args = parser.parse_args(argv)
    result = (run_synthetic_canary() if args.mode == "synthetic" else
              run_real_canary(args.prompt, args.output_root, args.update_id))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
