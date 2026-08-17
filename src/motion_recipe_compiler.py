#!/usr/bin/env python3
"""Compile bounded per-job Shotcraft adaptations into a Remotion entrypoint.

Only a deliberately small JSX/Remotion surface is accepted.  The generated
file lives inside the output job, cannot import modules, and never changes the
versioned product renderer or skill files.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from product_config import ROOT_DIR


VALIDATOR = ROOT_DIR / "scripts" / "validate-motion-recipe-source.mjs"
MOTION_GRAPHIC_COMPONENT = ROOT_DIR / "src" / "remotion" / "compositions" / "MotionGraphic.tsx"
MAX_SCENE_SOURCE_CHARS = 40_000
MAX_TOTAL_SOURCE_CHARS = 240_000


def _guard_accent_text_color(source):
    """Keep custom recipe text readable without stripping brand accents from shapes."""
    # `palette.accent` remains available for fills, borders, glows and other
    # decorative layers. A direct CSS `color:` use, however, is text and must
    # use the contrast-checked foreground generated for the scene background.
    return re.sub(
        r"(\bcolor\s*:\s*)palette\.accent\b",
        r"\1(palette.accentOnBackground || palette.text)",
        str(source or ""),
    )


class MotionRecipeCompileError(ValueError):
    """A compiled Shotcraft scene violates the bounded render contract."""


def validate_recipe_component_source(source):
    source = str(source or "").strip()
    if not source:
        raise MotionRecipeCompileError("Falta la adaptación visual de la receta seleccionada.")
    if len(source) > MAX_SCENE_SOURCE_CHARS:
        raise MotionRecipeCompileError("Una escena Shotcraft supera el tamaño seguro permitido.")
    if not VALIDATOR.is_file():
        raise MotionRecipeCompileError("Esta instalación no incluye el validador seguro de recetas Shotcraft.")
    try:
        result = subprocess.run(
            ["node", str(VALIDATOR)],
            input=json.dumps({"source": source, "max_chars": MAX_SCENE_SOURCE_CHARS}),
            capture_output=True,
            text=True,
            cwd=str(ROOT_DIR),
            timeout=20,
            check=False,
        )
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise MotionRecipeCompileError("No pude validar de forma segura la adaptación Shotcraft.") from exc
    if result.returncode != 0 or not payload.get("ok"):
        reason = re.sub(r"[^a-z0-9_-]+", "_", str(payload.get("reason") or "invalid_source").lower())[:80]
        detail = re.sub(r"\s+", " ", str(payload.get("detail") or "")).strip()[:180]
        suffix = f" ({detail})" if detail else ""
        raise MotionRecipeCompileError(f"La adaptación Shotcraft no pasó la validación segura: {reason}{suffix}.")
    return source


def _typescript_literal(value):
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _scene_component(index, source):
    return f"""
const CompiledRecipeScene{index}: React.FC<CompiledSceneContext> = ({{scene, brand}}) => {{
  const frame = useCurrentFrame();
  const {{fps, width, height, durationInFrames}} = useVideoConfig();
  const palette = brand.palette;
  const seededRandom = (seed: number | string) => random(`${{seed}}`);
  const ProtectedMedia: React.FC<{{assetIndex?: number; fit?: \"cover\" | \"contain\"; style?: React.CSSProperties}}> = ({{assetIndex, fit, style}}) => (
    <SafeMedia scene={{scene}} assetIndex={{assetIndex}} fit={{fit}} style={{style}} />
  );
  const BrandLogo: React.FC<{{style?: React.CSSProperties}}> = ({{style}}) => (
    brand.logo_src ? <Img src={{staticFile(brand.logo_src)}} style={{{{maxWidth: width * 0.24, maxHeight: height * 0.09, objectFit: \"contain\", ...style}}}} /> : null
  );
{source}
}};
"""


def build_generated_entrypoint(spec, job_dir):
    """Write a job-scoped entrypoint when one or more scenes are adapted."""
    scenes = spec.get("scenes") or []
    sources = [str(scene.get("compiled_recipe_source") or "").strip() for scene in scenes]
    if not any(sources):
        return None
    if sum(len(source) for source in sources) > MAX_TOTAL_SOURCE_CHARS:
        raise MotionRecipeCompileError("El storyboard Shotcraft completo supera el tamaño seguro permitido.")
    validated = {}
    for index, source in enumerate(sources):
        if source:
            validated[index] = validate_recipe_component_source(_guard_accent_text_color(source))

    defaults = dict(spec)
    defaults.pop("generated_entrypoint", None)
    component_import = MOTION_GRAPHIC_COMPONENT.resolve().with_suffix("").as_posix()
    component_defs = "\n".join(_scene_component(index, source) for index, source in validated.items())
    component_refs = ", ".join(
        f"CompiledRecipeScene{index}" if index in validated else "null" for index in range(len(scenes))
    )
    source = f"""/* Generated inside one Admira render job. Do not edit product code from here. */
import React from \"react\";
import {{Audio, Video}} from \"@remotion/media\";
import {{CameraMotionBlur}} from \"@remotion/motion-blur\";
import {{
  AbsoluteFill, Composition, Easing, Img, Sequence, interpolate,
  interpolateColors, random, registerRoot, spring, staticFile,
  useCurrentFrame, useVideoConfig,
}} from \"remotion\";
import {{SceneView, type MotionGraphicProps, type Scene}} from {_typescript_literal(component_import)};

type Brand = MotionGraphicProps[\"brand\"];
type CompiledSceneContext = {{scene: Scene; brand: Brand}};

const SafeMedia: React.FC<{{scene: Scene; assetIndex?: number; fit?: \"cover\" | \"contain\"; style?: React.CSSProperties}}> = ({{scene, assetIndex, fit, style}}) => {{
  const selected = Number.isInteger(assetIndex) && assetIndex! >= 0 ? scene.layer_media?.[assetIndex!] : null;
  const src = selected?.src || scene.media_src;
  const kind = selected?.kind || scene.media_kind;
  if (!src) return null;
  const shared = {{width: \"100%\", height: \"100%\", objectFit: fit || scene.media_fit, objectPosition: \"center\", ...style}} as React.CSSProperties;
  return kind === \"video\"
    ? <Video src={{staticFile(src)}} muted loop style={{shared}} />
    : <Img src={{staticFile(src)}} style={{shared}} />;
}};

{component_defs}

const compiledScenes: Array<React.FC<CompiledSceneContext> | null> = [{component_refs}];

const BrandedSceneShell: React.FC<{{scene: Scene; brand: Brand; index: number; total: number; Component: React.FC<CompiledSceneContext>}}> = ({{scene, brand, index, total, Component}}) => {{
  const {{width, height}} = useVideoConfig();
  return <AbsoluteFill style={{{{background: brand.palette.background, color: brand.palette.text, fontFamily: brand.font_family, overflow: \"hidden\"}}}}>
    <Component scene={{scene}} brand={{brand}} />
    <div style={{{{position: \"absolute\", left: \"5%\", right: \"5%\", bottom: \"3.5%\", display: \"flex\", alignItems: \"center\", justifyContent: \"space-between\", pointerEvents: \"none\"}}}}>
      <div style={{{{display: \"flex\", alignItems: \"center\", gap: 12}}}}>
        {{brand.logo_src ? <Img src={{staticFile(brand.logo_src)}} style={{{{maxWidth: width * 0.14, maxHeight: height * 0.035, objectFit: \"contain\"}}}} /> : null}}
        <span style={{{{fontSize: Math.min(width * 0.022, 24), fontWeight: 760, color: brand.palette.mutedText}}}}>{{brand.name}}</span>
      </div>
      <div style={{{{width: width * 0.13, height: 4, borderRadius: 8, background: brand.palette.text + \"22\", overflow: \"hidden\"}}}}>
        <div style={{{{width: `${{((index + 1) / Math.max(1, total)) * 100}}%`, height: \"100%\", background: brand.palette.accent}}}} />
      </div>
    </div>
  </AbsoluteFill>;
}};

const CompiledMotionGraphic: React.FC<MotionGraphicProps> = (props) => {{
  let cursor = 0;
  return <AbsoluteFill style={{{{background: props.brand.palette.background}}}}>
    {{props.scenes.map((scene, index) => {{
      const from = cursor;
      cursor += scene.duration_frames;
      const Component = compiledScenes[index];
      return <Sequence key={{`${{index}}-${{scene.title}}`}} from={{from}} durationInFrames={{scene.duration_frames}} premountFor={{props.fps}}>
        {{Component
          ? <BrandedSceneShell scene={{scene}} brand={{props.brand}} index={{index}} total={{props.scenes.length}} Component={{Component}} />
          : <SceneView scene={{scene}} palette={{props.brand.palette}} sceneIndex={{index}} totalScenes={{props.scenes.length}} motionProfile={{props.brand.motion_profile}} fontFamily={{props.brand.font_family}} brandName={{props.brand.name}} logoSrc={{props.brand.logo_src}} />}}
      </Sequence>;
    }})}}
    {{props.audio.src ? <Audio src={{staticFile(props.audio.src)}} loop volume={{props.audio.volume}} /> : null}}
  </AbsoluteFill>;
}};

const defaultProps = {_typescript_literal(defaults)} as unknown as MotionGraphicProps;
const Root: React.FC = () => <Composition
  id=\"AdmiraCompiledMotionGraphic\"
  component={{CompiledMotionGraphic}}
  durationInFrames={{Math.max(1, defaultProps.duration_frames)}}
  fps={{defaultProps.fps}}
  width={{Math.max(2, Math.round(defaultProps.width * defaultProps.render_scale))}}
  height={{Math.max(2, Math.round(defaultProps.height * defaultProps.render_scale))}}
  defaultProps={{defaultProps}}
  calculateMetadata={{({{props}}) => ({{
    durationInFrames: Math.max(1, Math.round(props.duration_frames || 1)),
    fps: [24, 25, 30].includes(props.fps) ? props.fps : 30,
    width: Math.max(2, Math.ceil(Math.round(props.width * (props.render_scale || 1)) / 2) * 2),
    height: Math.max(2, Math.ceil(Math.round(props.height * (props.render_scale || 1)) / 2) * 2),
    props,
  }})}}
/>;

registerRoot(Root);
"""
    entrypoint = Path(job_dir) / "generated-shotcraft-entry.tsx"
    entrypoint.write_text(source, encoding="utf-8")
    spec["generated_entrypoint"] = entrypoint.name
    spec["compiled_recipe_hash"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return entrypoint


__all__ = [
    "MAX_SCENE_SOURCE_CHARS",
    "MAX_TOTAL_SOURCE_CHARS",
    "MotionRecipeCompileError",
    "build_generated_entrypoint",
    "validate_recipe_component_source",
]
