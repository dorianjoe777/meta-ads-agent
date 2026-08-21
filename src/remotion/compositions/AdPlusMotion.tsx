import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  Img,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Orbitron";

loadFont("normal", {
  weights: ["400", "700", "900"]
});

type Props = {
  eyebrow: string;
  headline: string;
  body: string;
  mechanism: string;
  cta: string;
  pillar: string;
  keyframeImage?: string;
};

const COLORS = {
  black: "#050007",
  violet900: "#230052",
  violet800: "#3B008C",
  violet700: "#5B13B8",
  lavender: "#DCCBFF",
  lavender2: "#EEE7FF",
  peach: "#FFD0CB",
  blush: "#FFE6E0",
  lime: "#C7F1B7",
  teal: "#0D6E62",
  ink: "#21004F",
  white: "#FFF9FF"
};

const font = "'Orbitron', 'Eurostile', 'Bank Gothic', 'Arial Black', sans-serif";

const scenes = [
  { from: 0, to: 120, key: "hook" },
  { from: 120, to: 300, key: "body" },
  { from: 300, to: 540, key: "mechanism" },
  { from: 540, to: 720, key: "cta" }
];

const clamp = (value: number, min = 0, max = 1) => Math.max(min, Math.min(max, value));

const sceneProgress = (frame: number, from: number, to: number) => clamp((frame - from) / (to - from));

const DiagonalPlane: React.FC<{
  color: string;
  opacity?: number;
  top: number;
  left: number;
  width: number;
  height: number;
  rotate: number;
  progress: number;
}> = ({ color, opacity = 1, top, left, width, height, rotate, progress }) => {
  const slide = interpolate(progress, [0, 1], [-90, 0], {
    easing: Easing.out(Easing.cubic),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp"
  });
  return (
    <div
      style={{
        position: "absolute",
        top,
        left: left + slide,
        width,
        height,
        background: color,
        opacity,
        transform: `rotate(${rotate}deg)`,
        transformOrigin: "center",
        clipPath: "polygon(0 0, 100% 0, 86% 100%, 0% 100%)",
        filter: "blur(0.2px)"
      }}
    />
  );
};

const Halftone: React.FC<{ progress: number; dark?: boolean }> = ({ progress, dark = false }) => {
  const drift = interpolate(progress, [0, 1], [0, 90]);
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        opacity: dark ? 0.18 : 0.26,
        backgroundImage: `radial-gradient(${dark ? COLORS.lavender : COLORS.violet800} 1.4px, transparent 1.4px)`,
        backgroundSize: "14px 14px",
        transform: `translateX(${drift}px)`,
        maskImage: "linear-gradient(120deg, black 0%, transparent 68%)"
      }}
    />
  );
};

const LogoMark: React.FC<{ small?: boolean }> = ({ small = false }) => {
  const size = small ? 64 : 136;
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: small ? 4 : 8 }}>
      <div
        style={{
          fontFamily: font,
          fontWeight: 900,
          fontSize: small ? 52 : 112,
          letterSpacing: -1,
          lineHeight: 0.86,
          color: COLORS.lavender2
        }}
      >
        Ad
      </div>
      <div
        style={{
          fontFamily: font,
          fontWeight: 900,
          fontSize: small ? 20 : 42,
          lineHeight: 0.7,
          marginTop: small ? -7 : -10,
          color: COLORS.lime,
          textShadow: `0 0 28px ${COLORS.lime}`
        }}
      >
        +
      </div>
    </div>
  );
};

const Pill: React.FC<{ children: React.ReactNode; active?: boolean; index: number; progress: number }> = ({
  children,
  active,
  index,
  progress
}) => {
  const y = interpolate(progress, [0, 1], [26 + index * 4, 0], {
    easing: Easing.out(Easing.cubic),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp"
  });
  return (
    <div
      style={{
        width: active ? 560 : 420,
        minHeight: active ? 104 : 74,
        marginBottom: 24,
        borderRadius: 999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: active ? COLORS.peach : "rgba(255, 208, 203, 0.72)",
        color: COLORS.ink,
        fontFamily: font,
        fontWeight: active ? 900 : 700,
        fontSize: active ? 42 : 26,
        boxShadow: active ? "0 22px 55px rgba(255, 208, 203, 0.28)" : "none",
        transform: `translateY(${y}px)`,
        opacity: interpolate(progress, [0, 0.22, 1], [0, 1, 1], { extrapolateRight: "clamp" })
      }}
    >
      {children}
    </div>
  );
};

const TextBlock: React.FC<{ title: string; body?: string; progress: number; light?: boolean }> = ({
  title,
  body,
  progress,
  light
}) => {
  const enter = spring({ frame: progress * 50, fps: 30, config: { damping: 14, stiffness: 105 } });
  return (
    <div
      style={{
        position: "absolute",
        left: 86,
        right: 86,
        top: 520,
        color: light ? COLORS.ink : COLORS.white,
        transform: `translateY(${interpolate(enter, [0, 1], [80, 0])}px) scale(${interpolate(enter, [0, 1], [0.96, 1])})`,
        opacity: enter
      }}
    >
      <div
        style={{
          fontFamily: font,
          fontWeight: 900,
          fontSize: title.length > 45 ? 64 : 78,
          lineHeight: 1.05,
          letterSpacing: -1,
          textShadow: light ? "none" : "0 18px 60px rgba(0,0,0,.5)"
        }}
      >
        {title}
      </div>
      {body ? (
        <div
          style={{
            marginTop: 56,
            maxWidth: 850,
            fontFamily: font,
            fontSize: 34,
            lineHeight: 1.35,
            fontWeight: 700,
            color: light ? COLORS.ink : COLORS.lavender2
          }}
        >
          {body}
        </div>
      ) : null}
    </div>
  );
};

const ProgressRail: React.FC<{ frame: number }> = ({ frame }) => {
  const pct = interpolate(frame, [0, 720], [0, 1], { extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left: 86, right: 86, bottom: 94, height: 12, borderRadius: 12, background: "rgba(255,255,255,.18)" }}>
      <div style={{ width: `${pct * 100}%`, height: "100%", borderRadius: 12, background: `linear-gradient(90deg, ${COLORS.lavender}, ${COLORS.peach}, ${COLORS.lime})` }} />
    </div>
  );
};

export const AdPlusMotion: React.FC<Props> = ({ eyebrow, headline, body, mechanism, cta, keyframeImage = "" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const globalPulse = Math.sin(frame / 18) * 12;
  const hook = sceneProgress(frame, 0, 120);
  const bodyP = sceneProgress(frame, 120, 300);
  const mechP = sceneProgress(frame, 300, 540);
  const ctaP = sceneProgress(frame, 540, 720);
  const sceneIndex = scenes.findIndex((scene) => frame >= scene.from && frame < scene.to);
  const current = sceneIndex === -1 ? 3 : sceneIndex;
  const bgRotate = interpolate(frame, [0, 720], [0, 18]);
  const arrowSpin = interpolate(frame, [540, 720], [-35, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: COLORS.black, overflow: "hidden" }}>
      {keyframeImage ? (
        <Img
          src={staticFile(keyframeImage)}
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${interpolate(frame, [0, 720], [1.08, 1.0])}) translateY(${interpolate(frame, [0, 720], [-34, 26])}px)`,
            filter: "saturate(1.05) contrast(1.04) brightness(0.82)",
            opacity: 0.92
          }}
        />
      ) : null}
      <AbsoluteFill
        style={{
          background:
            current === 1
              ? `linear-gradient(145deg, ${COLORS.lime} 0%, ${COLORS.blush} 100%)`
              : current === 2
                ? COLORS.teal
                : `radial-gradient(circle at 70% 12%, ${COLORS.peach} 0%, ${COLORS.violet700} 28%, ${COLORS.violet900} 72%, ${COLORS.black} 100%)`,
          opacity: keyframeImage ? 0.36 : 1
        }}
      />
      <Halftone progress={frame / 720} dark={current !== 1} />
      <DiagonalPlane color={COLORS.lavender} top={-80} left={-120} width={640} height={360} rotate={-34 + bgRotate} progress={hook} opacity={0.92} />
      <DiagonalPlane color={COLORS.peach} top={120} left={610} width={650} height={320} rotate={18 - bgRotate} progress={bodyP || hook} opacity={0.72} />
      <DiagonalPlane color={COLORS.lime} top={-120} left={430} width={850} height={430} rotate={18} progress={bodyP} opacity={current === 1 ? 0.96 : 0.22} />
      <DiagonalPlane color={COLORS.violet800} top={1290} left={-140} width={800} height={390} rotate={20 + bgRotate} progress={ctaP || hook} opacity={0.86} />

      <div style={{ position: "absolute", left: 86, top: 110, transform: `translateY(${globalPulse}px)` }}>
        <LogoMark small={current !== 0} />
      </div>

      <div
        style={{
          position: "absolute",
          right: 78,
          top: 126,
          padding: "20px 28px",
          borderRadius: 999,
          background: current === 1 ? "rgba(255,255,255,.56)" : "rgba(220,203,255,.22)",
          color: current === 1 ? COLORS.ink : COLORS.lavender2,
          fontFamily: font,
          fontWeight: 700,
          fontSize: 22
        }}
      >
        {eyebrow}
      </div>

      {current === 0 ? <TextBlock title={headline} progress={hook} /> : null}
      {current === 1 ? <TextBlock title="Tecnología para decidir mejor" body={body} progress={bodyP} light /> : null}
      {current === 2 ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column" }}>
          <Pill index={0} progress={mechP}>Dashboard</Pill>
          <Pill index={1} progress={mechP}>Lectura diaria</Pill>
          <Pill index={2} progress={mechP} active>Acciones listas</Pill>
          <Pill index={3} progress={mechP}>Aprobación</Pill>
          <div style={{ maxWidth: 760, marginTop: 28, color: COLORS.lavender2, fontFamily: font, fontSize: 30, lineHeight: 1.35, textAlign: "center", opacity: mechP }}>
            {mechanism}
          </div>
        </div>
      ) : null}
      {current === 3 ? (
        <>
          <TextBlock title={cta} body="Un operador instalado en tu PC o VPS. Tú conservas el control." progress={ctaP} />
          <svg width="220" height="220" viewBox="0 0 220 220" style={{ position: "absolute", right: 115, bottom: 405, transform: `rotate(${arrowSpin}deg) scale(${spring({ frame: Math.max(0, frame - 540), fps, config: { damping: 10 } })})` }}>
            <circle cx="110" cy="110" r="92" fill={COLORS.lavender} opacity="0.95" />
            <path d="M82 136l55-55M96 78h44v44" fill="none" stroke={COLORS.violet800} strokeWidth="18" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </>
      ) : null}
      <ProgressRail frame={frame} />
    </AbsoluteFill>
  );
};
