const PLATFORM_DEFINITIONS = [
  {
    id: "mac",
    label: "Mac",
    badge: "Recomendado: DMG",
    formats: [".dmg", ".pkg"],
    description: "Para Mac con Docker Desktop. Abre la app y el instalador se prepara solo.",
    button: "Descargar para Mac"
  },
  {
    id: "windows",
    label: "Windows",
    badge: "Recomendado: MSI",
    formats: [".msi", ".exe"],
    description: "Para Windows con Docker Desktop. Instala y abre el acceso directo.",
    button: "Descargar para Windows"
  },
  {
    id: "linux",
    label: "Linux / VPS",
    badge: "Bundle seguro",
    formats: [".tar.gz"],
    description: "Para VPS o Linux local. Incluye launcher y scripts de instalacion.",
    button: "Descargar para Linux"
  }
];

const DEFAULT_BUYER_IMPROVEMENTS = [
  {
    title: "Instalacion clara",
    body: "Elige Mac, Windows o Linux y sigue el instalador paso a paso.",
    impact: "Inicio rapido"
  },
  {
    title: "Manager IA actualizado",
    body: "Incluye la version estable del dashboard, chat del agente y flujos de configuracion.",
    impact: "Producto"
  },
  {
    title: "Listo para PC, VPS o nube",
    body: "Puedes instalarlo localmente o dejarlo corriendo en tu propio servidor.",
    impact: "Instalacion"
  }
];

const INTERNAL_RELEASE_WORDS = [
  "bootstrap",
  "dominio",
  "endpoint",
  "github",
  "license server",
  "licencias",
  "migracion",
  "migrar",
  "repo",
  "repositorio",
  "servidor de licencias",
  "vercel"
];

function plainText(value = "") {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function normalizeBuyerImprovement(item = {}) {
  if (typeof item === "string") {
    return { title: item.slice(0, 90), body: "", impact: "Mejora incluida" };
  }
  return {
    title: String(item?.title || item?.name || "Mejora incluida").slice(0, 90),
    body: String(item?.body || item?.description || "").slice(0, 260),
    impact: String(item?.impact || item?.area || "Mejora incluida").slice(0, 80)
  };
}

function isInternalReleaseNote(item = {}) {
  const normalized = normalizeBuyerImprovement(item);
  const haystack = plainText(`${normalized.title} ${normalized.body} ${normalized.impact}`);
  return INTERNAL_RELEASE_WORDS.some((word) => haystack.includes(plainText(word)));
}

export function buyerFacingImprovements(items = []) {
  const safeItems = Array.isArray(items)
    ? items.map(normalizeBuyerImprovement).filter((item) => !isInternalReleaseNote(item))
    : [];
  const merged = [...safeItems, ...DEFAULT_BUYER_IMPROVEMENTS];
  const seen = new Set();
  return merged.filter((item) => {
    const key = plainText(item.title);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 3);
}

function githubRepoFromAssets(release = {}) {
  const assets = release.assets || {};
  for (const asset of Object.values(assets)) {
    const sourceUrl = String(asset?.source_url || "");
    const match = sourceUrl.match(/^https:\/\/api\.github\.com\/repos\/([^/]+)\/([^/]+)\/releases\/assets\/\d+$/i);
    if (match) {
      return { owner: match[1], repo: match[2] };
    }
  }
  return null;
}

export async function releaseWithDiscoveredAssets(release = {}) {
  const token = String(process.env.GITHUB_RELEASE_TOKEN || process.env.GITHUB_TOKEN || "").trim();
  const version = String(release.version || "").trim();
  const repo = githubRepoFromAssets(release);
  if (!token || !version || !repo) {
    return release;
  }
  try {
    const url = `https://api.github.com/repos/${repo.owner}/${repo.repo}/releases/tags/${encodeURIComponent(version)}`;
    const response = await fetch(url, {
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${token}`,
        "User-Agent": "admiro-ai-download-portal",
        "X-GitHub-Api-Version": "2022-11-28"
      }
    });
    if (!response.ok) {
      return release;
    }
    const data = await response.json();
    const discovered = {};
    for (const asset of data.assets || []) {
      const name = String(asset.name || "").trim();
      const sourceUrl = String(asset.url || "").trim();
      if (!name || !sourceUrl) continue;
      discovered[name] = {
        asset_name: name,
        filename: name,
        content_type: String(asset.content_type || "application/octet-stream"),
        source_url: sourceUrl
      };
    }
    return {
      ...release,
      assets: {
        ...discovered,
        ...(release.assets || {})
      }
    };
  } catch {
    return release;
  }
}

function assetScore(assetName, filename, platform) {
  const haystack = `${assetName} ${filename}`.toLowerCase();
  if (platform.id === "mac" && !/mac|darwin|osx/.test(haystack)) return -1;
  if (platform.id === "windows" && !/windows|win/.test(haystack)) return -1;
  if (platform.id === "linux" && !/linux|vps/.test(haystack)) return -1;
  const formatIndex = platform.formats.findIndex((format) => haystack.includes(format));
  if (formatIndex < 0) return 1;
  return 100 - formatIndex;
}

export function platformCards(release = {}) {
  const assets = release.assets || {};
  return PLATFORM_DEFINITIONS.map((platform) => {
    const ranked = Object.entries(assets)
      .map(([assetName, asset]) => ({
        asset_name: assetName,
        filename: String(asset?.filename || assetName),
        content_type: String(asset?.content_type || "application/octet-stream"),
        score: assetScore(assetName, asset?.filename || assetName, platform)
      }))
      .filter((item) => item.score >= 0)
      .sort((left, right) => right.score - left.score);
    const chosen = ranked[0] || null;
    return {
      id: platform.id,
      label: platform.label,
      badge: platform.badge,
      description: platform.description,
      button: platform.button,
      available: Boolean(chosen),
      asset_name: chosen?.asset_name || "",
      filename: chosen?.filename || "",
      content_type: chosen?.content_type || ""
    };
  });
}

export function platformAsset(release = {}, platformId = "") {
  return platformCards(release).find((card) => card.id === platformId && card.available) || null;
}
