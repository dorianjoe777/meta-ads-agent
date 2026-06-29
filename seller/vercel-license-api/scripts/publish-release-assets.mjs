#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { put } from "@vercel/blob";
import { readReleases, writeReleases } from "../lib/store.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "../../..");
const releaseDir = resolve(repoRoot, "release");
const version = process.argv[2] || (await readFile(resolve(repoRoot, "VERSION"), "utf8")).trim();
const channel = process.env.RELEASE_CHANNEL || "stable";

const ASSETS = [
  {
    asset_name: `MetaAdsAgent-${version}-mac.dmg`,
    filename: `MetaAdsAgent-${version}-mac.dmg`,
    content_type: "application/x-apple-diskimage"
  },
  {
    asset_name: `MetaAdsAgent-${version}-windows.exe`,
    filename: `MetaAdsAgent-${version}-windows.exe`,
    content_type: "application/vnd.microsoft.portable-executable"
  },
  {
    asset_name: `MetaAdsAgent-${version}-linux.tar.gz`,
    filename: `MetaAdsAgent-${version}-linux.tar.gz`,
    content_type: "application/gzip"
  },
  {
    asset_name: `MetaAdsAgent-${version}-source.zip`,
    filename: `MetaAdsAgent-${version}-source.zip`,
    content_type: "application/zip"
  },
  {
    asset_name: "MetaAdsAgent-source.zip",
    filename: "MetaAdsAgent-source.zip",
    content_type: "application/zip"
  }
];

const improvements = [
  {
    title: "Login de ChatGPT/Codex mas confiable",
    body: "El login en DigitalOcean ya no se queda congelado en Preparando login cuando se reintenta la conexion o cuando falta autorizacion.",
    impact: "Onboarding"
  },
  {
    title: "Primer onboarding mas fluido",
    body: "La instalacion inicial puede iniciar, revisar y responder el login de ChatGPT/Codex antes de terminar la contraseña del dashboard.",
    impact: "Instalacion cloud"
  },
  {
    title: "Errores visibles en la pestaña de login",
    body: "Si el servidor no puede abrir el enlace seguro, la pestaña de espera muestra una accion para volver al dashboard en vez de quedarse girando.",
    impact: "Claridad"
  }
];

if (!process.env.BLOB_READ_WRITE_TOKEN) {
  throw new Error("BLOB_READ_WRITE_TOKEN is required to publish private release assets.");
}

const releases = await readReleases();
releases.channels ||= {};
const current = releases.channels[channel] || { assets: {} };
current.version = version;
current.asset_name = "MetaAdsAgent-source.zip";
current.github_repo = process.env.META_ADS_GITHUB_REPO || current.github_repo || "dorianjoe777/meta-ads-agent";
current.github_release_tag = version;
delete current.github_asset_id;
delete current.github_asset_api_url;
current.published_at = new Date().toISOString();
current.improvements = improvements;
current.assets = {};

for (const asset of ASSETS) {
  const localPath = resolve(releaseDir, asset.filename);
  if (!existsSync(localPath)) {
    console.warn(`Skipping missing asset: ${localPath}`);
    continue;
  }
  const blobPath = `releases/${channel}/${version}/${asset.filename}`;
  const body = await readFile(localPath);
  const sha256 = createHash("sha256").update(body).digest("hex");
  await put(blobPath, body, {
    access: "private",
    contentType: asset.content_type,
    allowOverwrite: true,
    cacheControlMaxAge: 60
  });
  current.assets[asset.asset_name] = {
    ...asset,
    blob_path: blobPath,
    source_url: "",
    sha256
  };
  console.log(`Published ${asset.filename} -> ${blobPath}`);
}

if (current.assets["MetaAdsAgent-source.zip"]?.sha256) {
  current.sha256 = current.assets["MetaAdsAgent-source.zip"].sha256;
}

releases.channels[channel] = current;
await writeReleases(releases);
console.log(`Updated ${channel} release registry to ${version}.`);
