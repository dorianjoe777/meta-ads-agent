import test from "node:test";
import assert from "node:assert/strict";
import { renderBuyerLicenseEmail, sendBuyerLicenseEmail } from "../lib/buyer-email.js";

const license = {
  license_key: "MAO-TEST-BUYR-LICN-ABC123",
  buyer_email: "buyer@example.com",
  buyer_name: "Maria Buyer",
  plan: "individual"
};

test("renders buyer license email with license and access link", () => {
  const rendered = renderBuyerLicenseEmail(license, {
    accessUrl: "https://admiraia.uboost.lat/access"
  });

  assert.equal(rendered.subject, "Tu acceso a Admira IA está listo");
  assert.match(rendered.text, /MAO-TEST-BUYR-LICN-ABC123/);
  assert.match(rendered.text, /buyer@example\.com/);
  assert.match(rendered.text, /https:\/\/admiraia\.uboost\.lat\/access/);
  assert.match(rendered.html, /Entrar al área de acceso/);
  assert.match(rendered.text, /Tu acceso ya está listo/);
  assert.match(rendered.text, /sesión gratuita de instalación/);
  assert.match(rendered.text, /en hasta 20 minutos dejamos todo instalado contigo/);
  assert.match(rendered.text, /queda configurado de forma permanente/);
  assert.match(rendered.html, /sesión gratuita de instalación/);
});

test("renders owner commercial access details in Spanish", () => {
  const rendered = renderBuyerLicenseEmail({
    ...license,
    buyer_email: "dorianjoe.777@gmail.com",
    buyer_name: "Dorian",
    role: "owner",
    plan: "agency"
  });

  assert.match(rendered.text, /Email de compra: dorianjoe\.777@gmail\.com/);
  assert.match(rendered.text, /Plan: Comercial ilimitado/);
  assert.match(rendered.text, /Rol: Owner/);
  assert.match(rendered.html, /Comercial ilimitado/);
  assert.match(rendered.html, /<div style="font-size:16px;line-height:1\.5;color:#1b1d18;">Owner<\/div>/);
});

test("sends buyer license email through Resend payload", async () => {
  let captured = null;
  const fetchImpl = async (url, options) => {
    captured = { url, options };
    return {
      ok: true,
      text: async () => JSON.stringify({ id: "email_123" })
    };
  };

  const delivery = await sendBuyerLicenseEmail(license, {
    provider: "resend",
    apiKey: "test_resend_key",
    from: "Admira IA <licenses@example.com>",
    replyTo: "support@example.com",
    accessUrl: "https://admiraia.uboost.lat/access",
    fetchImpl
  });

  assert.equal(delivery.provider, "resend");
  assert.equal(delivery.id, "email_123");
  assert.equal(captured.url, "https://api.resend.com/emails");
  assert.equal(captured.options.method, "POST");
  assert.equal(captured.options.headers.Authorization, "Bearer test_resend_key");

  const body = JSON.parse(captured.options.body);
  assert.deepEqual(body.to, ["buyer@example.com"]);
  assert.equal(body.reply_to, "support@example.com");
  assert.match(body.html, /MAO-TEST-BUYR-LICN-ABC123/);
  assert.match(body.text, /https:\/\/admiraia\.uboost\.lat\/access/);
});

test("sends buyer license email through SMTP transport", async () => {
  let captured = null;
  const smtpTransport = {
    async sendMail(message) {
      captured = message;
      return { messageId: "smtp_123" };
    }
  };

  const delivery = await sendBuyerLicenseEmail(license, {
    provider: "smtp",
    smtpUser: "licenses@admiraia.uboost.lat",
    smtpPass: "test_password",
    from: "Admira IA <licenses@admiraia.uboost.lat>",
    replyTo: "support@admiraia.uboost.lat",
    accessUrl: "https://admiraia.uboost.lat/access",
    smtpTransport
  });

  assert.equal(delivery.provider, "smtp");
  assert.equal(delivery.id, "smtp_123");
  assert.equal(captured.from, "Admira IA <licenses@admiraia.uboost.lat>");
  assert.equal(captured.to, "buyer@example.com");
  assert.equal(captured.replyTo, "support@admiraia.uboost.lat");
  assert.match(captured.html, /MAO-TEST-BUYR-LICN-ABC123/);
  assert.match(captured.text, /https:\/\/admiraia\.uboost\.lat\/access/);
});
