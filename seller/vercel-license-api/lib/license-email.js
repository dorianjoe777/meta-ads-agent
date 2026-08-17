const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_EMAIL_HISTORY = 20;

export function normalizeBuyerEmail(value = "") {
  return String(value || "").trim().toLowerCase();
}

export function isValidBuyerEmail(value = "") {
  const email = normalizeBuyerEmail(value);
  return email.length <= 254 && EMAIL_PATTERN.test(email);
}

export function licenseEmailAliases(record = {}) {
  const current = normalizeBuyerEmail(record.buyer_email);
  const aliases = Array.isArray(record.buyer_email_aliases)
    ? record.buyer_email_aliases
    : [];
  return [...new Set(aliases.map(normalizeBuyerEmail).filter((email) => isValidBuyerEmail(email) && email !== current))];
}

/**
 * Email changes are deliberately non-destructive. The license key, device
 * registrations and cloud installation remain untouched. Keeping the prior
 * email as an installation alias lets an already-installed client refresh or
 * verify itself while the new owner uses the new email for future access.
 */
export function licenseEmailMatches(record = {}, value = "") {
  const email = normalizeBuyerEmail(value);
  if (!isValidBuyerEmail(email)) return false;
  return email === normalizeBuyerEmail(record.buyer_email) || licenseEmailAliases(record).includes(email);
}

export function updateLicenseBuyerEmail(record = {}, nextEmail = "", now = new Date().toISOString()) {
  const previousEmail = normalizeBuyerEmail(record.buyer_email);
  const buyerEmail = normalizeBuyerEmail(nextEmail);
  const aliases = licenseEmailAliases(record);
  if (previousEmail && previousEmail !== buyerEmail && isValidBuyerEmail(previousEmail)) {
    aliases.push(previousEmail);
  }
  const uniqueAliases = [...new Set(aliases.filter((email) => email && email !== buyerEmail))];
  const history = Array.isArray(record.buyer_email_history) ? record.buyer_email_history : [];
  const change = previousEmail && previousEmail !== buyerEmail
    ? { from: previousEmail, to: buyerEmail, changed_at: now }
    : null;
  return {
    ...record,
    buyer_email: buyerEmail,
    buyer_email_aliases: uniqueAliases,
    buyer_email_history: change ? [...history, change].slice(-MAX_EMAIL_HISTORY) : history,
    updated_at: now
  };
}
