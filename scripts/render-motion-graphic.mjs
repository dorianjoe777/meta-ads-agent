import {bundle} from "@remotion/bundler";
import {renderMedia, renderStill, selectComposition} from "@remotion/renderer";
import fs from "node:fs/promises";
import path from "node:path";

const [, , specPath, outputPath, posterPath] = process.argv;
if (!specPath || !outputPath || !posterPath) {
  console.error("Usage: node scripts/render-motion-graphic.mjs spec.json output.mp4 poster.png");
  process.exit(2);
}

const cwd = process.cwd();
const inputProps = JSON.parse(await fs.readFile(specPath, "utf8"));
if (inputProps.schema !== "admira.motion-graphic.v1") {
  throw new Error("Unsupported motion graphic schema");
}

const publicDir = path.join(path.dirname(specPath), "public");
let entryPoint = path.join(cwd, "src/remotion/index.tsx");
let compositionId = "AdmiraMotionGraphic";
if (inputProps.generated_entrypoint) {
  const jobDir = path.resolve(path.dirname(specPath));
  const candidate = path.resolve(jobDir, String(inputProps.generated_entrypoint));
  if (!candidate.startsWith(`${jobDir}${path.sep}`) || path.extname(candidate) !== ".tsx") {
    throw new Error("Unsafe generated motion entrypoint");
  }
  const stat = await fs.stat(candidate);
  if (!stat.isFile() || stat.size > 400000) {
    throw new Error("Invalid generated motion entrypoint");
  }
  entryPoint = candidate;
  compositionId = "AdmiraCompiledMotionGraphic";
}
const serveUrl = await bundle({
  entryPoint,
  publicDir,
  webpackOverride: (config) => config,
});
const composition = await selectComposition({
  serveUrl,
  id: compositionId,
  inputProps,
});
const concurrency = Math.max(1, Math.min(2, Number.parseInt(process.env.REMOTION_CONCURRENCY || "1", 10) || 1));
const chromiumOptions = {
  ignoreCertificateErrors: false,
  enableMultiProcessOnLinux: process.platform === "linux",
};

await renderMedia({
  composition,
  serveUrl,
  codec: "h264",
  outputLocation: outputPath,
  inputProps,
  concurrency,
  crf: inputProps.quality === "final" ? 18 : 24,
  pixelFormat: "yuv420p",
  chromiumOptions,
});

await renderStill({
  composition,
  serveUrl,
  output: posterPath,
  inputProps,
  frame: Math.min(composition.durationInFrames - 1, Math.max(0, Math.round(composition.fps * 0.8))),
  chromiumOptions,
});

console.log(JSON.stringify({ok: true, outputPath, posterPath, durationInFrames: composition.durationInFrames}));
