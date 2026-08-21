#!/usr/bin/env python3
"""Small content review dashboard for generated social assets."""
import json
import sys
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from content_pipeline import approve_item, generate_batch, list_items, add_comment
from keyframe_planner import plan_keyframes


PORT = 7872
ROOT_DIR = Path(__file__).resolve().parent.parent


def safe_asset_path(value):
    candidate = Path(str(value or "")).resolve()
    try:
        candidate.relative_to(ROOT_DIR)
    except ValueError as exc:
        raise FileNotFoundError("Asset not found") from exc
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError("Asset not found")
    return candidate


def page():
    items = list_items()["items"]
    cards = []
    for item in items:
        comments = "".join(f"<li>{escape(str(c.get('comment') or ''))}</li>" for c in item.get("comments", []))
        asset = item.get("asset_path", "")
        preview = (
            f'<img src="/asset?path={escape(str(asset), quote=True)}" alt="{escape(str(item.get("id") or ""), quote=True)} preview">'
            if item.get("type") == "image"
            else f'<video src="/asset?path={escape(str(asset), quote=True)}" controls muted playsinline preload="metadata"></video>'
        )
        asset_label = "Final MP4" if item.get("type") == "motion" else "Final image"
        cards.append(f"""
        <article class="card">
          <div class="meta"><b>{asset_label}</b><span>{escape(str(item.get("status") or ""))}</span></div>
          {preview}
          <h2>{escape(str(item.get("copy", {}).get("headline") or ""))}</h2>
          <p>{escape(str(item.get("copy", {}).get("caption") or ""))}</p>
          <form method="post" action="/approve"><input type="hidden" name="id" value="{escape(str(item.get("id") or ""), quote=True)}"><button>Approve</button></form>
          <form method="post" action="/comment">
            <input type="hidden" name="id" value="{escape(str(item.get("id") or ""), quote=True)}">
            <textarea name="comment" placeholder="Leave change notes"></textarea>
            <button type="submit">Request changes</button>
          </form>
          <ul>{comments}</ul>
        </article>
        """)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Content Review Queue</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#101315;color:#f2f2ee;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}header{{position:sticky;top:0;background:rgba(16,19,21,.88);backdrop-filter:blur(18px);border-bottom:1px solid #343a42;padding:18px 22px;display:flex;gap:12px;align-items:center;justify-content:space-between}}h1{{font-size:20px;margin:0}}main{{padding:18px;display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}}.card{{border:1px solid #343a42;background:#171c20;border-radius:8px;padding:14px;box-shadow:0 20px 50px rgba(0,0,0,.24)}}.meta{{display:flex;justify-content:space-between;color:#a7adb5;font-size:12px;text-transform:uppercase}}img,video{{width:100%;object-fit:cover;border-radius:7px;border:1px solid #343a42;background:#0b0d0f;margin:12px 0}}img{{aspect-ratio:4/5}}video{{aspect-ratio:9/16}}h2{{font-size:18px;line-height:1.15}}p{{color:#c4c9cf;line-height:1.45}}button{{border:1px solid #27c7a7;background:#27c7a7;color:#061512;border-radius:7px;padding:9px 11px;font-weight:850;cursor:pointer}}textarea{{width:100%;min-height:70px;margin:8px 0;background:#22262b;color:#f2f2ee;border:1px solid #343a42;border-radius:7px;padding:9px}}form{{margin-top:8px}}ul{{color:#f4b740;font-size:13px;line-height:1.35}}.secondary{{background:#22262b;color:#f2f2ee;border-color:#343a42;text-decoration:none;border-radius:7px;padding:9px 11px;font-weight:850}}.header-actions{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.header-actions form{{margin:0}}
</style>
</head>
<body>
<header>
  <div><h1>Content Review Queue</h1><div>{len(items)} generated item(s)</div></div>
  <div class="header-actions">
    <form method="post" action="/generate"><button>Generate today's batch</button></form>
  </div>
</header>
<main>{''.join(cards) or '<p>No generated content yet.</p>'}</main>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect_home(self):
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/asset":
            try:
                path = safe_asset_path(parse_qs(parsed.query).get("path", [""])[0])
            except FileNotFoundError:
                self.send_error(404)
                return
            data = path.read_bytes()
            if path.suffix.lower() == ".mp4":
                content_type = "video/mp4"
            elif path.suffix.lower() == ".svg":
                content_type = "image/svg+xml"
            else:
                content_type = "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_html(page())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        payload = parse_qs(self.rfile.read(length).decode("utf-8"))
        parsed = urlparse(self.path)
        if parsed.path == "/generate":
            generate_batch(force=True)
            plan_keyframes()
        elif parsed.path == "/plan-keyframes":
            plan_keyframes()
        elif parsed.path == "/approve":
            approve_item(payload.get("id", [""])[0])
        elif parsed.path == "/comment":
            add_comment(payload.get("id", [""])[0], payload.get("comment", [""])[0])
        self.redirect_home()


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Content review dashboard: http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
