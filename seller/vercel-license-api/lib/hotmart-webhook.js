import { timingSafeEqual } from "node:crypto";

const APPROVED_EVENTS = new Set(["PURCHASE_APPROVED"]);
const APPROVED_STATUSES = new Set(["APPROVED"]);
const REVOKE_EVENTS = new Set(["PURCHASE_REFUNDED", "PURCHASE_CHARGEBACK", "PURCHASE_CANCELED", "PURCHASE_CANCELLED"]);
const REVOKE_STATUSES = new Set(["REFUNDED", "CHARGEBACK", "CANCELED", "CANCELLED", "BLOCKED"]);

function normalize(value) {
  return String(value || "").trim();
}

function upper(value) {
  return normalize(value).toUpperCase();
}

function headerValue(headers = {}, name) {
  if (!headers) return "";
  if (typeof headers.get === "function") {
    return normalize(headers.get(name));
  }
  const lowerName = name.toLowerCase();
  const entry = Object.entries(headers).find(([key]) => String(key).toLowerCase() === lowerName);
  return normalize(entry?.[1]);
}

function commaSet(value) {
  return new Set(
    normalize(value)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
  );
}

export function hotmartTokenAllowed(headers = {}, expectedToken = process.env.HOTMART_HOTTOK || process.env.HOTMART_WEBHOOK_TOKEN || "") {
  const supplied = headerValue(headers, "x-hotmart-hottok");
  const expected = normalize(expectedToken);
  if (!supplied || !expected) return false;
  const suppliedBuffer = Buffer.from(supplied);
  const expectedBuffer = Buffer.from(expected);
  return suppliedBuffer.length === expectedBuffer.length && timingSafeEqual(suppliedBuffer, expectedBuffer);
}

export function parseHotmartPayload(body = {}) {
  if (typeof body === "string") {
    try {
      return JSON.parse(body);
    } catch {
      return null;
    }
  }
  if (!body || typeof body !== "object") {
    return null;
  }
  return body;
}

export function hotmartSummary(payload = {}) {
  const data = payload.data || {};
  const buyer = data.buyer || payload.buyer || {};
  const purchase = data.purchase || payload.purchase || {};
  const product = data.product || payload.product || {};
  const offer = purchase.offer || data.offer || payload.offer || {};
  const buyerName = normalize(buyer.name || [buyer.first_name, buyer.last_name].filter(Boolean).join(" "));

  return {
    event_id: normalize(payload.id || payload.event_id),
    event: upper(payload.event),
    creation_date: payload.creation_date || null,
    buyer_email: normalize(buyer.email || payload.email).toLowerCase(),
    buyer_name: buyerName,
    transaction: normalize(purchase.transaction || payload.transaction),
    status: upper(purchase.status || payload.status),
    approved_date: purchase.approved_date || null,
    product_id: normalize(product.id || payload.prod),
    product_ucode: normalize(product.ucode),
    product_name: normalize(product.name || payload.product_name),
    offer_code: normalize(offer.code || purchase.offer_code || payload.off)
  };
}

export function isHotmartPurchaseApproved(summary = {}) {
  return APPROVED_EVENTS.has(upper(summary.event)) || APPROVED_STATUSES.has(upper(summary.status));
}

export function isHotmartPurchaseRevoked(summary = {}) {
  return REVOKE_EVENTS.has(upper(summary.event)) || REVOKE_STATUSES.has(upper(summary.status));
}

export function hotmartProductAllowed(summary = {}) {
  const allowedIds = commaSet(process.env.HOTMART_PRODUCT_IDS || process.env.HOTMART_PRODUCT_ID || "");
  const allowedUcodes = commaSet(process.env.HOTMART_PRODUCT_UCODES || process.env.HOTMART_PRODUCT_UCODE || "");
  const productIdAllowed = !allowedIds.size || allowedIds.has(String(summary.product_id || ""));
  const productUcodeAllowed = !allowedUcodes.size || allowedUcodes.has(String(summary.product_ucode || ""));
  return productIdAllowed && productUcodeAllowed;
}

export function planForHotmartPurchase(summary = {}) {
  const agencyOffers = commaSet(process.env.HOTMART_AGENCY_OFFER_CODES || "");
  if (summary.offer_code && agencyOffers.has(summary.offer_code)) {
    return "agency";
  }
  return process.env.HOTMART_DEFAULT_PLAN === "agency" ? "agency" : "individual";
}

export function shouldSendHotmartBuyerEmail() {
  const value = String(process.env.HOTMART_SEND_BUYER_EMAIL ?? "true").trim().toLowerCase();
  return !["0", "false", "no", "off"].includes(value);
}
