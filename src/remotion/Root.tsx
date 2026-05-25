import React from "react";
import { Composition } from "remotion";
import { AdPlusMotion } from "./compositions/AdPlusMotion";

export const Root: React.FC = () => {
  return (
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
        keyframeImage: ""
      }}
    />
  );
};
