import React from "react";
import {CalculateMetadataFunction, Composition} from "remotion";
import {AdPlusMotion} from "./compositions/AdPlusMotion";
import {MotionGraphic, MotionGraphicProps} from "./compositions/MotionGraphic";

const defaultProps: MotionGraphicProps = {
  schema: "admira.motion-graphic.v1",
  job_id: "studio-preview",
  objective: "educational",
  template: "adaptive",
  aspect_ratio: "9:16",
  width: 1080,
  height: 1920,
  fps: 30,
  duration_frames: 240,
  duration_seconds: 8,
  quality: "preview",
  render_scale: 0.5,
  brand: {
    name: "Admira IA",
    offer: "Oferta activa",
    audience: "Dueños de negocio",
    tone: "claro y profesional",
    visual_style: "editorial moderno",
    motion_style: "movimiento claro y medido",
    energy: "medio",
    motion_profile: {
      preset: "professional",
      entry_seconds: 0.62,
      travel_px: 38,
      media_scale: 0.95,
      stagger_seconds: 0.12,
      decor_drift: 0.028,
    },
    font_family: "Inter, Arial, sans-serif",
    typography_direction: "",
    logo_src: "",
    palette: {
      background: "#070A12",
      surface: "#202431",
      primary: "#675CFF",
      accent: "#2ED3B7",
      highlight: "#FFC857",
      text: "#FFFFFF",
      mutedText: "#C9CCD5",
    },
  },
  product: {id: "", guide: "", name: "Oferta activa"},
  scenes: [
    {
      type: "hook",
      eyebrow: "Educación",
      title: "Una idea clara en pocos segundos",
      body: "Cada plano comunica una sola cosa y luego deja respirar el mensaje.",
      items: [],
      stat: "",
      left: "",
      right: "",
      quote: "",
      attribution: "",
      media_src: "",
      media_kind: "",
      media_fit: "cover",
      duration_seconds: 4,
      duration_frames: 120,
      motion: "editorial-reveal",
      shot_recipe: "brand-ink-open",
      shot_recipes: ["brand-ink-open", "brand-frame-snap"],
      transition: "",
    },
    {
      type: "cta",
      eyebrow: "Siguiente paso",
      title: "Guarda este video",
      body: "",
      items: [],
      stat: "",
      left: "",
      right: "",
      quote: "",
      attribution: "",
      media_src: "",
      media_kind: "",
      media_fit: "cover",
      duration_seconds: 4,
      duration_frames: 120,
      motion: "cta-lockup",
      shot_recipe: "cta-ink-lockup",
      shot_recipes: ["cta-ink-lockup"],
      transition: "",
    },
  ],
  audio: {src: "", volume: 0},
  assets: [],
  asset_policy: "",
};

const calculateMetadata: CalculateMetadataFunction<MotionGraphicProps> = ({props}) => ({
  durationInFrames: Math.max(1, Math.round(props.duration_frames || 1)),
  fps: [24, 25, 30].includes(props.fps) ? props.fps : 30,
  width: Math.max(2, Math.ceil(Math.round(props.width * (props.render_scale || 1)) / 2) * 2),
  height: Math.max(2, Math.ceil(Math.round(props.height * (props.render_scale || 1)) / 2) * 2),
  props,
  defaultOutName: `${props.job_id || "motion-graphic"}.mp4`,
  defaultCodec: "h264",
});

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="AdmiraMotionGraphic"
        component={MotionGraphic}
        durationInFrames={240}
        fps={30}
        width={540}
        height={960}
        defaultProps={defaultProps}
        calculateMetadata={calculateMetadata}
      />
      <Composition
        id="AdPlusMotion"
        component={AdPlusMotion}
        durationInFrames={720}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          eyebrow: "Meta Ads sin ansiedad",
          headline: "IA como manager, no como botón mágico",
          body: "La automatización no debería gastar por ti. Primero explica, prepara acciones y te pide aprobación.",
          mechanism: "El agente revisa resultados, explica lo importante y deja las acciones listas para aprobación.",
          cta: "Mira cómo trabaja",
          pillar: "approval_based_automation",
          keyframeImage: "",
        }}
      />
    </>
  );
};
