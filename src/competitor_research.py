"""Public Ad Library visual provenance, isolated from buyer branding."""
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from local_store import now_iso


def _creative_element_expression(ad_id):
    # Inspect only rendered media inside the modal carrying this exact ad ID.
    # No image URL is downloaded, and no page code or text becomes executable.
    return """(() => {
      const adId = AD_ID;
      const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"]'))
        .filter(e => e.innerText.includes(adId));
      const media = dialogs.flatMap(e => Array.from(e.querySelectorAll('img, video')))
        .filter(e => {
          const r = e.getBoundingClientRect();
          return r.width > 64 && r.height > 64 &&
            (e.tagName === 'VIDEO' ? e.readyState >= 2 : e.complete && e.naturalWidth > 0);
        }).sort((a, b) => b.getBoundingClientRect().width * b.getBoundingClientRect().height -
                            a.getBoundingClientRect().width * a.getBoundingClientRect().height);
      if (!media.length) return null;
      const element = media[0];
      const parts = [];
      for (let e = element; e && e.nodeType === 1; e = e.parentElement) {
        const siblings = e.parentElement ? Array.from(e.parentElement.children).filter(s => s.tagName === e.tagName) : [e];
        parts.unshift(e.tagName.toLowerCase() + ':nth-of-type(' + (siblings.indexOf(e) + 1) + ')');
      }
      return {selector: parts.join(' > '), media_type: element.tagName.toLowerCase(), candidate_count: media.length};
    })()""".replace("AD_ID", json.dumps(ad_id))


def canonical_ad_library_url(value):
    parsed = urlparse(str(value or ""))
    query = parse_qs(parsed.query)
    ad_id = (query.get("id") or query.get("ad_archive_id") or [""])[0]
    if (parsed.scheme != "https" or parsed.hostname not in {"facebook.com", "www.facebook.com", "m.facebook.com"}
            or parsed.username or parsed.password or parsed.port not in {None, 443}
            or parsed.path.rstrip("/") not in {"/ads/library", "/ads/archive/render_ad"}
            or not ad_id.isdecimal()):
        raise ValueError("Necesito el enlace público exacto de un anuncio de Meta Ads Library con su ID.")
    return f"https://www.facebook.com/ads/library/?id={ad_id}"


def capture_public_ad_reference(payload, *, output_dir, run=None):
    url = canonical_ad_library_url(payload.get("source_reference_url") or payload.get("url"))
    binary = shutil.which("agent-browser")
    if not binary and run is None:
        return {"ok": False, "reason": "public_browser_unavailable", "source_reference_url": url}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    session = "admira-research-" + uuid.uuid4().hex[:12]
    screenshot = output_dir / (session + ".png")
    runner = run or subprocess.run
    browser_env = {key: os.environ[key] for key in (
        "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
        "AGENT_BROWSER_EXECUTABLE_PATH", "AGENT_BROWSER_IDLE_TIMEOUT_MS",
    ) if key in os.environ}

    def command(*args):
        result = runner([binary or "agent-browser", "--session", session, "--json", *args],
                        capture_output=True, text=True, timeout=35, check=False, env=browser_env)
        if result.returncode:
            raise ValueError("public_browser_read_failed")
        body = json.loads(result.stdout)
        if body.get("success") is False:
            raise ValueError("public_browser_read_failed")
        return body.get("data", body)

    try:
        command("open", url)
        location = command("get", "url")
        current = location.get("url") if isinstance(location, dict) else location
        if canonical_ad_library_url(current) != url:
            raise ValueError("public_ad_redirected")
        ad_id = parse_qs(urlparse(url).query)["id"][0]
        command("wait", "--text", ad_id)
        snapshot = command("snapshot")
        text = str(snapshot.get("snapshot") or snapshot.get("text") or "") if isinstance(snapshot, dict) else str(snapshot)
        if ad_id not in text:
            raise ValueError("public_ad_not_visible")
        expression = _creative_element_expression(ad_id)
        command("wait", "--fn", "Boolean(" + expression + ")")
        selected = command("eval", "JSON.stringify(" + expression + ")")
        media = json.loads(selected.get("result") or "null")
        if not isinstance(media, dict) or not media.get("selector"):
            raise ValueError("public_ad_creative_not_visible")
        command("screenshot", media["selector"], str(screenshot))
        if not screenshot.is_file():
            raise ValueError("public_ad_screenshot_missing")
        excerpt_start = max(0, text.index(ad_id) - 500)
        return {"ok": True, "source_reference_url": url, "file_path": str(screenshot),
                "research_observed_at": now_iso(), "page_excerpt": text[excerpt_start:excerpt_start + 5000],
                "media_type": media.get("media_type"),
                "visual_review_required": True,
                "instruction": "Inspect this actual media screenshot. Only proceed if it shows the selected ad creative clearly. A video capture is one still, not evidence of its motion or full narrative. Use it only for angle/structure; Ads Library does not establish conversions or ROAS."}
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                "source_reference_url": url}
    finally:
        try:
            command("close")
        except (ValueError, OSError, subprocess.TimeoutExpired):
            pass
