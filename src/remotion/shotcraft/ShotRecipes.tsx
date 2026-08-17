/*
 * Parametric adaptations of motion patterns published by video-shotcraft.
 * Upstream: https://github.com/Vincentwei1021/video-shotcraft
 * License: Apache-2.0. Modified for Admira's bounded, brand-aware data schema,
 * arbitrary aspect ratios, and buyer-owned media preservation rules.
 */
import React from "react";
import {Video} from "@remotion/media";
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

export type ShotPalette = {
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

export type ShotScene = {
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
  media_fit: "cover" | "contain";
  duration_frames: number;
  shot_recipe: string;
};

const clamp = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};
const ease = Easing.bezier(0.16, 1, 0.3, 1);

const reveal = (frame: number, from: number, length = 18) =>
  interpolate(frame, [from, from + length], [0, 1], {...clamp, easing: ease});

const splitWords = (value: string) => (value || "").trim().split(/\s+/).filter(Boolean);

const ShotMedia: React.FC<{scene: ShotScene; style?: React.CSSProperties}> = ({scene, style}) => {
  if (!scene.media_src) return null;
  if (scene.media_kind === "video") return <Video src={staticFile(scene.media_src)} muted loop style={{width: "100%", height: "100%", objectFit: scene.media_fit, ...style}}/>;
  return <Img src={staticFile(scene.media_src)} style={{width: "100%", height: "100%", objectFit: scene.media_fit, ...style}}/>;
};

export const DigitRoll: React.FC<{value: string; delay?: number; fontSize: number; color: string}> = ({value, delay = 0, fontSize, color}) => {
  const frame = useCurrentFrame();
  const digits = "0123456789";
  const lineHeight = fontSize * 1.04;
  return (
    <span style={{display: "inline-flex", overflow: "hidden", height: lineHeight}}>
      {String(value).split("").map((character, index) => {
        const target = digits.indexOf(character);
        if (target < 0) return <span key={index} style={{fontSize, lineHeight: `${lineHeight}px`, color}}>{character}</span>;
        const progress = interpolate(frame, [delay + index * 3, delay + index * 3 + 24], [0, 1], {...clamp, easing: ease});
        const offset = (10 + target) * progress * lineHeight;
        return (
          <span key={index} style={{display: "inline-block", height: lineHeight}}>
            <span style={{display: "block", transform: `translateY(${-offset}px)`}}>
              {(digits + digits).split("").map((digit, digitIndex) => (
                <span key={digitIndex} style={{display: "block", fontSize, lineHeight: `${lineHeight}px`, color, fontVariantNumeric: "tabular-nums"}}>{digit}</span>
              ))}
            </span>
          </span>
        );
      })}
    </span>
  );
};

const BrandInkOpen: React.FC<{scene: ShotScene; palette: ShotPalette; fontFamily: string}> = ({scene, palette, fontFamily}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const words = splitWords(scene.title);
  const cross = reveal(frame, 0, 16);
  return (
    <AbsoluteFill style={{background: palette.surface, color: palette.text, justifyContent: "center", alignItems: "center", fontFamily}}>
      <div style={{position: "absolute", left: "10%", right: "10%", top: "50%", height: Math.max(2, width * 0.004), background: palette.accent, transform: `scaleX(${cross})`}}/>
      <div style={{position: "absolute", top: "12%", bottom: "12%", left: "50%", width: Math.max(2, width * 0.004), background: palette.accent, transform: `scaleY(${cross})`}}/>
      <div style={{zIndex: 2, background: palette.surface, padding: `${height * 0.045}px ${width * 0.07}px`, textAlign: "center", maxWidth: "82%"}}>
        <div style={{fontSize: Math.min(width * 0.105, height * 0.08), lineHeight: 0.98, fontWeight: 900, letterSpacing: "-0.05em"}}>
          {words.map((word, index) => {
            const p = reveal(frame, 7 + index * 4, 10);
            return <span key={`${word}-${index}`} style={{display: "inline-block", marginRight: "0.22em", opacity: p, transform: `scale(${1.35 - p * 0.35})`, filter: `blur(${(1 - p) * 5}px)`, color: index === words.length - 1 ? palette.emphasisText : palette.surfaceText}}>{word}</span>;
          })}
        </div>
        <div style={{fontSize: Math.min(width * 0.035, 34), marginTop: 28, color: palette.surfaceMutedText, opacity: reveal(frame, 18, 12), letterSpacing: "0.12em", textTransform: "uppercase"}}>{scene.eyebrow || scene.body}</div>
      </div>
    </AbsoluteFill>
  );
};

const PaperTitleCard: React.FC<{scene: ShotScene; palette: ShotPalette}> = ({scene, palette}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const words = splitWords(scene.title);
  const underline = reveal(frame, 14, 18);
  return (
    <AbsoluteFill style={{background: `radial-gradient(circle at 50% 40%, ${palette.surface}, ${palette.background})`, color: palette.text, justifyContent: "center", alignItems: "center"}}>
      <div style={{width: "82%", textAlign: "center"}}>
        <div style={{fontFamily: "Georgia, 'Times New Roman', serif", fontSize: Math.min(width * 0.11, height * 0.085), lineHeight: 1.04, fontWeight: 650}}>
          {words.map((word, index) => {
            const p = reveal(frame, 3 + index * 4, 10);
            return <span key={`${word}-${index}`} style={{display: "inline-block", marginRight: "0.25em", opacity: p, transform: `scale(${1.22 - p * 0.22})`, filter: `blur(${(1 - p) * 6}px)`, fontStyle: index === words.length - 1 ? "italic" : "normal", color: index === words.length - 1 ? palette.emphasisText : palette.text}}>{word}</span>;
          })}
        </div>
        <div style={{height: Math.max(4, height * 0.004), width: width * 0.20, margin: `${height * 0.035}px auto`, borderRadius: 4, background: palette.highlight, transform: `scaleX(${underline})`}}/>
        <div style={{fontFamily: "ui-monospace, Menlo, monospace", fontSize: Math.min(width * 0.028, 28), letterSpacing: "0.12em", textTransform: "uppercase", color: palette.mutedText, opacity: reveal(frame, 18, 12)}}>{scene.body || scene.eyebrow}</div>
      </div>
    </AbsoluteFill>
  );
};

const PageCam25D: React.FC<{scene: ShotScene; palette: ShotPalette}> = ({scene, palette}) => {
  const frame = useCurrentFrame();
  const {width, height, durationInFrames} = useVideoConfig();
  const p = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], {...clamp, easing: Easing.inOut(Easing.ease)});
  const scale = 1.05 + p * 0.22;
  const rotX = 10 - p * 5;
  const rotY = -9 + p * 13;
  const translateX = (0.5 - p) * width * 0.08;
  const translateY = (0.5 - p) * height * 0.05;
  return (
    <AbsoluteFill style={{background: palette.background, perspective: `${Math.max(width, height) * 1.3}px`, overflow: "hidden"}}>
      <div style={{position: "absolute", inset: "7%", borderRadius: Math.min(width, height) * 0.045, overflow: "hidden", background: palette.surface, transform: `translate3d(${translateX}px, ${translateY}px, 0) rotateX(${rotX}deg) rotateY(${rotY}deg) scale(${scale})`, transformStyle: "preserve-3d", boxShadow: `0 ${height * 0.04}px ${height * 0.09}px #0009`}}>
        <ShotMedia scene={scene}/>
      </div>
      <div style={{position: "absolute", inset: 0, background: "linear-gradient(180deg, transparent 35%, rgba(0,0,0,.72) 100%)"}}/>
      <div style={{position: "absolute", left: "8%", right: "8%", bottom: "9%", color: palette.text, opacity: reveal(frame, 12, 16)}}>
        <div style={{fontSize: Math.min(width * 0.075, height * 0.06), lineHeight: 1, fontWeight: 850}}>{scene.title}</div>
        <div style={{fontSize: Math.min(width * 0.034, 34), color: palette.mutedText, marginTop: 18}}>{scene.body}</div>
      </div>
    </AbsoluteFill>
  );
};

const CrashZoomPunch: React.FC<{scene: ShotScene; palette: ShotPalette}> = ({scene, palette}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const p = interpolate(frame, [0, 8, 15], [0, 1.12, 1], {...clamp, easing: ease});
  return (
    <AbsoluteFill style={{background: palette.background, overflow: "hidden"}}>
      {scene.media_src ? <div style={{position: "absolute", inset: 0, transform: `scale(${0.74 + p * 0.26})`, filter: `blur(${Math.max(0, (1 - p) * 8)}px)`}}><ShotMedia scene={scene}/></div> : null}
      <div style={{position: "absolute", inset: 0, background: scene.media_src ? "#0006" : palette.background}}/>
      <div style={{position: "absolute", inset: "12% 8%", display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center", transform: `scale(${0.58 + p * 0.42})`, opacity: Math.min(1, p)}}>
        <div style={{fontSize: Math.min(width * 0.13, height * 0.1), lineHeight: 0.9, fontWeight: 950, color: palette.text, textTransform: "uppercase", textShadow: `0 8px 30px ${palette.background}`}}>{scene.title}</div>
        <div style={{fontSize: Math.min(width * 0.038, 38), marginTop: 24, color: palette.accentOnBackground || palette.text}}>{scene.body}</div>
      </div>
    </AbsoluteFill>
  );
};

const CardStack: React.FC<{scene: ShotScene; palette: ShotPalette; numbered?: boolean}> = ({scene, palette, numbered = false}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const items = (scene.items.length ? scene.items : [scene.body]).filter(Boolean).slice(0, 6);
  return (
    <AbsoluteFill style={{background: palette.background, color: palette.text, padding: "10% 8%"}}>
      <div style={{fontSize: Math.min(width * 0.072, height * 0.055), fontWeight: 860, lineHeight: 1}}>{scene.title}</div>
      <div style={{position: "relative", flex: 1, marginTop: "6%"}}>
        {items.map((item, index) => {
          const p = reveal(frame, 5 + index * 5, 15);
          const y = index * Math.min(height * 0.10, 120);
          return <div key={`${item}-${index}`} style={{position: "absolute", left: 0, right: 0, top: y, minHeight: Math.min(height * 0.12, 150), display: "grid", gridTemplateColumns: "auto 1fr", alignItems: "center", gap: 22, padding: "20px 26px", borderRadius: 26, background: index % 2 ? palette.surface : palette.primary, color: index % 2 ? palette.surfaceText : palette.primaryText, border: `1px solid ${palette.text}22`, boxShadow: "0 18px 45px #0004", opacity: p, transform: `translate3d(${(1 - p) * (index % 2 ? -width : width)}px, ${(1 - p) * height * 0.15}px, ${-index * 8}px) rotateZ(${(1 - p) * (index % 2 ? -7 : 7)}deg)`}}>
            <div style={{fontSize: Math.min(width * 0.034, 34), fontWeight: 900}}>{numbered ? index + 1 : "•"}</div><div style={{fontSize: Math.min(width * 0.041, 41), lineHeight: 1.13, fontWeight: 700}}>{item}</div>
          </div>;
        })}
      </div>
    </AbsoluteFill>
  );
};

const OdometerStat: React.FC<{scene: ShotScene; palette: ShotPalette}> = ({scene, palette}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const pulse = interpolate(frame, [18, 30, 42], [0.92, 1.05, 1], clamp);
  return <AbsoluteFill style={{background: palette.background, color: palette.text, justifyContent: "center", alignItems: "center", textAlign: "center"}}><div style={{fontSize: Math.min(width * 0.026, 28), letterSpacing: "0.14em", textTransform: "uppercase", color: palette.emphasisText}}>{scene.eyebrow}</div><div style={{transform: `scale(${pulse})`, margin: `${height * 0.035}px 0`}}><DigitRoll value={scene.stat || scene.title || "0"} delay={2} fontSize={Math.min(width * 0.22, height * 0.17)} color={palette.emphasisText}/></div><div style={{fontSize: Math.min(width * 0.055, 55), lineHeight: 1.05, fontWeight: 760, maxWidth: "80%"}}>{scene.stat ? scene.title : scene.body}</div></AbsoluteFill>;
};

const BeforeAfterSlider: React.FC<{scene: ShotScene; palette: ShotPalette}> = ({scene, palette}) => {
  const frame = useCurrentFrame();
  const {width, height, durationInFrames} = useVideoConfig();
  const p = interpolate(frame, [4, Math.max(5, durationInFrames * 0.72)], [0.16, 0.76], {...clamp, easing: Easing.bezier(0.2, 0.8, 0.3, 1)});
  return <AbsoluteFill style={{background: palette.background, color: palette.text, overflow: "hidden"}}><div style={{position: "absolute", inset: 0, background: palette.surface, color: palette.surfaceText, display: "grid", placeItems: "center", fontSize: Math.min(width * 0.075, height * 0.06), fontWeight: 800, padding: "12%", textAlign: "center"}}>{scene.left}</div><div style={{position: "absolute", inset: 0, clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`, background: palette.primary, color: palette.primaryText, display: "grid", placeItems: "center", fontSize: Math.min(width * 0.075, height * 0.06), fontWeight: 900, padding: "12%", textAlign: "center"}}>{scene.right}</div><div style={{position: "absolute", left: p * width - 3, top: 0, bottom: 0, width: 6, background: palette.highlight, boxShadow: `0 0 25px ${palette.highlight}`}}/><div style={{position: "absolute", left: "7%", right: "7%", bottom: "7%", fontSize: Math.min(width * 0.047, 47), fontWeight: 850}}>{scene.title}</div></AbsoluteFill>;
};

const GradientWordSweep: React.FC<{scene: ShotScene; palette: ShotPalette}> = ({scene, palette}) => {
  const frame = useCurrentFrame();
  const {width, height, durationInFrames} = useVideoConfig();
  const x = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [-80, 180], clamp);
  return <AbsoluteFill style={{background: palette.background, color: palette.text, display: "grid", placeItems: "center", padding: "10%"}}><div style={{fontSize: Math.min(width * 0.12, height * 0.09), lineHeight: 0.95, fontWeight: 900, textAlign: "center", backgroundImage: `linear-gradient(100deg, ${palette.text} 0%, ${palette.text} ${x - 30}%, ${palette.highlight} ${x}%, ${palette.accent} ${x + 22}%, ${palette.text} ${x + 48}%)`, backgroundClip: "text", WebkitBackgroundClip: "text", color: "transparent", filter: `drop-shadow(0 0 ${Math.max(0, 30 - Math.abs(x - 50) / 3)}px ${palette.accent})`}}>{scene.title}</div></AbsoluteFill>;
};

const MarkerUnderline: React.FC<{scene: ShotScene; palette: ShotPalette}> = ({scene, palette}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const p = reveal(frame, 12, 22);
  return <AbsoluteFill style={{background: palette.background, color: palette.text, justifyContent: "center", padding: "10%"}}><div style={{fontSize: Math.min(width * 0.105, height * 0.082), lineHeight: 1, fontWeight: 900}}>{scene.title}</div><div style={{height: Math.max(10, height * 0.014), width: "74%", marginTop: -height * 0.008, background: palette.highlight, opacity: 0.72, transform: `rotate(-2deg) scaleX(${p})`, transformOrigin: "left", clipPath: "polygon(0 30%, 100% 0, 98% 75%, 3% 100%)"}}/><div style={{fontSize: Math.min(width * 0.038, 38), marginTop: height * 0.035, color: palette.mutedText, opacity: reveal(frame, 25, 12)}}>{scene.body}</div></AbsoluteFill>;
};

const RadialWave: React.FC<{scene: ShotScene; palette: ShotPalette}> = ({scene, palette}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const columns = 13;
  const rows = 17;
  return <AbsoluteFill style={{background: palette.background, color: palette.text, overflow: "hidden"}}><div style={{position: "absolute", inset: "5%", display: "grid", gridTemplateColumns: `repeat(${columns}, 1fr)`, gap: Math.max(5, width * 0.008), opacity: 0.7}}>{Array.from({length: columns * rows}).map((_, index) => {const x = index % columns - (columns - 1) / 2; const y = Math.floor(index / columns) - (rows - 1) / 2; const distance = Math.sqrt(x * x + y * y); const wave = Math.max(0, Math.sin((frame - distance * 3) * 0.22)); return <div key={index} style={{aspectRatio: "1", borderRadius: "50%", background: wave > 0.45 ? palette.accent : palette.surface, transform: `scale(${0.35 + wave * 1.1})`, boxShadow: wave > 0.7 ? `0 0 20px ${palette.accent}` : "none"}}/>;})}</div><div style={{position: "absolute", inset: 0, display: "grid", placeItems: "center", padding: "12%", textAlign: "center", background: "radial-gradient(circle, rgba(0,0,0,.7), transparent 62%)"}}><div style={{fontSize: Math.min(width * 0.10, height * 0.075), lineHeight: 0.95, fontWeight: 900, maxWidth: "82%"}}>{scene.title}</div></div></AbsoluteFill>;
};

const ProductCardAssemble: React.FC<{scene: ShotScene; palette: ShotPalette}> = ({scene, palette}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const card = reveal(frame, 0, 16);
  const media = reveal(frame, 8, 14);
  const copy = reveal(frame, 18, 16);
  return <AbsoluteFill style={{background: palette.background, justifyContent: "center", alignItems: "center", color: palette.text}}><div style={{width: "78%", minHeight: "66%", background: palette.surface, color: palette.surfaceText, borderRadius: Math.min(width, height) * 0.055, padding: "5%", boxShadow: "0 35px 90px #0007", transform: `translateY(${(1 - card) * height * 0.18}px) scale(${0.88 + card * 0.12})`, opacity: card}}>{scene.media_src ? <div style={{height: "48%", borderRadius: 24, overflow: "hidden", opacity: media, transform: `scale(${0.9 + media * 0.1})`}}><ShotMedia scene={scene}/></div> : null}<div style={{opacity: copy, marginTop: scene.media_src ? "6%" : "18%"}}><div style={{fontSize: Math.min(width * 0.072, height * 0.055), fontWeight: 900, lineHeight: 1}}>{scene.title}</div><div style={{fontSize: Math.min(width * 0.035, 35), color: palette.surfaceMutedText, marginTop: 22}}>{scene.body}</div>{scene.stat ? <div style={{display: "inline-block", marginTop: 30, padding: "12px 20px", borderRadius: 999, background: palette.highlight, color: palette.highlightText, fontSize: Math.min(width * 0.052, 52), fontWeight: 900}}>{scene.stat}</div> : null}</div></div></AbsoluteFill>;
};

const VerticalTicker: React.FC<{scene: ShotScene; palette: ShotPalette}> = ({scene, palette}) => {
  const frame = useCurrentFrame();
  const {width, height, durationInFrames} = useVideoConfig();
  const items = (scene.items.length ? scene.items : [scene.title, scene.body]).filter(Boolean);
  const repeated = [...items, ...items, ...items];
  const y = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, -height * 0.55], clamp);
  return <AbsoluteFill style={{background: palette.background, overflow: "hidden", color: palette.text, perspective: `${height}px`}}><div style={{position: "absolute", inset: "-10% 8%", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 22, transform: `rotateX(12deg) rotateZ(-3deg) scale(1.08)`}}>{[0, 1].map(column => <div key={column} style={{display: "flex", flexDirection: "column", gap: 22, transform: `translateY(${column ? -y - height * 0.5 : y}px)`}}>{repeated.map((item, index) => <div key={`${column}-${index}`} style={{minHeight: height * 0.16, padding: "8%", borderRadius: 24, background: index % 3 === 0 ? palette.primary : palette.surface, color: index % 3 === 0 ? palette.primaryText : palette.surfaceText, fontSize: Math.min(width * 0.04, 40), fontWeight: 760, display: "flex", alignItems: "flex-end"}}>{item}</div>)}</div>)}</div><div style={{position: "absolute", inset: 0, background: `linear-gradient(${palette.background}, transparent 25%, transparent 75%, ${palette.background})`}}/></AbsoluteFill>;
};

const CtaInkLockup: React.FC<{scene: ShotScene; palette: ShotPalette; brandName: string; logoSrc: string}> = ({scene, palette, brandName, logoSrc}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const p = reveal(frame, 3, 20);
  return <AbsoluteFill style={{background: palette.background, color: palette.text, display: "grid", placeItems: "center", textAlign: "center", padding: "10%"}}><div style={{opacity: p, transform: `translateY(${(1 - p) * 60}px)`}}>{logoSrc ? <Img src={staticFile(logoSrc)} style={{maxWidth: width * 0.24, maxHeight: height * 0.09, objectFit: "contain", marginBottom: 28}}/> : <div style={{fontSize: Math.min(width * 0.028, 28), color: palette.emphasisText, letterSpacing: "0.16em", textTransform: "uppercase", marginBottom: 28}}>{brandName}</div>}<div style={{fontFamily: "Georgia, 'Times New Roman', serif", fontSize: Math.min(width * 0.10, height * 0.08), lineHeight: 1, fontWeight: 650}}>{scene.title}</div><div style={{width: width * 0.18, height: Math.max(4, height * 0.004), background: palette.highlight, margin: `${height * 0.035}px auto`, transform: `scaleX(${reveal(frame, 16, 16)})`}}/><div style={{fontSize: Math.min(width * 0.036, 36), color: palette.mutedText}}>{scene.body}</div></div></AbsoluteFill>;
};

export const RECIPE_COMPONENTS = new Set([
  "brand-ink-open", "paper-title-card", "page-cam-2.5d", "multiplane", "crash-zoom-punch",
  "card-stack", "deck-deal-flyin", "row-embed", "list-stack-press", "odometer-digit-roll",
  "before-after-slider-scrub", "gradient-word-sweep", "marker-underline-title", "radial-wave",
  "product-card-progressive-assemble", "page-waterfall-wall", "cta-ink-lockup",
]);

export const ShotRecipeScene: React.FC<{scene: ShotScene; palette: ShotPalette; fontFamily: string; brandName: string; logoSrc: string}> = ({scene, palette, fontFamily, brandName, logoSrc}) => {
  switch (scene.shot_recipe) {
    case "brand-ink-open": return <BrandInkOpen scene={scene} palette={palette} fontFamily={fontFamily}/>;
    case "paper-title-card": return <PaperTitleCard scene={scene} palette={palette}/>;
    case "page-cam-2.5d":
    case "multiplane": return scene.media_src ? <PageCam25D scene={scene} palette={palette}/> : null;
    case "crash-zoom-punch": return <CrashZoomPunch scene={scene} palette={palette}/>;
    case "card-stack":
    case "deck-deal-flyin":
    case "row-embed": return <CardStack scene={scene} palette={palette}/>;
    case "list-stack-press": return <CardStack scene={scene} palette={palette} numbered/>;
    case "odometer-digit-roll": return <OdometerStat scene={scene} palette={palette}/>;
    case "before-after-slider-scrub": return <BeforeAfterSlider scene={scene} palette={palette}/>;
    case "gradient-word-sweep": return <GradientWordSweep scene={scene} palette={palette}/>;
    case "marker-underline-title": return <MarkerUnderline scene={scene} palette={palette}/>;
    case "radial-wave": return <RadialWave scene={scene} palette={palette}/>;
    case "product-card-progressive-assemble": return <ProductCardAssemble scene={scene} palette={palette}/>;
    case "page-waterfall-wall": return <VerticalTicker scene={scene} palette={palette}/>;
    case "cta-ink-lockup": return <CtaInkLockup scene={scene} palette={palette} brandName={brandName} logoSrc={logoSrc}/>;
    default: return null;
  }
};

export const ShotTransitionOverlay: React.FC<{transition: string; palette: ShotPalette}> = ({transition, palette}) => {
  const frame = useCurrentFrame();
  const {width, durationInFrames} = useVideoConfig();
  if (transition === "flash-cut") {
    const opacity = interpolate(frame, [0, 4, 11], [0, 0.88, 0], clamp);
    return <AbsoluteFill style={{pointerEvents: "none", opacity, background: `radial-gradient(circle at 50% 45%, #fff, ${palette.highlight}88 58%, transparent 82%)`}}/>;
  }
  if (transition === "whip-pan") {
    const x = interpolate(frame, [0, 8], [-width, width], clamp);
    return <AbsoluteFill style={{pointerEvents: "none", transform: `translateX(${x}px)`, background: `linear-gradient(90deg, transparent, ${palette.accent}, #fff, ${palette.primary}, transparent)`, filter: "blur(18px)", opacity: 0.8}}/>;
  }
  if (transition === "ink-bleed-reveal") {
    const p = interpolate(frame, [0, Math.min(16, durationInFrames * 0.25)], [0, 1], {...clamp, easing: ease});
    return <AbsoluteFill style={{pointerEvents: "none", background: palette.surface, clipPath: `polygon(0 0, ${p * 120}% 0, ${Math.max(0, p * 120 - 20)}% 100%, 0 100%)`, opacity: 1 - p}}/>;
  }
  return null;
};

export const ShotAccentLayers: React.FC<{recipes: string[]; palette: ShotPalette; scene: ShotScene}> = ({recipes, palette, scene}) => {
  const frame = useCurrentFrame();
  const {width, height, durationInFrames} = useVideoConfig();
  return (
    <AbsoluteFill style={{pointerEvents: "none", overflow: "hidden"}}>
      {recipes.includes("brand-frame-snap") ? (
        <div style={{position: "absolute", inset: width * 0.035, border: `${Math.max(5, width * 0.012)}px solid ${palette.accent}`, transform: `scale(${reveal(frame, 0, 14)})`, opacity: reveal(frame, 0, 10)}}/>
      ) : null}
      {recipes.includes("scanline-annotate-focus") ? (() => {
        const y = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [-height * 0.05, height * 1.05], clamp);
        return <><div style={{position: "absolute", left: "5%", right: "5%", top: y, height: Math.max(3, height * 0.004), background: palette.accent, boxShadow: `0 0 28px ${palette.accent}`}}/><div style={{position: "absolute", inset: "9%", border: `2px solid ${palette.accent}88`, clipPath: "polygon(0 0, 13% 0, 13% 2px, 2px 2px, 2px 13%, 0 13%, 0 0, 100% 0, 100% 13%, calc(100% - 2px) 13%, calc(100% - 2px) 2px, 87% 2px, 87% 0, 100% 0, 100% 100%, 87% 100%, 87% calc(100% - 2px), calc(100% - 2px) calc(100% - 2px), calc(100% - 2px) 87%, 100% 87%, 100% 100%, 0 100%, 0 87%, 2px 87%, 2px calc(100% - 2px), 13% calc(100% - 2px), 13% 100%, 0 100%)"}}/></>;
      })() : null}
      {recipes.includes("spotlight-sweep") ? (() => {
        const x = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [-30, 130], clamp);
        return <div style={{position: "absolute", inset: 0, background: `radial-gradient(circle at ${x}% 48%, ${palette.highlight}42 0%, transparent 24%)`, mixBlendMode: "screen"}}/>;
      })() : null}
      {recipes.includes("halation-bloom") ? (() => {
        const p = interpolate(frame, [8, 18, 34], [0, 1, 0.18], clamp);
        return <div style={{position: "absolute", inset: 0, opacity: p, background: `radial-gradient(circle at 50% 50%, ${palette.highlight}66, transparent 48%)`, mixBlendMode: "screen", filter: `blur(${width * 0.025}px)`}}/>;
      })() : null}
      {recipes.includes("marker-underline-title") ? (
        <div style={{position: "absolute", left: "14%", top: "61%", width: "48%", height: Math.max(9, height * 0.012), background: palette.highlight, opacity: 0.7 * reveal(frame, 12, 20), transform: `rotate(-2deg) scaleX(${reveal(frame, 12, 20)})`, transformOrigin: "left", clipPath: "polygon(0 30%, 100% 0, 98% 75%, 3% 100%)"}} aria-label={scene.title}/>
      ) : null}
    </AbsoluteFill>
  );
};
