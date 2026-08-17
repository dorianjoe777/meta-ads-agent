import React from "react";
import {Audio, Video} from "@remotion/media";
import {
  AbsoluteFill,
  Easing,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {RECIPE_COMPONENTS, ShotAccentLayers, ShotRecipeScene, ShotTransitionOverlay} from "../shotcraft/ShotRecipes";

export type Palette = {
  background: string;
  surface: string;
  primary: string;
  accent: string;
  highlight: string;
  text: string;
  mutedText: string;
  surfaceText: string;
  surfaceMutedText: string;
  primaryText: string;
  accentText: string;
  accentOnBackground: string;
  highlightText: string;
  emphasisText: string;
};

export type Scene = {
  type: string;
  eyebrow: string;
  title: string;
  body: string;
  items: string[];
  stat: string;
  left: string;
  right: string;
  quote: string;
  attribution: string;
  media_src: string;
  media_kind: string;
  layer_media: Array<{src: string; kind: string}>;
  media_fit: "cover" | "contain";
  duration_seconds: number;
  duration_frames: number;
  motion: string;
  shot_recipe: string;
  shot_recipes: string[];
  shot_recipe_refs?: Array<Record<string, string>>;
  compiled_recipe_source?: string;
  transition: string;
};

export type MotionGraphicProps = {
  schema: string;
  job_id: string;
  objective: string;
  template: string;
  aspect_ratio: string;
  width: number;
  height: number;
  fps: number;
  duration_frames: number;
  duration_seconds: number;
  quality: string;
  render_scale: number;
  brand: {
    name: string;
    offer: string;
    audience: string;
    tone: string;
    visual_style: string;
    motion_style: string;
    energy: string;
    motion_profile: {
      preset: string;
      entry_seconds: number;
      travel_px: number;
      media_scale: number;
      stagger_seconds: number;
      decor_drift: number;
    };
    font_family: string;
    typography_direction: string;
    logo_src: string;
    palette: Palette;
  };
  product: {id: string; guide: string; name: string};
  scenes: Scene[];
  audio: {src: string; volume: number};
  assets: Array<{src: string; preservation: string}>;
  asset_policy: string;
};

const clamp = {
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

const exit = (frame: number, duration: number, fps: number) =>
  interpolate(frame, [duration - 0.45 * fps, duration - 1], [1, 0], {
    ...clamp,
    easing: Easing.bezier(0.7, 0, 0.84, 0),
  });

const fontSizeFor = (text: string, base: number) => {
  const length = (text || "").length;
  if (length > 145) return base * 0.56;
  if (length > 95) return base * 0.68;
  if (length > 58) return base * 0.82;
  return base;
};

type MotionProfile = MotionGraphicProps["brand"]["motion_profile"];

const profileEasing = (preset: string) => {
  if (preset === "premium") return Easing.bezier(0.4, 0, 0.6, 1);
  if (preset === "calm") return Easing.inOut(Easing.ease);
  if (preset === "playful") return Easing.bezier(0.25, 0.9, 0.35, 1);
  return Easing.bezier(0.16, 1, 0.3, 1);
};

const Decor: React.FC<{palette: Palette; sceneIndex: number; motionProfile: MotionProfile}> = ({palette, sceneIndex, motionProfile}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, width, height} = useVideoConfig();
  const drift = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [-motionProfile.decor_drift * width, motionProfile.decor_drift * width], clamp);
  const rotation = (sceneIndex % 2 === 0 ? 1 : -1) * interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [-8, 8], clamp);
  return (
    <AbsoluteFill style={{overflow: "hidden"}}>
      <div style={{position: "absolute", width: width * 0.72, height: width * 0.72, borderRadius: "50%", background: palette.primary, opacity: 0.16, filter: `blur(${Math.round(width * 0.09)}px)`, left: -width * 0.28 + drift, top: -width * 0.22}} />
      <div style={{position: "absolute", width: width * 0.58, height: width * 0.58, borderRadius: width * 0.12, border: `${Math.max(2, width * 0.006)}px solid ${palette.accent}`, opacity: 0.18, right: -width * 0.3 - drift, bottom: -width * 0.1, rotate: `${rotation}deg`}} />
      <div style={{position: "absolute", inset: 0, opacity: 0.08, backgroundImage: `linear-gradient(${palette.text} 1px, transparent 1px), linear-gradient(90deg, ${palette.text} 1px, transparent 1px)`, backgroundSize: `${Math.max(26, width * 0.075)}px ${Math.max(26, width * 0.075)}px`}} />
    </AbsoluteFill>
  );
};

const MediaFrame: React.FC<{scene: Scene; palette: Palette; progress: number; motionProfile: MotionProfile; side?: boolean}> = ({scene, palette, progress, motionProfile, side = false}) => {
  if (!scene.media_src) return null;
  return (
    <div style={{position: "absolute", left: side ? "54%" : "8%", right: "8%", top: side ? "20%" : "10%", bottom: side ? "20%" : "46%", borderRadius: 34, overflow: "hidden", border: `2px solid ${palette.accent}66`, background: palette.surface, opacity: progress, scale: motionProfile.media_scale + progress * (1 - motionProfile.media_scale), boxShadow: `0 28px 80px ${palette.background}AA`}}>
      {scene.media_kind === "video" ? (
        <Video src={staticFile(scene.media_src)} muted loop style={{width: "100%", height: "100%", objectFit: scene.media_fit, objectPosition: "center"}} />
      ) : (
        <Img src={staticFile(scene.media_src)} style={{width: "100%", height: "100%", objectFit: scene.media_fit, objectPosition: "center"}} />
      )}
    </div>
  );
};

const Eyebrow: React.FC<{text: string; palette: Palette; progress: number}> = ({text, palette, progress}) => text ? (
  <div style={{fontSize: 30, fontWeight: 800, letterSpacing: 4, textTransform: "uppercase", color: palette.accentOnBackground || palette.text, opacity: progress, translate: `0 ${24 * (1 - progress)}px`, marginBottom: 22}}>{text}</div>
) : null;

const recipeSceneType = (scene: Scene) => ({
  "editorial-reveal": "hook",
  "card-cascade": "list",
  "step-stack": "steps",
  "stat-focus": "stat",
  "split-compare": "comparison",
  "quote-frame": "quote",
  "spotlight-media": "media",
  "cta-lockup": "cta",
}[scene.motion] || scene.type);

export const SceneView: React.FC<{scene: Scene; palette: Palette; sceneIndex: number; totalScenes: number; motionProfile: MotionProfile; fontFamily: string; brandName: string; logoSrc: string; transparentBackground?: boolean}> = ({scene, palette, sceneIndex, totalScenes, motionProfile, fontFamily, brandName, logoSrc, transparentBackground = false}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames, width, height} = useVideoConfig();
  const reveal = (delay = 0) => interpolate(frame, [delay, delay + motionProfile.entry_seconds * fps], [0, 1], {...clamp, easing: profileEasing(motionProfile.preset)});
  const p = reveal();
  const fade = p * exit(frame, durationInFrames, fps);
  const effectiveType = recipeSceneType(scene);
  const isSideMedia = Boolean(scene.media_src && ["hook", "statement", "comparison", "cta"].includes(effectiveType));
  const titleSize = fontSizeFor(scene.title, Math.min(width * 0.105, height * 0.068));
  const contentWidth = isSideMedia ? "45%" : "84%";
  const textTop = isSideMedia ? "18%" : "17%";
  const stagger = motionProfile.stagger_seconds * fps;

  const commonTitle = scene.title ? (
    <div style={{fontSize: titleSize, lineHeight: 0.98, fontWeight: 850, letterSpacing: -titleSize * 0.04, color: palette.text, opacity: reveal(0.08 * fps), translate: `0 ${motionProfile.travel_px * (1 - reveal(0.08 * fps))}px`, textWrap: "balance" as never}}>{scene.title}</div>
  ) : null;

  const commonBody = scene.body ? (
    <div style={{fontSize: Math.min(width * 0.046, 46), lineHeight: 1.32, fontWeight: 500, color: palette.mutedText, marginTop: 28, opacity: reveal(0.22 * fps), translate: `0 ${motionProfile.travel_px * 0.65 * (1 - reveal(0.22 * fps))}px`}}>{scene.body}</div>
  ) : null;

  const curatedRecipe = scene.shot_recipe && RECIPE_COMPONENTS.has(scene.shot_recipe) ? (
    <ShotRecipeScene scene={scene} palette={palette} fontFamily={fontFamily} brandName={brandName} logoSrc={logoSrc}/>
  ) : null;

  const main = curatedRecipe || (() => {
    if (effectiveType === "list" || effectiveType === "steps") {
      return (
        <div style={{position: "absolute", left: "8%", right: "8%", top: "13%", bottom: "12%", display: "flex", flexDirection: "column", justifyContent: "center"}}>
          <Eyebrow text={scene.eyebrow} palette={palette} progress={p}/>
          {commonTitle}
          <div style={{display: "grid", gap: 16, marginTop: 34}}>
            {scene.items.map((item, index) => {
              const itemP = reveal(0.22 * fps + index * stagger);
              return <div key={`${item}-${index}`} style={{display: "grid", gridTemplateColumns: "58px 1fr", gap: 18, alignItems: "center", padding: "20px 24px", borderRadius: 24, background: palette.surface, border: `1px solid ${palette.text}18`, opacity: itemP, translate: `${48 * (1 - itemP)}px 0`}}><div style={{width: 50, height: 50, display: "grid", placeItems: "center", borderRadius: 18, background: index % 2 ? palette.accent : palette.primary, color: palette.background, fontSize: 24, fontWeight: 900}}>{effectiveType === "steps" ? index + 1 : "•"}</div><div style={{fontSize: Math.min(width * 0.042, 42), lineHeight: 1.15, fontWeight: 680, color: palette.text}}>{item}</div></div>;
            })}
          </div>
        </div>
      );
    }
    if (effectiveType === "stat") {
      const statP = reveal(0.12 * fps);
      return <div style={{position: "absolute", inset: "13% 8%", display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center"}}><Eyebrow text={scene.eyebrow} palette={palette} progress={p}/><div style={{fontSize: Math.min(width * 0.24, 230), lineHeight: 0.88, fontWeight: 900, letterSpacing: -10, color: palette.highlight, opacity: statP, scale: 0.72 + statP * 0.28}}>{scene.stat || scene.title}</div>{scene.stat && commonTitle}<div style={{maxWidth: "82%"}}>{commonBody}</div></div>;
    }
    if (effectiveType === "comparison") {
      const splitP = reveal(0.16 * fps);
      return <div style={{position: "absolute", inset: "10% 7%", display: "flex", flexDirection: "column", justifyContent: "center"}}><Eyebrow text={scene.eyebrow} palette={palette} progress={p}/>{commonTitle}<div style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginTop: 42, opacity: splitP}}><div style={{padding: 30, minHeight: height * 0.26, borderRadius: 28, background: palette.surface, color: palette.mutedText, display: "flex", alignItems: "flex-end", fontSize: Math.min(width * 0.044, 44), lineHeight: 1.18, translate: `${-48 * (1 - splitP)}px 0`}}>{scene.left}</div><div style={{padding: 30, minHeight: height * 0.26, borderRadius: 28, background: palette.primary, color: palette.text, display: "flex", alignItems: "flex-end", fontSize: Math.min(width * 0.044, 44), lineHeight: 1.18, fontWeight: 760, translate: `${48 * (1 - splitP)}px 0`}}>{scene.right}</div></div></div>;
    }
    if (effectiveType === "quote") {
      return <div style={{position: "absolute", inset: "12% 9%", display: "flex", flexDirection: "column", justifyContent: "center"}}><div style={{fontSize: Math.min(width * 0.18, 180), lineHeight: 0.7, color: palette.accent, opacity: p}}>“</div><div style={{fontSize: fontSizeFor(scene.quote || scene.title, Math.min(width * 0.075, 74)), lineHeight: 1.08, fontWeight: 760, color: palette.text, opacity: reveal(0.08 * fps), translate: `0 ${motionProfile.travel_px * (1 - p)}px`}}>{scene.quote || scene.title}</div><div style={{fontSize: Math.min(width * 0.038, 38), marginTop: 30, color: palette.mutedText, opacity: reveal(0.25 * fps)}}>{scene.attribution}</div></div>;
    }
    if (effectiveType === "media" && scene.media_src) {
      return <><MediaFrame scene={scene} palette={palette} progress={p} motionProfile={motionProfile}/><div style={{position: "absolute", left: "8%", right: "8%", bottom: "9%"}}><Eyebrow text={scene.eyebrow} palette={palette} progress={p}/>{commonTitle}{commonBody}</div></>;
    }
    return <><MediaFrame scene={scene} palette={palette} progress={p} motionProfile={motionProfile} side={isSideMedia}/><div style={{position: "absolute", left: "8%", width: contentWidth, top: textTop, bottom: "12%", display: "flex", flexDirection: "column", justifyContent: "center"}}><Eyebrow text={scene.eyebrow} palette={palette} progress={p}/>{commonTitle}{commonBody}</div></>;
  })();

  return (
    <AbsoluteFill style={{background: transparentBackground ? "transparent" : palette.background, color: palette.text, fontFamily, overflow: "hidden", opacity: fade}}>
      {transparentBackground ? null : <Decor palette={palette} sceneIndex={sceneIndex} motionProfile={motionProfile}/>}
      {main}
      <ShotAccentLayers recipes={scene.shot_recipes || []} palette={palette} scene={scene}/>
      <ShotTransitionOverlay transition={scene.transition || ""} palette={palette}/>
      <div style={{position: "absolute", left: "8%", right: "8%", bottom: "4.5%", display: "flex", justifyContent: "space-between", alignItems: "center", opacity: reveal(0.34 * fps)}}>
        <div style={{display: "flex", alignItems: "center", gap: 14}}>{logoSrc ? <Img src={staticFile(logoSrc)} style={{maxWidth: width * 0.16, maxHeight: height * 0.04, objectFit: "contain"}}/> : null}<span style={{fontSize: Math.min(width * 0.027, 27), fontWeight: 750, color: palette.mutedText}}>{brandName}</span></div>
        <div style={{width: width * 0.15, height: 5, borderRadius: 9, background: palette.text + "22", overflow: "hidden"}}><div style={{width: `${((sceneIndex + 1) / Math.max(1, totalScenes)) * 100}%`, height: "100%", background: palette.accent}}/></div>
      </div>
    </AbsoluteFill>
  );
};

export const MotionGraphic: React.FC<MotionGraphicProps> = (props) => {
  let cursor = 0;
  return (
    <AbsoluteFill style={{background: props.brand.palette.background}}>
      {props.scenes.map((scene, index) => {
        const from = cursor;
        cursor += scene.duration_frames;
        return (
          <Sequence key={`${index}-${scene.title}`} name={`Scene ${index + 1}: ${scene.type}`} from={from} durationInFrames={scene.duration_frames} premountFor={props.fps}>
            <SceneView scene={scene} palette={props.brand.palette} sceneIndex={index} totalScenes={props.scenes.length} motionProfile={props.brand.motion_profile} fontFamily={props.brand.font_family} brandName={props.brand.name} logoSrc={props.brand.logo_src}/>
          </Sequence>
        );
      })}
      {props.audio.src ? <Audio src={staticFile(props.audio.src)} loop volume={props.audio.volume}/> : null}
    </AbsoluteFill>
  );
};
