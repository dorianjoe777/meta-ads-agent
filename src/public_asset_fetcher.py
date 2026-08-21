#!/usr/bin/env python3
"""Safe public URL and creative-asset retrieval for buyer-shared links."""
import hashlib
import html
import http.cookiejar
import ipaddress
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from local_store import now_iso
from product_config import ROOT_DIR, env_int


PUBLIC_ASSET_DIR = ROOT_DIR / "dashboard" / "data" / "uploads" / "public_assets"
DEFAULT_MAX_ASSET_BYTES = 250 * 1024 * 1024
DEFAULT_MAX_TEXT_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
DEFAULT_VIDEO_FRAME_COUNT = 4
TEXT_CONTENT_TYPES = {"text/html", "text/plain", "application/json", "text/markdown"}
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class PublicAssetError(ValueError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def max_asset_bytes():
    return max(1024 * 1024, env_int("PUBLIC_ASSET_MAX_BYTES", DEFAULT_MAX_ASSET_BYTES))


def max_text_bytes():
    return max(64 * 1024, min(DEFAULT_MAX_TEXT_BYTES, env_int("PUBLIC_ASSET_MAX_TEXT_BYTES", DEFAULT_MAX_TEXT_BYTES)))


def max_video_frame_count():
    return max(1, min(6, env_int("PUBLIC_ASSET_VIDEO_FRAME_COUNT", DEFAULT_VIDEO_FRAME_COUNT)))


def extract_url(value):
    text = str(value or "").strip()
    match = re.search(r"https?://[^\s<>\"']+", text, flags=re.I)
    if not match:
        return ""
    return match.group(0).rstrip(").,;]}'\"")


def google_drive_file_id(parsed):
    host = str(parsed.hostname or "").lower()
    if host not in {"drive.google.com", "www.drive.google.com", "docs.google.com"}:
        return ""
    match = re.search(r"/file/d/([^/]+)", parsed.path or "")
    if match:
        return match.group(1)
    query = urllib.parse.parse_qs(parsed.query or "")
    return (query.get("id") or [""])[0]


def normalize_public_asset_url(raw_url):
    url = extract_url(raw_url) or str(raw_url or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise PublicAssetError("unsupported_url_scheme", "Solo puedo abrir enlaces http/https públicos.")
    if parsed.username or parsed.password:
        raise PublicAssetError("url_credentials_not_allowed", "No puedo abrir enlaces que traen usuario/contraseña en la URL.")
    file_id = google_drive_file_id(parsed)
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={urllib.parse.quote(file_id)}"
    return urllib.parse.urlunparse(parsed)


def validate_public_url(url):
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise PublicAssetError("unsupported_url_scheme", "Solo puedo abrir enlaces http/https públicos.")
    host = str(parsed.hostname or "").strip().lower()
    if not host or host in BLOCKED_HOSTS:
        raise PublicAssetError("private_or_local_url", "Ese enlace apunta a una dirección local o privada, no a un recurso público.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PublicAssetError("dns_lookup_failed", f"No pude resolver ese dominio: {exc}") from exc
    checked = set()
    for info in infos:
        ip = info[4][0]
        if ip in checked:
            continue
        checked.add(ip)
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError as exc:
            raise PublicAssetError("invalid_resolved_ip", "El dominio resolvió a una dirección inválida.") from exc
        if not addr.is_global:
            raise PublicAssetError("private_or_local_url", "Ese enlace redirige o resuelve a una red local/privada; lo bloqueé por seguridad.")
    return True


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def content_disposition_filename(value):
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', str(value or ""), flags=re.I)
    if not match:
        return ""
    return urllib.parse.unquote(match.group(1).strip().strip('"'))


def extension_for_response(url, headers):
    filename = content_disposition_filename(headers.get("Content-Disposition", ""))
    suffix = Path(filename).suffix.lower()
    if suffix:
        return suffix
    parsed_suffix = Path(urllib.parse.urlparse(url).path or "").suffix.lower()
    if parsed_suffix:
        return parsed_suffix
    content_type = str(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    mapping = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "text/html": ".html",
        "text/plain": ".txt",
        "application/json": ".json",
    }
    return mapping.get(content_type) or mimetypes.guess_extension(content_type) or ".bin"


def asset_kind(content_type, suffix):
    content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    suffix = str(suffix or "").lower()
    if content_type.startswith("video/") or suffix in VIDEO_EXTENSIONS:
        return "video"
    if content_type.startswith("image/") or suffix in IMAGE_EXTENSIONS:
        return "image"
    if content_type in TEXT_CONTENT_TYPES or content_type.startswith("text/") or suffix in {".html", ".txt", ".md", ".json"}:
        return "web_page" if "html" in content_type or suffix == ".html" else "text"
    return "file"


def title_from_text(text):
    match = re.search(r"<title[^>]*>(.*?)</title>", text or "", flags=re.I | re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()[:160]


def text_excerpt(raw, content_type):
    text = raw.decode("utf-8", errors="replace")
    if "html" in str(content_type or "").lower():
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
        text = re.sub(r"(?is)<br\s*/?>", "\n", text)
        text = re.sub(r"(?is)</p\s*>", "\n", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:5000]


def google_drive_confirm_url(page_url, html_text):
    for raw in re.findall(r'href=["\']([^"\']*?(?:confirm=|download_warning)[^"\']*)["\']', html_text or "", flags=re.I):
        candidate = html.unescape(raw)
        if candidate.startswith("/"):
            candidate = urllib.parse.urljoin(page_url, candidate)
        parsed = urllib.parse.urlparse(candidate)
        if parsed.scheme in {"http", "https"} and google_drive_file_id(parsed):
            return candidate
    match = re.search(r'action=["\']([^"\']+/uc[^"\']*)["\']', html_text or "", flags=re.I)
    if match:
        return urllib.parse.urljoin(page_url, html.unescape(match.group(1)))
    return ""


def save_stream(response, target, limit):
    total = 0
    digest = hashlib.sha256()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        while True:
            chunk = response.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                try:
                    target.unlink()
                except OSError:
                    pass
                raise PublicAssetError("asset_too_large", f"El archivo supera el límite seguro de {round(limit / 1024 / 1024)} MB.")
            digest.update(chunk)
            handle.write(chunk)
    return total, digest.hexdigest()


def ffmpeg_binary(name):
    configured = os.environ.get(f"{name.upper()}_PATH", "").strip()
    if configured:
        return configured
    return shutil.which(name) or ""


def video_duration_seconds(video_path):
    ffprobe = ffmpeg_binary("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0.0
    if completed.returncode != 0:
        return 0.0
    try:
        return max(0.0, float(str(completed.stdout or "").strip() or 0))
    except ValueError:
        return 0.0


def video_frame_times(duration, count):
    count = max(1, int(count or DEFAULT_VIDEO_FRAME_COUNT))
    if duration > 0:
        ratios = [0.12, 0.35, 0.6, 0.85, 0.5, 0.72]
        raw_times = [min(max(duration * ratio, 0.1), max(duration - 0.1, 0.1)) for ratio in ratios[:count]]
    else:
        raw_times = [0.1, 1.5, 3.0, 5.0, 8.0, 12.0][:count]
    unique = []
    seen = set()
    for value in raw_times:
        rounded = round(float(value), 2)
        key = f"{rounded:.2f}"
        if key not in seen:
            seen.add(key)
            unique.append(rounded)
    return unique[:count]


def extract_video_preview_frames(video_path, output_dir=None, max_frames=None):
    """Extract representative JPG frames so vision-capable models can review MP4/MOV assets."""
    path = Path(video_path).expanduser()
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return {"ok": False, "reason": "video_missing", "frames": [], "duration_seconds": 0}
    if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.is_file():
        return {"ok": False, "reason": "not_video", "frames": [], "duration_seconds": 0}
    ffmpeg = ffmpeg_binary("ffmpeg")
    if not ffmpeg:
        return {"ok": False, "reason": "ffmpeg_missing", "frames": [], "duration_seconds": 0}
    duration = video_duration_seconds(path)
    count = max_frames if max_frames is not None else max_video_frame_count()
    frame_dir = Path(output_dir or (path.parent / f"{path.stem}_frames")).expanduser()
    frame_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, second in enumerate(video_frame_times(duration, count), start=1):
        frame_path = frame_dir / f"{path.stem}_frame_{index:02d}.jpg"
        try:
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{second:.2f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(frame_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=25,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0 and frame_path.exists() and frame_path.stat().st_size > 0:
            frames.append(str(frame_path))
    return {
        "ok": bool(frames),
        "reason": "" if frames else "frame_extraction_failed",
        "frames": frames,
        "duration_seconds": round(duration, 2) if duration else 0,
    }


def fetch_public_asset(payload):
    payload = payload or {}
    raw_url = payload.get("url") or payload.get("asset_url") or payload.get("link") or payload.get("message") or ""
    if not raw_url:
        raise PublicAssetError("missing_url", "Necesito un enlace público para revisarlo.")
    normalized_url = normalize_public_asset_url(raw_url)
    validate_public_url(normalized_url)
    limit = int(payload.get("max_bytes") or max_asset_bytes())
    text_limit = int(payload.get("max_text_bytes") or max_text_bytes())
    user_agent = str(payload.get("user_agent") or "AdmiraIA-PublicAssetFetcher/1.0").strip()[:160]
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar), SafeRedirectHandler)

    def open_url(url):
        validate_public_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        return opener.open(request, timeout=max(5, min(90, int(payload.get("timeout") or 45))))

    try:
        response = open_url(normalized_url)
    except urllib.error.HTTPError as exc:
        reason = "url_requires_login" if exc.code in {401, 403} else "url_fetch_failed"
        raise PublicAssetError(reason, f"No pude abrir el enlace público. HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PublicAssetError("url_fetch_failed", f"No pude abrir el enlace público: {exc}") from exc

    final_url = response.geturl()
    validate_public_url(final_url)
    headers = response.headers
    content_length = headers.get("Content-Length")
    if content_length and int(content_length) > limit:
        raise PublicAssetError("asset_too_large", f"El archivo pesa más de {round(limit / 1024 / 1024)} MB.")
    content_type = str(headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].strip().lower()
    suffix = extension_for_response(final_url, headers)
    kind = asset_kind(content_type, suffix)

    if kind in {"web_page", "text"}:
        raw = response.read(text_limit + 1)
        if len(raw) > text_limit:
            raw = raw[:text_limit]
        text = raw.decode("utf-8", errors="replace")
        drive_confirm = google_drive_confirm_url(final_url, text) if google_drive_file_id(urllib.parse.urlparse(normalized_url)) else ""
        if drive_confirm:
            validate_public_url(drive_confirm)
            response = open_url(drive_confirm)
            final_url = response.geturl()
            validate_public_url(final_url)
            headers = response.headers
            content_type = str(headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].strip().lower()
            suffix = extension_for_response(final_url, headers)
            kind = asset_kind(content_type, suffix)
        else:
            lower_text = text.lower()
            if "sign in" in lower_text and "google" in lower_text:
                raise PublicAssetError("url_requires_login", "Ese enlace parece pedir inicio de sesión. Comparte el archivo como público o súbelo directo por Telegram.")
            if "request access" in lower_text or "solicitar acceso" in lower_text or "you need access" in lower_text:
                raise PublicAssetError("url_not_public", "Ese archivo no está público. Activa acceso por enlace o súbelo directo por Telegram.")
            return {
                "ok": True,
                "asset_type": kind,
                "original_url": str(raw_url),
                "normalized_url": normalized_url,
                "final_url": final_url,
                "title": title_from_text(text),
                "text_excerpt": text_excerpt(raw, content_type),
                "downloaded": False,
                "content_type": content_type,
                "created_at": now_iso(),
            }

    safe_suffix = suffix if re.match(r"^\.[a-z0-9]{1,8}$", suffix or "") else ".bin"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    digest_name = hashlib.sha256(final_url.encode("utf-8")).hexdigest()[:10]
    target = PUBLIC_ASSET_DIR / f"public_asset_{timestamp}_{digest_name}{safe_suffix}"
    size, sha256 = save_stream(response, target, limit)
    relative = target.relative_to(ROOT_DIR)
    direct_url = final_url if kind == "video" else ""
    if google_drive_file_id(urllib.parse.urlparse(normalized_url)) and kind == "video":
        direct_url = normalized_url
    frame_result = extract_video_preview_frames(target) if kind == "video" else {"frames": [], "duration_seconds": 0, "ok": False, "reason": ""}
    frame_paths = frame_result.get("frames") or []
    return {
        "ok": True,
        "asset_type": kind,
        "original_url": str(raw_url),
        "normalized_url": normalized_url,
        "final_url": final_url,
        "direct_url": direct_url,
        "downloaded": True,
        "content_type": content_type,
        "file_path": str(target),
        "relative_path": str(relative),
        "filename": target.name,
        "size": size,
        "sha256": sha256,
        "video_url": direct_url if kind == "video" else "",
        "video_duration_seconds": frame_result.get("duration_seconds") or 0,
        "video_frame_paths": frame_paths,
        "video_preview_frame_paths": frame_paths,
        "video_frame_count": len(frame_paths),
        "video_visual_review": (
            "Use video_frame_paths with the vision/image tool to inspect representative frames; do not try to visually inspect the MP4 directly."
            if kind == "video" and frame_paths
            else ""
        ),
        "video_frame_error": frame_result.get("reason") if kind == "video" and not frame_paths else "",
        "image_path": str(target) if kind == "image" else "",
        "created_at": now_iso(),
    }


def fetch_public_asset_result(payload):
    try:
        return fetch_public_asset(payload)
    except PublicAssetError as exc:
        return {"ok": False, "blocked": True, "reason": exc.reason, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "blocked": True, "reason": "url_fetch_failed", "error": str(exc)}
