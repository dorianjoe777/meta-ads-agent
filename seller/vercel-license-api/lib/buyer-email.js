import nodemailer from "nodemailer";

const DEFAULT_ACCESS_URL = "https://admiroia.uboost.lat/access";
const DEFAULT_FROM = "Admira IA <no-reply@admiroia.uboost.lat>";
const DEFAULT_SMTP_HOST = "mail.spacemail.com";
const DEFAULT_SMTP_PORT = 465;

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function buyerFirstName(record = {}) {
  const name = String(record.buyer_name || "").trim();
  if (!name) return "";
  return name.split(/\s+/)[0];
}

function planLabel(plan = "individual") {
  return plan === "agency" ? "Agency" : "Individual";
}

export function buyerAccessUrl() {
  return String(process.env.BUYER_ACCESS_URL || DEFAULT_ACCESS_URL).trim() || DEFAULT_ACCESS_URL;
}

export function shouldAutoSendBuyerEmail() {
  return String(process.env.BUYER_EMAIL_AUTO_SEND || "").trim().toLowerCase() === "true";
}

function buyerEmailProvider(options = {}) {
  return String(options.provider || process.env.BUYER_EMAIL_PROVIDER || "resend").trim().toLowerCase();
}

function booleanOption(value, fallback = false) {
  if (value === undefined || value === null || value === "") return fallback;
  return ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase());
}

function numberOption(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function renderBuyerLicenseEmail(record, options = {}) {
  const accessUrl = String(options.accessUrl || buyerAccessUrl());
  const productName = String(options.productName || process.env.BUYER_EMAIL_PRODUCT_NAME || "Admira IA");
  const greetingName = buyerFirstName(record);
  const greeting = greetingName ? `Hola ${greetingName},` : "Hola,";
  const subject = String(options.subject || `Tu acceso a ${productName} esta listo`);
  const plan = planLabel(record.plan);
  const licenseKey = String(record.license_key || "").trim().toUpperCase();
  const buyerEmail = String(record.buyer_email || "").trim().toLowerCase();
  const preheader = `Tu licencia ${plan} y el acceso privado para instalar ${productName}.`;

  const text = [
    greeting,
    "",
    `Gracias por comprar ${productName}. Tu acceso ya esta listo.`,
    "",
    `Email de compra: ${buyerEmail}`,
    `Clave de acceso / licencia: ${licenseKey}`,
    `Plan: ${plan}`,
    "",
    `Entra aqui para descargar o instalar en la nube: ${accessUrl}`,
    "",
    "Usa exactamente el email de compra y esta clave de acceso. Si instalas en la nube, el portal te guiara paso a paso.",
    "",
    "Si necesitas ayuda, responde a este correo."
  ].join("\n");

  const html = `<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${escapeHtml(subject)}</title>
  </head>
  <body style="margin:0;background:#f6f7f4;color:#161714;font-family:Inter,Segoe UI,Arial,sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">${escapeHtml(preheader)}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f7f4;padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#ffffff;border:1px solid #dfe2d8;border-radius:18px;overflow:hidden;">
            <tr>
              <td style="background:#11130f;color:#f8f7ef;padding:28px 30px;">
                <div style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#b9c3ad;">${escapeHtml(productName)}</div>
                <h1 style="margin:10px 0 0;font-size:28px;line-height:1.15;font-weight:700;">Tu acceso esta listo</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:30px;">
                <p style="margin:0 0 16px;font-size:16px;line-height:1.6;">${escapeHtml(greeting)}</p>
                <p style="margin:0 0 20px;font-size:16px;line-height:1.6;">Gracias por comprar ${escapeHtml(productName)}. Guarda esta informacion: la vas a usar para entrar al area privada, descargar el producto o instalarlo en la nube.</p>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #dfe2d8;border-radius:12px;background:#fbfcf8;margin:22px 0;">
                  <tr>
                    <td style="padding:18px 20px;border-bottom:1px solid #e7e9e1;">
                      <div style="font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#6b705f;">Email de compra</div>
                      <div style="font-size:16px;line-height:1.5;color:#1b1d18;">${escapeHtml(buyerEmail)}</div>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:18px 20px;border-bottom:1px solid #e7e9e1;">
                      <div style="font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#6b705f;">Clave de acceso / licencia</div>
                      <div style="font-family:SFMono-Regular,Consolas,Liberation Mono,monospace;font-size:18px;line-height:1.55;color:#11130f;word-break:break-all;">${escapeHtml(licenseKey)}</div>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:18px 20px;">
                      <div style="font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#6b705f;">Plan</div>
                      <div style="font-size:16px;line-height:1.5;color:#1b1d18;">${escapeHtml(plan)}</div>
                    </td>
                  </tr>
                </table>
                <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#34372e;">Entra con el mismo email y la clave de acceso. Desde ahi puedes descargar el launcher o usar la instalacion cloud guiada.</p>
                <a href="${escapeHtml(accessUrl)}" style="display:inline-block;background:#11130f;color:#ffffff;text-decoration:none;border-radius:10px;padding:14px 20px;font-size:15px;font-weight:700;">Entrar al area de acceso</a>
                <p style="margin:24px 0 0;font-size:13px;line-height:1.6;color:#6b705f;">Si el boton no abre, pega este link en tu navegador:<br><a href="${escapeHtml(accessUrl)}" style="color:#2f5e3b;">${escapeHtml(accessUrl)}</a></p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>`;

  return {
    subject,
    text,
    html
  };
}

export async function sendBuyerLicenseEmail(record, options = {}) {
  const provider = buyerEmailProvider(options);
  if (provider === "smtp") {
    return sendBuyerLicenseEmailWithSmtp(record, options);
  }
  if (provider === "resend") {
    return sendBuyerLicenseEmailWithResend(record, options);
  }
  throw new Error(`Unsupported buyer email provider: ${provider}`);
}

async function sendBuyerLicenseEmailWithResend(record, options = {}) {
  const apiKey = String(options.apiKey || process.env.RESEND_API_KEY || "").trim();
  if (!apiKey) {
    throw new Error("RESEND_API_KEY is not configured");
  }

  const from = String(options.from || process.env.BUYER_EMAIL_FROM || DEFAULT_FROM).trim();
  const replyTo = String(options.replyTo || process.env.BUYER_EMAIL_REPLY_TO || "").trim();
  const accessUrl = String(options.accessUrl || buyerAccessUrl());
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  if (typeof fetchImpl !== "function") {
    throw new Error("fetch is not available in this runtime");
  }

  const rendered = renderBuyerLicenseEmail(record, { accessUrl });
  const payload = {
    from,
    to: [record.buyer_email],
    subject: rendered.subject,
    html: rendered.html,
    text: rendered.text
  };
  if (replyTo) {
    payload.reply_to = replyTo;
  }

  const result = await fetchImpl("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  const responseText = await result.text();
  let responseBody = {};
  try {
    responseBody = responseText ? JSON.parse(responseText) : {};
  } catch {
    responseBody = { raw: responseText };
  }
  if (!result.ok) {
    const detail = responseBody.message || responseBody.error || `HTTP ${result.status}`;
    throw new Error(`Buyer email send failed: ${detail}`);
  }
  return {
    provider: "resend",
    id: responseBody.id || "",
    sent_at: new Date().toISOString()
  };
}

async function sendBuyerLicenseEmailWithSmtp(record, options = {}) {
  const host = String(options.smtpHost || process.env.SMTP_HOST || DEFAULT_SMTP_HOST).trim();
  const port = numberOption(options.smtpPort || process.env.SMTP_PORT, DEFAULT_SMTP_PORT);
  const secure = booleanOption(options.smtpSecure ?? process.env.SMTP_SECURE, port === 465);
  const user = String(options.smtpUser || process.env.SMTP_USER || "").trim();
  const pass = String(options.smtpPass || process.env.SMTP_PASS || "");
  if (!host) {
    throw new Error("SMTP_HOST is not configured");
  }
  if (!user) {
    throw new Error("SMTP_USER is not configured");
  }
  if (!pass) {
    throw new Error("SMTP_PASS is not configured");
  }

  const from = String(options.from || process.env.BUYER_EMAIL_FROM || DEFAULT_FROM).trim();
  const replyTo = String(options.replyTo || process.env.BUYER_EMAIL_REPLY_TO || "").trim();
  const accessUrl = String(options.accessUrl || buyerAccessUrl());
  const rendered = renderBuyerLicenseEmail(record, { accessUrl });
  const transport = options.smtpTransport || nodemailer.createTransport({
    host,
    port,
    secure,
    auth: {
      user,
      pass
    }
  });

  const info = await transport.sendMail({
    from,
    to: record.buyer_email,
    replyTo: replyTo || undefined,
    subject: rendered.subject,
    html: rendered.html,
    text: rendered.text
  });

  return {
    provider: "smtp",
    id: info?.messageId || "",
    sent_at: new Date().toISOString()
  };
}
