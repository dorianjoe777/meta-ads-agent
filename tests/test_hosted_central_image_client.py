import hashlib, hmac, json, os, socket, stat, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch

from src.hosted_central_image_client import (_canonical, _request_uuid, _snapshot_reference,
                                             maybe_generate_central_image)


PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 32

class CentralClientTests(unittest.TestCase):
    def test_request_id_is_deterministic_and_hmac_is_verifiable(self):
        refs = [{"sha256": "a" * 64, "bytes": 4, "suffix": ".png"}]
        first = _request_uuid("tenant-001", "7", "prompt", "ad_creative", "square", refs)
        self.assertEqual(first, _request_uuid("tenant-001", "7", "prompt", "ad_creative", "square", refs))
        self.assertNotEqual(first, _request_uuid("tenant-001", "7", "prompt", "ad_creative", "portrait", refs))
        envelope = {"timestamp": 1, "nonce": "n", "body": {"tenant_id": "tenant-001"}}
        signature = hmac.new(b"k" * 32, _canonical(envelope), hashlib.sha256).hexdigest()
        self.assertTrue(hmac.compare_digest(signature, hmac.new(b"k" * 32, _canonical(envelope), hashlib.sha256).hexdigest()))

    def test_disabled_and_personal_return_none_but_blocked_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "access"; p.write_text(json.dumps({"route": "personal_chatgpt"})); p.chmod(0o600)
            with patch.dict(os.environ, {"ADMIRA_HOSTED_IMAGE_ACCESS_FILE": str(p), "ADMIRA_TENANT_ID": "tenant-001"}):
                self.assertIsNone(maybe_generate_central_image("x", output_root=d))
            p.write_text(json.dumps({"route": "blocked"})); p.chmod(0o600)
            with patch.dict(os.environ, {"ADMIRA_HOSTED_IMAGE_ACCESS_FILE": str(p), "ADMIRA_TENANT_ID": "tenant-001"}):
                self.assertEqual(maybe_generate_central_image("x", output_root=d)["reason"], "entitlement_blocked")

    def test_not_ready_blocks_without_socket(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "access"; p.write_text(json.dumps({"route":"central_sponsored", "central_ready":False, "tenant_id":"tenant-001"})); p.chmod(0o600)
            with patch.dict(os.environ, {"ADMIRA_HOSTED_IMAGE_ACCESS_FILE":str(p), "ADMIRA_TENANT_ID":"tenant-001"}):
                self.assertEqual(maybe_generate_central_image("x", output_root=d)["reason"], "central_not_ready")

    def test_signed_round_trip_and_atomic_copy(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); access=root/"access"; key=root/"key"; sock=root/"broker.sock"; exchange=root/"exchange"; ref=root/"ref.png"
            access.write_text(json.dumps({"route":"central_sponsored","central_ready":True,"tenant_id":"tenant-001"})); access.chmod(0o600)
            key.write_bytes(b"k"*32); key.chmod(0o600); ref.write_bytes(PNG); (root/"out").mkdir()
            def serve():
                with socket.socket(socket.AF_UNIX) as s:
                    s.bind(str(sock)); s.listen(1); c,_=s.accept()
                    with c:
                        req=json.loads(c.recv(65536)); body=req["body"]
                        out=exchange/("a"*32+".png"); out.write_bytes(PNG)
                        c.sendall((json.dumps({"ok":True,"tenant_id":"tenant-001","request_id":body["request_id"],"output_ref":out.name,"sha256":hashlib.sha256(PNG).hexdigest(),"size":len(PNG)})+"\n").encode())
            thread=threading.Thread(target=serve); thread.start()
            env={"ADMIRA_HOSTED_IMAGE_ACCESS_FILE":str(access),"ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE":str(key),"ADMIRA_CENTRAL_IMAGE_SOCKET":str(sock),"ADMIRA_CENTRAL_IMAGE_EXCHANGE_ROOT":str(exchange),"ADMIRA_TENANT_ID":"tenant-001"}
            with patch.dict(os.environ,env): result=maybe_generate_central_image("x",output_root=root/"out",reference_image_paths=[ref],update_id=3)
            thread.join(); self.assertTrue(result["ok"], result); generated=Path(result["image_path"]); self.assertEqual(generated.read_bytes(),PNG); self.assertEqual(stat.S_IMODE(generated.stat().st_mode),0o600); self.assertTrue(result["request_id"])

    def test_rejects_symlink_reference_and_bad_response(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); access=root/"a"; access.write_text(json.dumps({"route":"central_sponsored","central_ready":True,"tenant_id":"tenant-001"})); access.chmod(0o600)
            ref=root/"r"; ref.symlink_to(root/"missing")
            with patch.dict(os.environ,{"ADMIRA_HOSTED_IMAGE_ACCESS_FILE":str(access),"ADMIRA_TENANT_ID":"tenant-001"}): self.assertEqual(maybe_generate_central_image("x",output_root=root,reference_image_paths=[ref])["reason"],"provider_failed")

    def test_reference_swap_at_open_boundary_never_reads_linked_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "reference.png"
            outside = root / "outside.png"
            target = root / "snapshot.png"
            source.write_bytes(PNG)
            outside.write_bytes(b"linked-secret-bytes")
            real_open = os.open
            swapped = False

            def swap_before_open(path, flags, *args):
                nonlocal swapped
                if Path(path) == source and not swapped:
                    swapped = True
                    source.unlink()
                    source.symlink_to(outside)
                return real_open(path, flags, *args)

            with patch("src.hosted_central_image_client.os.open", side_effect=swap_before_open):
                with self.assertRaisesRegex(ValueError, "reference_invalid"):
                    _snapshot_reference(source, target)
            self.assertTrue(swapped)
            self.assertFalse(target.exists())

    def test_rejects_truncated_and_dangerous_output_refs(self):
        for payload in (b'{"ok":true}', b'{"ok":true,"tenant_id":"tenant-001","request_id":"x","output_ref":"../secret.png"}\n'):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d); access=root/"a"; key=root/"k"; sock=root/"s"; exchange=root/"e"
                access.write_text(json.dumps({"route":"central_sponsored","central_ready":True,"tenant_id":"tenant-001"})); access.chmod(0o600); key.write_bytes(b"k"*32); key.chmod(0o600); exchange.mkdir()
                def serve():
                    with socket.socket(socket.AF_UNIX) as s:
                        s.bind(str(sock)); s.listen(1); c,_=s.accept()
                        with c: c.recv(65536); c.sendall(payload)
                thread=threading.Thread(target=serve, daemon=True); thread.start()
                env={"ADMIRA_HOSTED_IMAGE_ACCESS_FILE":str(access),"ADMIRA_CENTRAL_IMAGE_CLIENT_KEY_FILE":str(key),"ADMIRA_CENTRAL_IMAGE_SOCKET":str(sock),"ADMIRA_CENTRAL_IMAGE_EXCHANGE_ROOT":str(exchange),"ADMIRA_TENANT_ID":"tenant-001"}
                with patch.dict(os.environ,env): result=maybe_generate_central_image("x",output_root=root,timeout=1)
                thread.join(timeout=2); self.assertFalse(result["ok"])

if __name__ == "__main__": unittest.main()
