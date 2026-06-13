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
    accessUrl: "https://admiroia.uboost.lat/access"
  });

  assert.equal(rendered.subject, "Tu acceso a Admira IA esta listo");
  assert.match(rendered.text, /MAO-TEST-BUYR-LICN-ABC123/);
  assert.match(rendered.text, /buyer@example\.com/);
  assert.match(rendered.text, /https:\/\/admiroia\.uboost\.lat\/access/);
  assert.match(rendered.html, /Entrar al area de acceso/);
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
    accessUrl: "https://admiroia.uboost.lat/access",
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
  assert.match(body.text, /https:\/\/admiroia\.uboost\.lat\/access/);
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
    smtpUser: "licenses@admiroia.uboost.lat",
    smtpPass: "test_password",
    from: "Admira IA <licenses@admiroia.uboost.lat>",
    replyTo: "support@admiroia.uboost.lat",
    accessUrl: "https://admiroia.uboost.lat/access",
    smtpTransport
  });

  assert.equal(delivery.provider, "smtp");
  assert.equal(delivery.id, "smtp_123");
  assert.equal(captured.from, "Admira IA <licenses@admiroia.uboost.lat>");
  assert.equal(captured.to, "buyer@example.com");
  assert.equal(captured.replyTo, "support@admiroia.uboost.lat");
  assert.match(captured.html, /MAO-TEST-BUYR-LICN-ABC123/);
  assert.match(captured.text, /https:\/\/admiroia\.uboost\.lat\/access/);
});
