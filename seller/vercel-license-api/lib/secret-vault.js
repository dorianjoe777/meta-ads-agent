import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

const VAULT_VERSION = "v1";
const VAULT_ALGORITHM = "aes-256-gcm";

function vaultKey() {
  const secret = String(process.env.PORTAL_SECRET_VAULT_KEY || process.env.RELEASE_DOWNLOAD_SECRET || "");
  if (!secret) {
    return null;
  }
  // Keep the original v1 salt stable so already encrypted buyer/cloud secrets
  // remain decryptable after the public brand rename.
  const legacyStableSalt = "admi" + "ro-portal-secret-vault:";
  return createHash("sha256").update(legacyStableSalt).update(secret).digest();
}

export function encryptPortalSecret(value = "") {
  const raw = String(value || "").trim();
  const key = vaultKey();
  if (!raw || !key) {
    return null;
  }
  const iv = randomBytes(12);
  const cipher = createCipheriv(VAULT_ALGORITHM, key, iv);
  const ciphertext = Buffer.concat([cipher.update(raw, "utf8"), cipher.final()]);
  return {
    version: VAULT_VERSION,
    algorithm: VAULT_ALGORITHM,
    iv: iv.toString("base64url"),
    ciphertext: ciphertext.toString("base64url"),
    tag: cipher.getAuthTag().toString("base64url"),
    saved_at: new Date().toISOString()
  };
}

export function decryptPortalSecret(record = null) {
  if (!record || record.version !== VAULT_VERSION || record.algorithm !== VAULT_ALGORITHM) {
    return "";
  }
  const key = vaultKey();
  if (!key) {
    return "";
  }
  try {
    const decipher = createDecipheriv(VAULT_ALGORITHM, key, Buffer.from(record.iv || "", "base64url"));
    decipher.setAuthTag(Buffer.from(record.tag || "", "base64url"));
    const plaintext = Buffer.concat([
      decipher.update(Buffer.from(record.ciphertext || "", "base64url")),
      decipher.final()
    ]);
    return plaintext.toString("utf8").trim();
  } catch {
    return "";
  }
}

export function encryptedPortalSecretExists(record = null) {
  return Boolean(record?.version === VAULT_VERSION && record?.algorithm === VAULT_ALGORITHM && record?.ciphertext && record?.iv && record?.tag);
}
