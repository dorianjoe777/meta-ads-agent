#!/usr/bin/env python3
"""Content factory for daily Meta Ads Operator social assets."""
import argparse
import html
import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from local_store import now_iso, read_json, write_json


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "dashboard" / "data"
QUEUE_FILE = DATA_DIR / "content_queue.json"
CONTENT_ROOT = ROOT_DIR / "output" / "content-factory"
POSTIZ_INBOX = ROOT_DIR / "output" / "postiz" / "inbox"
REMOTION_QUEUE = CONTENT_ROOT / "remotion-queue"


CONTENT_PILLARS = [
    {
        "pillar": "daily_ads_clarity",
        "angle": "Deja de abrir Meta Ads a ciegas",
        "promise": "Ten una lectura diaria clara antes de tocar presupuesto, pausar anuncios o culparte por números que todavía no entiendes.",
    },
    {
        "pillar": "approval_based_automation",
        "angle": "IA como manager, no como botón mágico",
        "promise": "La automatización no debería gastar por ti. Primero explica, prepara acciones y te pide aprobación.",
    },
    {
        "pillar": "local_control",
        "angle": "Tu cuenta no tiene que vivir dentro de otro SaaS",
        "promise": "El operador corre en tu PC o VPS, con tus accesos bajo tu control y sin entregar la cuenta a una caja negra.",
    },
    {
        "pillar": "beginner_friendly",
        "angle": "Explicaciones simples para marketers ocupados",
        "promise": "ROAS, CPA, fatiga y presupuesto se convierten en próximos pasos claros, sin jerga innecesaria.",
    },
]


FORMATS = {
    "image": {"size": "1080x1350", "extension": "svg"},
    "motion": {"size": "1080x1920", "extension": "mp4"},
}

def slugify(value):
    replacements = str.maketrans("áéíóúñüÁÉÍÓÚÑÜ", "aeiounuAEIOUNU")
    value = str(value).translate(replacements)
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value[:80] or "content"

def load_queue():
    return read_json(QUEUE_FILE, {"items": [], "updated_at": ""})


def save_queue(queue):
    queue["updated_at"] = now_iso()
    write_json(QUEUE_FILE, queue)
    return queue


def asset_dir(batch_date):
    path = CONTENT_ROOT / batch_date
    path.mkdir(parents=True, exist_ok=True)
    return path


def content_id(batch_date, content_type, index, pillar):
    return f"{batch_date}_{content_type}_{index}_{slugify(pillar)}"


def wrap_words(value, limit, max_lines):
    words = str(value or "").split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def svg_text_lines(lines, x, y, dy, **attrs):
    attr_text = " ".join(f'{key.replace("_", "-")}="{html.escape(str(value))}"' for key, value in attrs.items())
    tspans = []
    for idx, line in enumerate(lines):
        offset = 0 if idx == 0 else dy
        tspans.append(f'<tspan x="{x}" dy="{offset}">{html.escape(line)}</tspan>')
    return f'<text x="{x}" y="{y}" {attr_text}>' + "".join(tspans) + "</text>"


def image_svg(item):
    title_lines = wrap_words(item["copy"]["headline"], 22, 4)
    body = html.escape(item["copy"]["body"])
    cta = html.escape(item["copy"]["cta"])
    eyebrow = html.escape(item["copy"]["eyebrow"])
    title = svg_text_lines(
        title_lines,
        112,
        330,
        78,
        fill="#f2f2ee",
        font_family="Inter, Arial, sans-serif",
        font_size="64",
        font_weight="900",
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" viewBox="0 0 1080 1350">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#230052"/>
      <stop offset="0.54" stop-color="#5B13B8"/>
      <stop offset="1" stop-color="#FFD0CB"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" x2="1">
      <stop offset="0" stop-color="#DCCBFF"/>
      <stop offset="0.55" stop-color="#FFD0CB"/>
      <stop offset="1" stop-color="#C7F1B7"/>
    </linearGradient>
  </defs>
  <rect width="1080" height="1350" fill="url(#bg)"/>
  <polygon points="0,0 380,0 0,320" fill="#DCCBFF" opacity="0.92"/>
  <polygon points="1080,0 1080,260 620,0" fill="#FFF9FF" opacity="0.9"/>
  <polygon points="0,1350 530,1350 0,1040" fill="#230052" opacity="0.86"/>
  <rect x="72" y="72" width="936" height="1206" rx="0" fill="#12051f" opacity="0.88" stroke="#DCCBFF" stroke-width="2"/>
  <rect x="72" y="72" width="936" height="14" rx="7" fill="url(#accent)"/>
  <text x="112" y="178" fill="#DCCBFF" font-family="Orbitron, Eurostile, Arial Black, sans-serif" font-size="34" font-weight="800">{eyebrow}</text>
  {title}
  <foreignObject x="112" y="700" width="820" height="260">
    <div xmlns="http://www.w3.org/1999/xhtml" style="color:#EEE7FF;font-family:Orbitron,Eurostile,Arial,sans-serif;font-size:34px;line-height:1.35;font-weight:700;">{body}</div>
  </foreignObject>
  <rect x="112" y="1050" width="540" height="82" rx="41" fill="#FFD0CB"/>
  <text x="150" y="1103" fill="#21004F" font-family="Orbitron, Eurostile, Arial Black, sans-serif" font-size="31" font-weight="900">{cta}</text>
  <text x="112" y="1218" fill="#DCCBFF" font-family="Orbitron, Eurostile, Arial Black, sans-serif" font-size="28" font-weight="700">Ad+ / Operador IA para Meta Ads</text>
</svg>
"""


def escape_ass(value):
    return str(value or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def ass_dialogue(start, end, style, text):
    return f"Dialogue: 0,{start},{end},{style},,0,0,0,,{escape_ass(text)}"


def motion_story(item):
    return [
        {
            "start": "0:00:00.00",
            "end": "0:00:04.20",
            "style": "Hook",
            "text": item["copy"]["headline"],
        },
        {
            "start": "0:00:04.20",
            "end": "0:00:10.80",
            "style": "Body",
            "text": item["copy"]["body"],
        },
        {
            "start": "0:00:10.80",
            "end": "0:00:18.40",
            "style": "Body",
            "text": item["strategy"]["mechanism"],
        },
        {
            "start": "0:00:18.40",
            "end": "0:00:24.00",
            "style": "Cta",
            "text": item["copy"]["cta"],
        },
    ]


def motion_ass(item):
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Brand,Arial,38,&H00A7C727,&H000000FF,&H00101315,&H00000000,1,0,0,0,100,100,0,0,1,0,0,7,86,86,132,1",
        "Style: Hook,Arial,78,&H00EEF2F2,&H000000FF,&H00101315,&H00000000,1,0,0,0,100,100,0,0,1,0,0,7,86,86,470,1",
        "Style: Body,Arial,48,&H00CFC9C4,&H000000FF,&H00101315,&H00000000,1,0,0,0,100,100,0,0,1,0,0,7,86,86,590,1",
        "Style: Cta,Arial,54,&H00121506,&H000000FF,&H00A7C727,&H00000000,1,0,0,0,100,100,0,0,3,28,0,2,86,86,230,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ass_dialogue("0:00:00.00", "0:00:24.00", "Brand", item["copy"]["eyebrow"]),
    ]
    for scene in motion_story(item):
        lines.append(ass_dialogue(scene["start"], scene["end"], scene["style"], scene["text"]))
    return "\n".join(lines) + "\n"


def render_motion_video(item, asset_path):
    spec_path = asset_path.with_suffix(".remotion.json")
    remotion_props = {
        "eyebrow": item["copy"]["eyebrow"],
        "headline": item["copy"]["headline"],
        "body": item["copy"]["body"],
        "mechanism": item["strategy"]["mechanism"],
        "cta": item["copy"]["cta"],
        "pillar": item["strategy"]["pillar"],
        "keyframeImage": item.get("keyframe_pipeline", {}).get("public_keyframe_path", ""),
    }
    write_json(spec_path, {"schema": "meta-ads-agent.remotion-props.v1", **remotion_props})
    error_path = asset_path.with_suffix(".render-error.txt")
    if error_path.exists():
        error_path.unlink()
    try:
        subprocess.run(
            ["npm", "run", "remotion:render-content", "--", str(spec_path), str(asset_path)],
            cwd=str(ROOT_DIR),
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if error_path.exists():
            error_path.unlink()
        return
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        details = [str(exc)]
        if isinstance(exc, subprocess.CalledProcessError):
            details.extend([exc.stdout or "", exc.stderr or ""])
        fallback_path = error_path
        fallback_path.write_text("\n".join(details), encoding="utf-8")

    scene_paths = render_motion_frames(item, asset_path.parent / f"{asset_path.stem}_frames")
    concat_path = asset_path.with_suffix(".concat.txt")
    concat_lines = []
    for scene, path in zip(motion_story(item), scene_paths):
        start_parts = [float(part) for part in scene["start"].split(":")]
        end_parts = [float(part) for part in scene["end"].split(":")]
        start = start_parts[0] * 3600 + start_parts[1] * 60 + start_parts[2]
        end = end_parts[0] * 3600 + end_parts[1] * 60 + end_parts[2]
        concat_lines.append(f"file '{path}'")
        concat_lines.append(f"duration {round(end - start, 2)}")
    concat_lines.append(f"file '{scene_paths[-1]}'")
    concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-t",
        "24",
        "-vf",
        "fps=30,format=yuv420p",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(asset_path),
    ]
    subprocess.run(cmd, cwd=str(ROOT_DIR), check=True, capture_output=True, text=True)


def load_font(size, bold=True):
    from PIL import ImageFont

    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Helvetica.ttf",
    ]
    for path in candidates:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_wrapped(draw, xy, text, font, fill, max_width, line_gap=12):
    words = str(text or "").split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def render_motion_frames(item, frame_dir):
    from PIL import Image, ImageDraw

    frame_dir.mkdir(parents=True, exist_ok=True)
    width, height = 1080, 1920
    brand_font = load_font(42)
    hook_font = load_font(86)
    body_font = load_font(52)
    cta_font = load_font(58)
    scene_paths = []
    scenes = motion_story(item)
    for idx, scene in enumerate(scenes, 1):
        image = Image.new("RGB", (width, height), "#101315")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((72, 96, 1008, 1780), radius=34, fill="#151a1e", outline="#343a42", width=3)
        draw.rounded_rectangle((112, 136, 968, 152), radius=8, fill="#27c7a7")
        draw.rectangle((540, 136, 968, 152), fill="#f4b740")
        draw.text((112, 230), item["copy"]["eyebrow"], font=brand_font, fill="#27c7a7")
        if scene["style"] == "Hook":
            draw_wrapped(draw, (112, 520), scene["text"], hook_font, "#f2f2ee", 820, line_gap=20)
        elif scene["style"] == "Cta":
            draw_wrapped(draw, (112, 560), "¿Qué harías si un manager revisara tus anuncios cada mañana?", body_font, "#c4c9cf", 820, line_gap=18)
            draw.rounded_rectangle((112, 1240, 760, 1340), radius=50, fill="#27c7a7")
            draw.text((154, 1262), scene["text"], font=cta_font, fill="#061512")
        else:
            draw_wrapped(draw, (112, 560), scene["text"], body_font, "#f2f2ee", 820, line_gap=18)
        draw.text((112, 1660), "Operador IA para Meta Ads", font=brand_font, fill="#777f89")
        progress_x = 112 + int((idx / len(scenes)) * 856)
        draw.rounded_rectangle((112, 1708, 968, 1724), radius=8, fill="#2b3036")
        draw.rounded_rectangle((112, 1708, progress_x, 1724), radius=8, fill="#27c7a7")
        path = frame_dir / f"scene_{idx:02d}.png"
        image.save(path)
        scene_paths.append(path)
    return scene_paths


def build_item(batch_date, content_type, index, pillar):
    item_id = content_id(batch_date, content_type, index, pillar["pillar"])
    hook = pillar["angle"]
    body = pillar["promise"]
    cta = "Pide una lectura diaria" if content_type == "image" else "Mira cómo trabaja"
    item = {
        "id": item_id,
        "type": content_type,
        "status": "needs_review",
        "batch_date": batch_date,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "platforms": ["instagram", "facebook", "linkedin"],
        "postiz_ready": False,
        "comments": [],
        "copy": {
            "eyebrow": "Meta Ads sin ansiedad",
            "headline": hook,
            "body": body,
            "caption": f"{hook}. {body} Esto no va de automatizar a ciegas: va de operar con más claridad, más criterio y mejores aprobaciones.",
            "cta": cta,
        },
        "strategy": {
            "pillar": pillar["pillar"],
            "buyer_stage": "problem-aware",
            "mechanism": "El agente revisa resultados, explica lo importante y deja las acciones listas para aprobación.",
        },
        "asset_path": "",
        "postiz_path": "",
    }
    out_dir = asset_dir(batch_date)
    if content_type == "image":
        asset_path = out_dir / f"{item_id}.svg"
        asset_path.write_text(image_svg(item), encoding="utf-8")
    else:
        asset_path = out_dir / f"{item_id}.mp4"
        render_motion_video(item, asset_path)
    item["asset_path"] = str(asset_path)
    write_json(out_dir / f"{item_id}.meta.json", item)
    return item


def generate_batch(batch_date=None, images=2, motions=2, force=False):
    batch_date = batch_date or date.today().isoformat()
    queue = load_queue()
    existing = {item["id"]: item for item in queue.get("items", [])}
    new_items = []
    plan = [("image", images), ("motion", motions)]
    cursor = 0
    for content_type, count in plan:
        for idx in range(count):
            pillar = CONTENT_PILLARS[cursor % len(CONTENT_PILLARS)]
            cursor += 1
            item = build_item(batch_date, content_type, idx + 1, pillar)
            if item["id"] in existing and force:
                queue["items"] = [item if old.get("id") == item["id"] else old for old in queue.get("items", [])]
                new_items.append(item)
            elif item["id"] not in existing:
                queue["items"].insert(0, item)
                new_items.append(item)
    save_queue(queue)
    return {"created": len(new_items), "items": new_items, "queue_file": str(QUEUE_FILE)}


def find_item(queue, item_id):
    for item in queue.get("items", []):
        if item.get("id") == item_id:
            return item
    raise ValueError(f"Unknown content item: {item_id}")


def add_comment(item_id, comment, status="changes_requested"):
    queue = load_queue()
    item = find_item(queue, item_id)
    item.setdefault("comments", []).append({"at": now_iso(), "comment": comment})
    item["status"] = status
    item["updated_at"] = now_iso()
    save_queue(queue)
    return item


def approve_item(item_id):
    queue = load_queue()
    item = find_item(queue, item_id)
    source = Path(item.get("asset_path", ""))
    if not source.exists():
        raise ValueError(f"Missing asset: {source}")
    if item.get("type") == "motion":
        destination_dir = POSTIZ_INBOX
        item["status"] = "approved_for_postiz"
        item["postiz_ready"] = True
    else:
        destination_dir = POSTIZ_INBOX
        item["status"] = "approved_for_postiz"
        item["postiz_ready"] = True
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    shutil.copy2(source, destination)
    sidecar = destination.with_suffix(destination.suffix + ".meta.json")
    write_json(sidecar, item)
    item["postiz_path"] = str(destination)
    item["approved_at"] = now_iso()
    item["updated_at"] = now_iso()
    save_queue(queue)
    return item


def list_items(status=None):
    queue = load_queue()
    items = queue.get("items", [])
    if status:
        items = [item for item in items if item.get("status") == status]
    return {"items": items, "count": len(items), "queue_file": str(QUEUE_FILE)}


def main():
    parser = argparse.ArgumentParser(description="Generate and review social content assets.")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="Generate a daily content batch")
    generate.add_argument("--date", default="")
    generate.add_argument("--images", type=int, default=2)
    generate.add_argument("--motions", type=int, default=2)
    generate.add_argument("--force", action="store_true", help="Regenerate existing ids for the date")
    list_parser = sub.add_parser("list", help="List content queue items")
    list_parser.add_argument("--status", default="")
    approve = sub.add_parser("approve", help="Approve one item")
    approve.add_argument("item_id")
    comment = sub.add_parser("comment", help="Leave a revision comment")
    comment.add_argument("item_id")
    comment.add_argument("comment")
    args = parser.parse_args()

    if args.command == "generate":
        result = generate_batch(args.date or None, args.images, args.motions, force=args.force)
    elif args.command == "list":
        result = list_items(args.status or None)
    elif args.command == "approve":
        result = approve_item(args.item_id)
    elif args.command == "comment":
        result = add_comment(args.item_id, args.comment)
    else:
        result = {"error": "Unknown command"}
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
