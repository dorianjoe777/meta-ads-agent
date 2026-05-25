import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import fs from "node:fs/promises";
import path from "node:path";

const [, , propsPath, outputPath] = process.argv;

if (!propsPath || !outputPath) {
  console.error("Usage: node scripts/render-content-video.mjs props.json output.mp4");
  process.exit(1);
}

const cwd = process.cwd();
const entry = path.join(cwd, "src/remotion/index.tsx");
const inputProps = JSON.parse(await fs.readFile(propsPath, "utf8"));
const serveUrl = await bundle({
  entryPoint: entry,
  webpackOverride: (config) => config
});
const composition = await selectComposition({
  serveUrl,
  id: "AdPlusMotion",
  inputProps
});

await renderMedia({
  composition,
  serveUrl,
  codec: "h264",
  outputLocation: outputPath,
  inputProps,
  chromiumOptions: {
    ignoreCertificateErrors: true
  }
});
