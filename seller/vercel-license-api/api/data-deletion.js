const UPDATED_AT = "July 6, 2026";

function setHtmlHeaders(response) {
  response.setHeader("Content-Type", "text/html; charset=utf-8");
  response.setHeader("Cache-Control", "public, max-age=300, s-maxage=3600");
  response.setHeader("X-Frame-Options", "DENY");
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  response.setHeader(
    "Content-Security-Policy",
    "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
  );
}

function page() {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Data Deletion Instructions | Admira IA</title>
  <style>
    :root{color-scheme:light;--bg:#f7f8ff;--card:#fff;--text:#171923;--muted:#5e6678;--line:#e3e7f1;--accent:#6d5cff}
    *{box-sizing:border-box}
    body{margin:0;background:linear-gradient(160deg,#fbfcff,#eef3ff);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Arial,sans-serif;line-height:1.65}
    main{max-width:860px;margin:0 auto;padding:48px 20px 72px}
    .card{background:rgba(255,255,255,.9);border:1px solid var(--line);border-radius:24px;padding:clamp(24px,5vw,48px);box-shadow:0 24px 80px rgba(47,63,108,.12)}
    h1{margin:0 0 8px;font-size:clamp(34px,6vw,54px);line-height:1.02;letter-spacing:-.04em}
    h2{margin:34px 0 10px;font-size:22px;line-height:1.2}
    p,li{color:var(--muted);font-size:16px}
    ol{padding-left:22px}
    .eyebrow{color:var(--accent);font-weight:800;text-transform:uppercase;letter-spacing:.08em;font-size:12px}
    .updated{margin:0 0 28px;color:#7b8496}
    a{color:var(--accent);font-weight:700}
  </style>
</head>
<body>
  <main>
    <article class="card">
      <div class="eyebrow">Admira IA</div>
      <h1>Data Deletion Instructions</h1>
      <p class="updated">Last updated: ${UPDATED_AT}</p>

      <p>
        If you connected Admira IA to Meta/Facebook and want your data deleted from Admira IA systems,
        you can request deletion using the steps below.
      </p>

      <h2>How to request deletion</h2>
      <ol>
        <li>Email <a href="mailto:support@admiroia.uboost.lat">support@admiroia.uboost.lat</a>.</li>
        <li>Use the subject line: <strong>Admira IA Data Deletion Request</strong>.</li>
        <li>Include the email address used for your purchase or product access, and the Meta Page or business name if relevant.</li>
      </ol>

      <h2>What we delete</h2>
      <p>
        We will delete or anonymize personal data that Admira IA controls, such as license/contact records,
        support records, stored business setup data, cloud install records, and Meta integration records where applicable.
        Some information may remain if required for legal, security, billing, fraud prevention, or dispute-resolution reasons.
      </p>

      <h2>Remove Meta access immediately</h2>
      <p>
        You can also revoke Admira IA's access directly from your Meta/Facebook account settings. This stops future access
        from Meta, but you should still contact us if you want stored product records deleted from Admira IA systems.
      </p>

      <h2>Timing</h2>
      <p>
        We aim to respond to deletion requests within 30 days after verifying the request.
      </p>

      <p>
        Privacy Policy: <a href="/privacy">/privacy</a>
      </p>
    </article>
  </main>
</body>
</html>`;
}

export default function handler(request, response) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return response.status(405).send("Method not allowed");
  }
  setHtmlHeaders(response);
  return response.status(200).send(request.method === "HEAD" ? "" : page());
}
