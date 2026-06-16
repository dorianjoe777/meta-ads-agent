#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
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
    title: "Codigo de ChatGPT mas confiable",
    body: "El boton de copiar ahora toma exactamente el ultimo codigo grande visible en pantalla para evitar pegar codigos viejos.",
    impact: "ChatGPT"
  },
  {
    title: "Telegram mas facil de terminar",
    body: "Al pegar la clave de BotFather, el campo se convierte en clave guardada y muestra el siguiente paso para enviar hola y detectar el chat.",
    impact: "Telegram"
  },
  {
    title: "Video de Telegram compatible",
    body: "El tutorial de creacion del bot ahora se sirve como MP4 con respaldo MOV para que cargue mejor en navegador, Docker y VPS.",
    impact: "Onboarding"
  }
];

if (!process.env.BLOB_READ_WRITE_TOKEN) {
  throw new Error("BLOB_READ_WRITE_TOKEN is required to publish private release assets.");
}

const releases = await readReleases();
releases.channels ||= {};
const current = releases.channels[channel] || { assets: {} };
current.version = version;
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
  await put(blobPath, body, {
    access: "private",
    contentType: asset.content_type,
    allowOverwrite: true,
    cacheControlMaxAge: 60
  });
  current.assets[asset.asset_name] = {
    ...asset,
    blob_path: blobPath,
    source_url: ""
  };
  console.log(`Published ${asset.filename} -> ${blobPath}`);
}

releases.channels[channel] = current;
await writeReleases(releases);
console.log(`Updated ${channel} release registry to ${version}.`);
