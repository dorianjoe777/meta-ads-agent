const PLATFORM_DEFINITIONS = [
  {
    id: "mac",
    label: "Mac",
    badge: "Launcher Docker para Mac",
    formats: [".dmg"],
    allowUniversalFallback: true,
    description: "Descarga el DMG y abre Admira IA. Si el DMG aun se esta preparando, descarga el ZIP estable, descomprimelo y abre Instalar en Mac.command.",
    button: "Descargar para Mac"
  },
  {
    id: "windows",
    label: "Windows",
    badge: "Paquete ZIP temporal para Windows",
    formats: [".exe"],
    allowUniversalFallback: true,
    description: "Descarga el instalador y abre Docker Desktop. Si el instalador de Windows aun no esta publicado, descarga el ZIP estable, descomprimelo y abre Instalar en Windows.bat.",
    button: "Descargar para Windows"
  },
  {
    id: "linux",
    label: "Linux / VPS",
    badge: "Bundle Docker para Linux",
    formats: [".tar.gz"],
    allowUniversalFallback: true,
    description: "Para Linux local o VPS avanzado. Incluye launcher Docker, scripts de instalacion y apertura del dashboard.",
    button: "Descargar para Linux"
  }
];

const DEFAULT_BUYER_IMPROVEMENTS = [
  {
    title: "Instalacion en contenedor",
    body: "Elige Mac, Windows o Linux y corre el producto en Docker para una instalacion mas limpia y facil de soportar.",
    impact: "Docker"
  },
  {
    title: "Manager IA actualizado",
    body: "Incluye la version estable del dashboard, chat del agente y flujos de configuracion.",
    impact: "Producto"
  },
  {
    title: "Listo para PC, VPS o nube",
    body: "Puedes instalarlo localmente con Docker o dejarlo corriendo en tu propio servidor.",
    impact: "Instalacion"
  }
];

const INTERNAL_RELEASE_WORDS = [
  "api compatible",
  "bootstrap",
  "chatgpt",
  "codex",
  "comando",
  "digitalocean",
  "dominio",
  "endpoint",
  "github",
  "hermes",
  "license server",
  "licencias",
  "minimax",
  "migracion",
  "migrar",
  "no-browser",
  "oauth",
  "repo",
  "repositorio",
  "ssh",
  "servidor de licencias",
  "terminal",
  "vps",
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
  const configured = String(process.env.RELEASE_GITHUB_REPO || release.github_repo || "").trim();
  if (configured && configured.includes("/")) {
    const [owner, repo] = configured.split("/", 2).map((part) => part.trim());
    if (owner && repo) return { owner, repo };
  }
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
  const configuredVersion = String(process.env.RELEASE_GITHUB_TAG || "").trim();
  const version = configuredVersion || String(release.version || "").trim();
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
        "User-Agent": "admira-ia-download-portal",
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
      const registered = release.assets?.[name] || {};
      const discoveredSha256 = String(asset.digest || "").trim().toLowerCase().replace(/^sha256:/, "");
      discovered[name] = {
        ...registered,
        asset_name: name,
        filename: name,
        content_type: String(asset.content_type || "application/octet-stream"),
        source_url: sourceUrl,
        sha256: String(registered.sha256 || discoveredSha256 || "").trim().toLowerCase()
      };
    }
    return {
      ...release,
      ...(configuredVersion ? { version, github_repo: `${repo.owner}/${repo.repo}`, github_release_tag: version } : {}),
      assets: {
        ...(release.assets || {}),
        ...discovered
      }
    };
  } catch {
    return release;
  }
}

export function releaseAssetByName(release = {}, assetName = "") {
  const desired = String(assetName || "").trim();
  if (!desired) return null;
  const assets = release.assets || {};
  if (assets[desired]) return assets[desired];
  for (const [key, asset] of Object.entries(assets)) {
    const names = [
      key,
      asset?.asset_name,
      asset?.name,
      asset?.filename
    ].map((value) => String(value || "").trim()).filter(Boolean);
    if (names.includes(desired)) return asset;
  }
  return null;
}

function assetScore(assetName, filename, platform) {
  const haystack = `${assetName} ${filename}`.toLowerCase();
  if (platform.id === "mac" && !/mac|darwin|osx/.test(haystack)) return -1;
  if (platform.id === "windows" && !/windows|win/.test(haystack)) return -1;
  if (platform.id === "linux" && !/linux|vps/.test(haystack)) return -1;
  const formatIndex = platform.formats.findIndex((format) => haystack.includes(format));
  if (formatIndex < 0) return -1;
  let score = 100 - formatIndex;
  if (haystack.includes("docker")) score += 12;
  if (haystack.includes("launcher")) score += 10;
  if (haystack.includes("installer")) score += 4;
  if (haystack.includes("source")) score -= 80;
  if (haystack.includes("pkg") || haystack.includes("msi")) score -= 20;
  return score;
}

function universalInstallerAsset(assets = {}) {
  const ranked = Object.entries(assets)
    .map(([assetName, asset]) => {
      const filename = String(asset?.filename || assetName);
      const haystack = `${assetName} ${filename}`.toLowerCase();
      let score = 0;
      if (haystack.includes("metaadsagent-source.zip")) score += 80;
      if (haystack.includes("source.zip")) score += 60;
      if (haystack.endsWith(".zip")) score += 25;
      if (/mac|darwin|osx|windows|win|linux|vps/.test(haystack)) score -= 30;
      return {
        asset_name: assetName,
        filename,
        content_type: String(asset?.content_type || "application/octet-stream"),
        score
      };
    })
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score);
  return ranked[0] || null;
}

export function platformCards(release = {}) {
  const assets = release.assets || {};
  const universal = universalInstallerAsset(assets);
  return PLATFORM_DEFINITIONS.map((platform) => {
    const ranked = Object.entries(assets)
      .map(([assetName, asset]) => ({
        asset_name: assetName,
        filename: String(asset?.filename || assetName),
        content_type: String(asset?.content_type || "application/octet-stream"),
        blob_path: String(asset?.blob_path || ""),
        score: assetScore(assetName, asset?.filename || assetName, platform)
      }))
      .filter((item) => item.score >= 0)
      .sort((left, right) => right.score - left.score);
    const chosen = ranked[0] || (platform.allowUniversalFallback ? universal : null) || null;
    const isUniversal = Boolean(chosen && !ranked[0] && platform.allowUniversalFallback && universal);
    return {
      id: platform.id,
      label: platform.label,
      badge: platform.badge,
      description: isUniversal
        ? `${platform.description} Si el instalador especifico aun no esta publicado, este paquete estable universal trae los launchers necesarios.`
        : (!chosen && !platform.allowUniversalFallback
            ? `${platform.description} Este boton se activa cuando el instalador oficial de ${platform.label} esta publicado.`
            : platform.description),
      button: isUniversal && platform.id === "mac"
        ? "Descargar ZIP para Mac"
        : isUniversal && platform.id === "windows"
        ? "Descargar ZIP para Windows"
        : platform.button,
      available: Boolean(chosen),
      asset_name: chosen?.asset_name || "",
      filename: chosen?.filename || "",
      content_type: chosen?.content_type || "",
      blob_path: chosen?.blob_path || "",
      universal_fallback: isUniversal
    };
  });
}

export function platformAsset(release = {}, platformId = "") {
  return platformCards(release).find((card) => card.id === platformId && card.available) || null;
}
