function setSecurityHeaders(response) {
  response.setHeader("Content-Type", "text/html; charset=utf-8");
  response.setHeader("Cache-Control", "private, no-store");
  response.setHeader("X-Frame-Options", "DENY");
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("Referrer-Policy", "no-referrer");
  response.setHeader(
    "Content-Security-Policy",
    "default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
  );
}

export default async function handler(request, response) {
  if (request.method !== "GET") {
    return response.status(405).send("Method not allowed");
  }
  setSecurityHeaders(response);
  return response.status(200).send(`<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Descargar Admira IA</title>
  <style>
    :root{
      color-scheme:light;
      --bg:#f7f8fd;
      --shell:rgba(255,255,255,.82);
      --surface:#ffffff;
      --surface2:#f4f6fb;
      --line:rgba(38,44,57,.11);
      --border:#dfe5f1;
      --text:#171a22;
      --dim:#6b7284;
      --muted:#98a0af;
      --accent:#7b4dff;
      --accent2:#30d7b4;
      --blue:#5b8bff;
      --cyan:#31c8df;
      --pink:#ff90d9;
      --gold:#ffe267;
      --shadow:0 26px 80px rgba(85,96,132,.18);
      --glow:0 0 0 1px rgba(255,255,255,.8) inset,0 1px 0 rgba(255,255,255,.9) inset;
      font-family:"Satoshi","Plus Jakarta Sans","Manrope","Avenir Next",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      min-height:100vh;
      background:
        linear-gradient(112deg,rgba(115,211,255,.34) 0%,rgba(115,211,255,0) 30%),
        linear-gradient(232deg,rgba(255,185,239,.36) 0%,rgba(255,185,239,0) 34%),
        linear-gradient(318deg,rgba(246,223,128,.24) 0%,rgba(246,223,128,0) 32%),
        linear-gradient(180deg,#fbfcff 0%,#eef3fb 100%);
      color:var(--text);
      background-attachment:fixed;
    }
    main{
      width:min(1180px,calc(100% - 32px));
      margin:0 auto;
      padding:36px 0;
    }
    .shell{
      position:relative;
      border:1px solid rgba(38,44,57,.1);
      border-radius:30px;
      overflow:hidden;
      background:linear-gradient(145deg,rgba(255,255,255,.84),rgba(248,251,255,.66));
      box-shadow:var(--shadow),var(--glow);
      backdrop-filter:blur(24px) saturate(145%);
      -webkit-backdrop-filter:blur(24px) saturate(145%);
    }
    .shell:before{
      content:"";
      position:absolute;
      inset:0;
      background:
        linear-gradient(90deg,transparent 0,transparent calc(100% - 1px),rgba(123,77,255,.045) calc(100% - 1px)),
        linear-gradient(180deg,transparent 0,transparent calc(100% - 1px),rgba(49,200,223,.045) calc(100% - 1px));
      background-size:36px 36px;
      opacity:.38;
      pointer-events:none;
    }
    .hero{
      position:relative;
      z-index:1;
      display:grid;
      grid-template-columns:minmax(0,1.08fr) minmax(330px,.92fr);
      gap:24px;
      padding:30px;
      align-items:stretch;
    }
    .brand{
      display:flex;
      align-items:center;
      gap:12px;
      margin-bottom:32px;
    }
    .mark{
      display:grid;
      place-items:center;
      width:39px;height:39px;border-radius:12px;
      background:linear-gradient(135deg,var(--blue),var(--accent),var(--accent2));
      box-shadow:0 14px 36px rgba(85,96,132,.2),var(--glow);
      color:#fff;
      font-weight:950;
    }
    .mark:after{
      content:"";
      width:12px;
      height:12px;
      border-radius:50%;
      background:rgba(255,255,255,.9);
      box-shadow:12px 6px 0 rgba(255,255,255,.45),-6px 13px 0 rgba(255,255,255,.34);
    }
    .brand strong{display:block;font-size:18px;line-height:1.05}
    .brand span{display:block;color:var(--dim);font-size:12px;margin-top:4px}
    h1{
      margin:0;
      font-size:clamp(38px,6vw,76px);
      line-height:.92;
      max-width:760px;
      letter-spacing:0;
      font-weight:950;
    }
    .gradient{
      background:linear-gradient(104deg,#1c1f2b 0%,#7b4dff 34%,#31c8df 66%,#141722 100%);
      -webkit-background-clip:text;
      background-clip:text;
      color:transparent;
    }
    .copy{
      margin:22px 0 0;
      color:var(--dim);
      font-size:18px;
      line-height:1.58;
      max-width:680px;
    }
    .aurora-orb{
      position:relative;
      overflow:hidden;
      margin-top:28px;
      width:min(470px,100%);
      aspect-ratio:16/9;
      max-width:650px;
      border:1px solid var(--line);
      border-radius:22px;
      background:
        radial-gradient(circle at 72% 22%,rgba(92,222,245,.54),transparent 19%),
        radial-gradient(circle at 42% 24%,rgba(255,151,218,.58),transparent 24%),
        radial-gradient(circle at 28% 68%,rgba(255,224,100,.46),transparent 21%),
        linear-gradient(145deg,rgba(255,255,255,.72),rgba(248,251,255,.56));
      box-shadow:0 24px 66px rgba(85,96,132,.13),var(--glow);
      backdrop-filter:blur(22px) saturate(145%);
      -webkit-backdrop-filter:blur(22px) saturate(145%);
    }
    .aurora-orb:before{
      content:"";
      position:absolute;
      inset:18px;
      border-radius:18px;
      border:1px solid rgba(255,255,255,.72);
      background:linear-gradient(135deg,rgba(255,255,255,.64),rgba(255,255,255,.18));
      box-shadow:var(--glow);
    }
    .aurora-orb:after,.login:after,.card:after{
      content:"";
      position:absolute;
      right:-32px;
      top:-34px;
      width:170px;
      height:140px;
      background:
        radial-gradient(circle at 72% 26%,rgba(92,222,245,.7),transparent 18%),
        radial-gradient(circle at 44% 22%,rgba(255,151,218,.72),transparent 24%),
        radial-gradient(circle at 32% 66%,rgba(255,224,100,.62),transparent 20%),
        radial-gradient(circle at 72% 72%,rgba(77,255,195,.52),transparent 23%);
      filter:saturate(1.12);
      opacity:.52;
      pointer-events:none;
    }
    .login{
      position:relative;
      overflow:hidden;
      align-self:start;
      background:rgba(255,255,255,.78);
      border:1px solid var(--line);
      border-radius:22px;
      padding:22px;
      box-shadow:0 22px 64px rgba(85,96,132,.16),var(--glow);
      backdrop-filter:blur(22px) saturate(145%);
      -webkit-backdrop-filter:blur(22px) saturate(145%);
    }
    .login>*{position:relative;z-index:1}
    .login:after{opacity:.44}
    .login h2{margin:0 0 8px;font-size:24px;line-height:1.05}
    .login p{margin:0 0 18px;color:var(--dim);line-height:1.5}
    label{display:block;color:#4f5870;font-weight:900;font-size:12px;margin:14px 0 8px;text-transform:uppercase}
    input,select,textarea{
      width:100%;
      border:1px solid var(--border);
      border-radius:14px;
      background:#fff;
      color:var(--text);
      padding:0 14px;
      font:inherit;
      outline:none;
      box-shadow:0 1px 0 rgba(255,255,255,.9) inset;
    }
    input,select{min-height:52px}
    textarea{min-height:118px;padding:14px;resize:vertical;line-height:1.4}
    input:focus,select:focus,textarea:focus{border-color:rgba(123,77,255,.46);box-shadow:0 0 0 4px rgba(123,77,255,.1)}
    button{
      border:0;
      border-radius:15px;
      min-height:52px;
      padding:0 18px;
      font-weight:900;
      cursor:pointer;
      color:#fff;
      background:#171a22;
      box-shadow:0 16px 36px rgba(23,26,34,.18);
      transition:transform .16s ease,box-shadow .16s ease,opacity .16s ease;
    }
    button:hover{transform:translateY(-1px);box-shadow:0 20px 42px rgba(23,26,34,.22)}
    button:focus-visible,input:focus-visible{outline:3px solid rgba(49,200,223,.26);outline-offset:2px}
    .download-btn{
      background:rgba(123,77,255,.08);
      color:#5f35d8;
      border:1px solid rgba(123,77,255,.25);
      box-shadow:none;
    }
    .primary{width:100%;margin-top:18px}
    button:disabled{cursor:not-allowed;opacity:.55}
    .status{min-height:24px;margin-top:14px;color:#5f35d8;font-size:14px;font-weight:800}
    .remember-row{
      display:flex;
      align-items:flex-start;
      gap:10px;
      margin-top:14px;
      color:var(--dim);
      font-size:13px;
      line-height:1.35;
      font-weight:800;
    }
    .remember-row input{
      width:18px;
      min-height:18px;
      height:18px;
      margin-top:1px;
      accent-color:var(--accent);
      box-shadow:none;
    }
    .downloads{
      display:none;
      position:relative;
      z-index:1;
      border-top:1px solid var(--line);
      padding:28px 34px 34px;
      background:rgba(255,255,255,.34);
    }
    .downloads.active{display:block}
    .install-state{
      display:none;
      margin-bottom:18px;
      border:1px solid rgba(123,77,255,.18);
      border-radius:22px;
      padding:18px;
      background:
        radial-gradient(circle at 88% 12%,rgba(49,200,223,.26),transparent 25%),
        radial-gradient(circle at 10% 0%,rgba(255,144,217,.2),transparent 24%),
        rgba(255,255,255,.72);
      box-shadow:0 24px 70px rgba(85,96,132,.13),var(--glow);
    }
    .install-state.active{display:block}
    .install-state h2{margin:0;font-size:28px;line-height:1.05}
    .install-state p{margin:7px 0 0;color:var(--dim);line-height:1.5}
    .state-grid{
      display:grid;
      grid-template-columns:minmax(0,1.25fr) minmax(240px,.75fr);
      gap:14px;
      margin-top:14px;
    }
    .state-card{
      position:relative;
      overflow:hidden;
      border:1px solid var(--line);
      border-radius:18px;
      padding:16px;
      background:rgba(255,255,255,.7);
      box-shadow:var(--glow);
    }
    .state-card strong{display:block;font-size:16px}
    .state-card .state-pill{
      display:inline-flex;
      align-items:center;
      gap:7px;
      margin-bottom:10px;
      border:1px solid rgba(48,215,180,.26);
      border-radius:999px;
      padding:7px 10px;
      color:#16816f;
      background:rgba(48,215,180,.11);
      font-size:12px;
      font-weight:950;
    }
    .state-pill.pending{
      border-color:rgba(244,183,64,.32);
      color:#895c02;
      background:rgba(244,183,64,.14);
    }
    .state-pill.empty{
      border-color:rgba(123,77,255,.18);
      color:#5f35d8;
      background:rgba(123,77,255,.08);
    }
    .state-actions{
      display:flex;
      gap:10px;
      flex-wrap:wrap;
      margin-top:14px;
    }
    .state-actions .cloud-open-button{margin:0;flex:1 1 260px}
    .cloud-ip-form{
      display:grid;
      gap:10px;
      width:100%;
    }
    .cloud-ip-form input{
      width:100%;
      min-height:52px;
      border:1px solid rgba(123,77,255,.2);
      border-radius:15px;
      padding:0 14px;
      color:var(--ink);
      background:rgba(255,255,255,.82);
      box-shadow:var(--glow);
      font:inherit;
      font-weight:800;
    }
    .cloud-ip-form input:disabled{
      opacity:.62;
      cursor:not-allowed;
    }
    .cloud-progress{
      margin:14px 0 4px;
      border:1px solid rgba(123,77,255,.16);
      border-radius:999px;
      height:14px;
      overflow:hidden;
      background:rgba(255,255,255,.68);
      box-shadow:var(--glow);
    }
    .cloud-progress span{
      display:block;
      width:var(--progress,0%);
      height:100%;
      border-radius:inherit;
      background:linear-gradient(90deg,var(--accent),var(--cyan),var(--accent2));
      box-shadow:0 0 24px rgba(123,77,255,.28);
      transition:width .65s ease;
    }
    .cloud-progress-meta{
      display:flex;
      justify-content:space-between;
      gap:12px;
      color:#5f35d8;
      font-size:12px;
      font-weight:950;
      margin-top:8px;
    }
    .cloud-open-button.pending{
      pointer-events:none;
      color:#5f35d8 !important;
      background:rgba(123,77,255,.08);
      border:1px solid rgba(123,77,255,.16);
      box-shadow:none;
    }
    .cloud-reset-button{
      width:100%;
      min-height:46px;
      border:1px solid rgba(239,93,102,.18);
      border-radius:14px;
      background:rgba(255,255,255,.7);
      color:#9b3d45;
      box-shadow:var(--glow);
      font-size:13px;
    }
    .cloud-reset-button:hover{background:rgba(239,93,102,.08)}
    .cloud-delete-button{
      width:100%;
      min-height:50px;
      border:0;
      border-radius:15px;
      background:linear-gradient(135deg,#ef5d66,#c43d4c);
      color:#fff;
      box-shadow:0 18px 38px rgba(196,61,76,.2);
      font-size:14px;
      font-weight:950;
    }
    .cloud-delete-button:hover{filter:brightness(.98)}
    .cloud-danger-zone{
      margin-top:12px;
      border:1px solid rgba(239,93,102,.16);
      border-radius:16px;
      padding:12px;
      background:rgba(239,93,102,.055);
    }
    .cloud-danger-zone strong{
      color:#7f313a;
      font-size:13px;
    }
    .cloud-reset-note{
      margin:6px 0 0;
      color:#6b7284;
      font-size:12px;
      line-height:1.45;
    }
    .state-secondary{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      min-height:54px;
      border:1px solid rgba(123,77,255,.18);
      border-radius:16px;
      padding:0 16px;
      color:#5f35d8;
      text-decoration:none;
      font-weight:950;
      background:rgba(255,255,255,.64);
    }
    .download-head{
      display:flex;
      align-items:end;
      justify-content:space-between;
      gap:18px;
      margin-bottom:18px;
    }
    .download-head h2{margin:0;font-size:28px}
    .download-head p{margin:5px 0 0;color:var(--dim)}
    .version{
      border:1px solid var(--line);
      border-radius:999px;
      padding:9px 12px;
      color:#5f35d8;
      background:rgba(123,77,255,.08);
      white-space:nowrap;
      font-size:13px;
      font-weight:900;
    }
    .download-tools{
      display:flex;
      align-items:center;
      gap:10px;
      flex-wrap:wrap;
      justify-content:flex-end;
    }
    .docker-download{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      min-height:38px;
      border:1px solid rgba(49,200,223,.28);
      border-radius:999px;
      padding:0 13px;
      color:#2940a8;
      background:linear-gradient(135deg,rgba(49,200,223,.14),rgba(95,53,216,.10));
      font-size:13px;
      font-weight:950;
      text-decoration:none;
      box-shadow:0 14px 30px rgba(49,88,170,.08);
      white-space:nowrap;
    }
    .local-security-note{
      margin:18px 0 0;
      padding:14px 16px;
      border:1px solid rgba(95,53,216,.16);
      border-radius:18px;
      background:linear-gradient(135deg,rgba(255,255,255,.82),rgba(241,246,255,.74));
      color:var(--ink);
      box-shadow:0 16px 42px rgba(63,52,122,.08);
    }
    .local-security-note strong{display:block;font-size:14px;margin-bottom:4px}
    .local-security-note p{margin:0;color:var(--dim);font-size:13px;line-height:1.45}
    .logout-btn{
      min-height:38px;
      border:1px solid rgba(123,77,255,.18);
      border-radius:999px;
      padding:0 13px;
      color:#5f35d8;
      background:rgba(255,255,255,.64);
      box-shadow:none;
      font-size:12px;
    }
    .cards{
      display:grid;
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:16px;
    }
    .card{
      position:relative;
      border:1px solid var(--line);
      border-radius:20px;
      padding:18px;
      background:linear-gradient(145deg,rgba(255,255,255,.82),rgba(248,251,255,.64));
      overflow:hidden;
      min-height:260px;
      display:flex;
      flex-direction:column;
      box-shadow:0 24px 70px rgba(85,96,132,.16),var(--glow);
      backdrop-filter:blur(18px) saturate(135%);
      -webkit-backdrop-filter:blur(18px) saturate(135%);
    }
    .card:before{
      content:"";
      position:absolute;
      inset:0 0 auto;
      height:4px;
      background:linear-gradient(90deg,var(--cyan),var(--accent),var(--pink),var(--gold));
      z-index:1;
    }
    .card:after{opacity:.32}
    .card>*{position:relative;z-index:2}
    .card h3{margin:12px 0 8px;font-size:24px;line-height:1.05}
    .card .badge{color:#5f35d8;font-size:12px;font-weight:950;text-transform:uppercase}
    .card p{margin:0 0 18px;color:var(--dim);line-height:1.5}
    .file{
      margin-top:auto;
      border:1px solid var(--line);
      border-radius:12px;
      padding:10px;
      color:#4f5870;
      font-size:12px;
      word-break:break-word;
      background:rgba(255,255,255,.62);
      box-shadow:var(--glow);
    }
    .download-btn{margin-top:12px;width:100%}
    .empty{opacity:.55}
    .improvements{
      display:grid;
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:12px;
      margin-top:18px;
    }
    .improvement{
      border:1px solid var(--line);
      border-radius:14px;
      padding:13px;
      background:rgba(255,255,255,.62);
      box-shadow:var(--glow);
    }
    .improvement strong{display:block}
    .improvement span{display:block;color:var(--dim);font-size:13px;margin-top:5px;line-height:1.35}
    .cloud{
      margin-top:18px;
      border:1px solid rgba(123,77,255,.18);
      border-radius:22px;
      padding:18px;
      background:
        radial-gradient(circle at 88% 12%,rgba(49,200,223,.28),transparent 25%),
        radial-gradient(circle at 10% 0%,rgba(255,144,217,.22),transparent 24%),
        rgba(255,255,255,.7);
      box-shadow:0 24px 70px rgba(85,96,132,.13),var(--glow);
    }
    .cloud-top{
      display:flex;
      justify-content:space-between;
      gap:16px;
      align-items:center;
    }
    .cloud h3{margin:0;font-size:24px}
    .cloud p{margin:6px 0 0;color:var(--dim);line-height:1.5}
    .cloud-actions{
      display:flex;
      flex-wrap:wrap;
      gap:10px;
      justify-content:flex-end;
      align-items:center;
    }
    .cloud-toggle{
      min-width:188px;
      background:linear-gradient(135deg,var(--accent),var(--cyan));
      color:#fff;
    }
    .cloud-link-button{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      min-height:42px;
      padding:0 15px;
      border:1px solid rgba(95,53,216,.18);
      border-radius:999px;
      background:rgba(255,255,255,.72);
      color:#5f35d8;
      font-weight:900;
      text-decoration:none;
      box-shadow:0 14px 34px rgba(90,102,140,.10);
    }
    .cloud-intro{
      display:grid;
      grid-template-columns:1.15fr .85fr;
      gap:12px;
      margin-bottom:15px;
    }
    .cloud-intro-card{
      border:1px solid rgba(95,53,216,.14);
      border-radius:16px;
      padding:14px;
      background:rgba(255,255,255,.58);
    }
    .cloud-intro-card strong{
      display:block;
      margin-bottom:5px;
      color:#172036;
      font-size:14px;
    }
    .cloud-intro-card p{font-size:13px}
    .cloud-steps{
      margin:10px 0 0;
      padding:0;
      list-style:none;
      display:grid;
      gap:8px;
    }
    .cloud-steps li{
      display:flex;
      gap:8px;
      color:#5e6477;
      font-size:13px;
      line-height:1.35;
    }
    .cloud-steps span{
      flex:0 0 22px;
      width:22px;
      height:22px;
      border-radius:999px;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      background:linear-gradient(135deg,var(--accent),var(--cyan));
      color:#fff;
      font-size:12px;
      font-weight:900;
    }
    .cloud-form{
      display:none;
      margin-top:18px;
      border-top:1px solid var(--line);
      padding-top:18px;
    }
    .cloud.active .cloud-form{display:block}
    .cloud-grid{
      display:grid;
      grid-template-columns:repeat(2,minmax(0,1fr));
      gap:14px;
    }
    .cloud-grid .wide{grid-column:1/-1}
    .cloud-field-head{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      margin:14px 0 8px;
    }
    .cloud-field-head label{margin:0}
    .cloud-token-cta{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      min-height:44px;
      padding:0 18px;
      border-radius:999px;
      background:linear-gradient(135deg,#171a22 0%,#5f35d8 50%,#31c8df 100%);
      color:#fff;
      font-size:13px;
      font-weight:950;
      text-decoration:none;
      box-shadow:0 16px 36px rgba(95,53,216,.22);
      white-space:nowrap;
    }
    .cloud-token-cta:hover{transform:translateY(-1px);box-shadow:0 20px 44px rgba(95,53,216,.28)}
    .helper{
      margin-top:8px;
      color:var(--dim);
      font-size:12px;
      line-height:1.42;
    }
    .helper code{
      display:block;
      margin-top:6px;
      padding:10px;
      border:1px solid var(--line);
      border-radius:11px;
      background:rgba(255,255,255,.66);
      color:#4f5870;
      white-space:normal;
      word-break:break-word;
    }
    .cloud-result{
      display:none;
      margin-top:14px;
      border:1px solid rgba(48,215,180,.26);
      border-radius:16px;
      padding:14px;
      background:rgba(48,215,180,.09);
      color:#245d55;
      line-height:1.45;
    }
    .cloud-result.active{display:block}
    .cloud-result a{color:#5f35d8;font-weight:900}
    .cloud-open-button{
      display:flex;
      align-items:center;
      justify-content:center;
      width:100%;
      min-height:54px;
      margin:14px 0 10px;
      border-radius:16px;
      text-decoration:none;
      color:#fff !important;
      background:linear-gradient(135deg,var(--accent),var(--cyan));
      box-shadow:0 18px 42px rgba(95,53,216,.18);
    }
    .cloud-safe-note{
      border:1px solid rgba(95,53,216,.14);
      border-radius:13px;
      padding:10px 12px;
      background:rgba(255,255,255,.62);
      color:#4f5870;
      font-size:13px;
    }
    .cloud-direct{
      color:#6b7284;
      font-size:12px;
      word-break:break-word;
    }
    .keeper-box{
      margin-top:12px;
      border:1px solid rgba(95,53,216,.18);
      border-radius:14px;
      padding:12px;
      background:rgba(255,255,255,.58);
    }
    .keeper-box strong{display:block;margin-bottom:4px}
    .keeper-command{
      display:block;
      margin-top:8px;
      border:1px solid rgba(89,97,120,.16);
      border-radius:10px;
      padding:10px;
      background:#101318;
      color:#eaf2ff;
      font-size:11px;
      line-height:1.45;
      overflow-x:auto;
      white-space:pre-wrap;
      word-break:break-word;
    }
    @media (prefers-reduced-motion:reduce){
      *,*:before,*:after{scroll-behavior:auto!important;transition:none!important}
    }
    @media (max-width:860px){
      main{width:min(100% - 20px,720px);padding:16px 0}
      .hero{grid-template-columns:1fr;padding:22px}
      .brand{margin-bottom:26px}
      .cards,.improvements{grid-template-columns:1fr}
      .downloads{padding:24px 22px}
      .download-head{align-items:start;flex-direction:column}
      .download-tools{width:100%;justify-content:stretch}
      .docker-download,.logout-btn,.version{width:100%;text-align:center}
      .state-grid{grid-template-columns:1fr}
      .cloud-top{align-items:start;flex-direction:column}
      .cloud-actions{width:100%;justify-content:stretch}
      .cloud-toggle{width:100%}
      .cloud-link-button{width:100%}
      .cloud-intro{grid-template-columns:1fr}
      .cloud-grid{grid-template-columns:1fr}
      .cloud-field-head{align-items:stretch;flex-direction:column}
      .cloud-token-cta{width:100%}
      .aurora-orb{display:none}
      h1{font-size:clamp(34px,12vw,54px)}
    }
  </style>
</head>
<body>
  <main>
    <section class="shell">
      <div class="hero">
        <div>
          <div class="brand">
            <div class="mark" aria-hidden="true"></div>
            <div>
              <strong>Admira IA</strong>
              <span>Manager IA local/VPS para Meta Ads</span>
            </div>
          </div>
          <h1>Descarga tu <span class="gradient">manager IA</span> para Meta Ads</h1>
          <p class="copy">Entra con el email de compra y la clave de acceso que recibiste. Luego descarga el launcher Docker correcto para tu sistema.</p>
          <div class="aurora-orb" aria-hidden="true"></div>
        </div>
        <form class="login" id="loginForm">
          <h2>Acceso de comprador</h2>
          <p>Usa exactamente el email de compra. La clave es la que llega en el correo despues del pago.</p>
          <label for="buyerEmail">Email de compra</label>
          <input id="buyerEmail" name="buyer_email" type="email" autocomplete="email" placeholder="tu@email.com" required />
          <label for="accessPassword">Clave de acceso</label>
          <input id="accessPassword" name="access_password" type="password" autocomplete="current-password" placeholder="Pega tu clave aqui" required />
          <label class="remember-row" for="rememberAccess">
            <input id="rememberAccess" type="checkbox" checked />
            <span>Recordar este acceso en este navegador. No lo uses en computadores compartidos.</span>
          </label>
          <button class="primary" id="loginButton" type="submit">Acceder</button>
          <div class="status" id="status" role="status" aria-live="polite"></div>
        </form>
      </div>
      <div class="downloads" id="downloads">
        <section class="install-state" id="installState"></section>
        <div class="download-head">
          <div>
            <h2 id="downloadTitle">Elige tu sistema</h2>
            <p id="downloadSubtitle">Para instalacion local usa Docker Desktop: Mac, Windows y Linux descargan un launcher que abre Docker y prepara Admira IA.</p>
          </div>
          <div class="download-tools">
            <a class="docker-download" href="https://www.docker.com/products/docker-desktop/" target="_blank" rel="noreferrer">Descargar Docker Desktop</a>
            <button class="logout-btn" id="logoutButton" type="button">Cerrar sesion</button>
            <div class="version" id="version">Version lista</div>
          </div>
        </div>
        <section class="local-security-note">
          <strong>Consejo de seguridad para instalacion local</strong>
          <p>Usa Admira IA dentro de Docker y no expongas el dashboard local a internet con tuneles, puertos abiertos o reglas del router. Si quieres verlo desde el telefono, activalo desde Configuracion y usalo solo en la misma red Wi-Fi. Para acceso remoto real, usa la instalacion cloud recomendada.</p>
        </section>
        <div class="cards" id="cards"></div>
        <div class="improvements" id="improvements"></div>
        <section class="cloud" id="cloudInstall">
          <div class="cloud-top">
            <div>
              <h3>Instalar en la nube</h3>
              <p>Para dejar el manager encendido aunque tu PC este apagado. Recomendamos DigitalOcean porque es un servicio cloud confiable, estable y sencillo de pagar.</p>
            </div>
            <div class="cloud-actions">
              <a class="cloud-link-button" href="https://cloud.digitalocean.com/registrations/new" target="_blank" rel="noreferrer">Crear cuenta en DigitalOcean</a>
              <button class="cloud-toggle" id="cloudToggle" type="button">Instalar en DigitalOcean</button>
            </div>
          </div>
          <form class="cloud-form" id="cloudForm">
            <div class="cloud-intro">
              <div class="cloud-intro-card">
                <strong>Como funciona</strong>
                <p>Creas tu cuenta en DigitalOcean, agregas un metodo de pago y pegas aqui un token API. Con ese token, el portal crea automaticamente el servidor, instala Admira IA y deja listo el boton para entrar al dashboard.</p>
                <ul class="cloud-steps">
                  <li><span>1</span><b>Crea tu cuenta y metodo de pago.</b></li>
                  <li><span>2</span><b>Abre el area API de DigitalOcean y crea un token.</b></li>
                  <li><span>3</span><b>Pega el token y tu llave publica SSH aqui.</b></li>
                </ul>
              </div>
              <div class="cloud-intro-card">
                <strong>Costo esperado</strong>
                <p>DigitalOcean suele ofrecer credito inicial para cuentas nuevas. Despues, el servidor basico normalmente queda cerca de US$4 a US$6 al mes, segun el tamano elegido. Revisa siempre el precio final en DigitalOcean antes de crear el servidor.</p>
              </div>
            </div>
            <div class="cloud-grid">
              <div class="wide">
                <div class="cloud-field-head">
                  <label for="digitalOceanToken">Token de DigitalOcean</label>
                  <a class="cloud-token-cta" href="https://cloud.digitalocean.com/account/api/tokens" target="_blank" rel="noreferrer">Haz clic aqui para obtener el token</a>
                </div>
                <input id="digitalOceanToken" type="password" autocomplete="off" placeholder="Pega aqui tu token de DigitalOcean" required />
                <div class="helper" id="cloudTokenSavedStatus">Lo usamos para crear el servidor, instalar el producto y configurar el acceso seguro. En DigitalOcean crea un token sin fecha de vencimiento, o con una duracion larga, para que el servidor pueda recuperar acceso si tu IP cambia.</div>
              </div>
              <div class="wide">
                <label for="sshPublicKey">Llave publica SSH</label>
                <div class="cloud-safe-note">
                  <strong>Por que pedimos esto:</strong> la llave SSH hace que solo tu computador pueda entrar por la puerta tecnica del servidor. La parte privada queda guardada en tu PC y no se pega aqui. Aqui solo pegas la parte publica, que es segura de compartir y sirve para que DigitalOcean reconozca tu computador cuando intente acceder al servidor.
                </div>
                <textarea id="sshPublicKey" placeholder="ssh-ed25519 AAAA... tu@email.com" required></textarea>
                <div class="helper">
                  <strong>Si no tienes una llave, abre Terminal en tu computador y pega este comando.</strong>
                  Al final aparecera una linea larga que empieza por <strong>ssh-ed25519</strong>. Copia esa linea completa y pegala en el campo de arriba. No compartas la llave privada.
                  <code>ssh-keygen -t ed25519 -C "admiro-ai" -f ~/.ssh/admiro_ai && cat ~/.ssh/admiro_ai.pub</code>
                </div>
              </div>
              <div>
                <label for="cloudRegion">Region</label>
                <select id="cloudRegion">
                  <option value="nyc3">Nueva York</option>
                  <option value="sfo3">San Francisco</option>
                  <option value="tor1">Toronto</option>
                  <option value="ams3">Amsterdam</option>
                </select>
              </div>
              <div>
                <label for="cloudSize">Tamano del servidor</label>
                <select id="cloudSize">
                  <option value="s-1vcpu-1gb">Basico recomendado</option>
                  <option value="s-1vcpu-2gb">Mas comodo</option>
                  <option value="s-2vcpu-2gb">Agencia pequena</option>
                </select>
              </div>
            </div>
            <button class="primary" id="cloudButton" type="submit">Crear mi servidor</button>
            <div class="cloud-result" id="cloudResult" aria-live="polite"></div>
          </form>
        </section>
      </div>
    </section>
  </main>
  <script>
    const form = document.getElementById('loginForm');
    const statusBox = document.getElementById('status');
    const cards = document.getElementById('cards');
    const downloads = document.getElementById('downloads');
    const version = document.getElementById('version');
    const improvements = document.getElementById('improvements');
    const installState = document.getElementById('installState');
    const downloadTitle = document.getElementById('downloadTitle');
    const downloadSubtitle = document.getElementById('downloadSubtitle');
    const cloudInstall = document.getElementById('cloudInstall');
    const cloudToggle = document.getElementById('cloudToggle');
    const cloudForm = document.getElementById('cloudForm');
    const cloudResult = document.getElementById('cloudResult');
    const logoutButton = document.getElementById('logoutButton');
    let portalToken = '';
    let cloudProgressTimer = null;
    let cloudCreatePreviewTimer = null;
    let cloudRecoveryToken = '';
    let cloudRecoveryRetryTimer = null;
    let cloudStateVersion = 0;
    let cloudPollFailures = 0;
    let cloudDisplayedProgress = 0;
    let cloudResetInProgress = false;
    let cloudDeleteInProgress = false;

    function setStatus(message, isError = false){
      statusBox.textContent = message || '';
      statusBox.style.color = isError ? '#ef5d66' : '#5f35d8';
    }
    function escapeHtml(value){
      return String(value || '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    }
    function safeHttpUrl(value){
      try {
        const url = new URL(String(value || ''), window.location.origin);
        if(url.protocol === 'http:' || url.protocol === 'https:') return url.href;
      } catch(_err) {}
      return '';
    }
    function buyerCopy(value){
      return String(value || '')
        .replaceAll('licencias-admiro-ai.uboost.lat/descargas', 'admiroia.uboost.lat/access')
        .replaceAll('licencias-admiro-ai.uboost.lat', 'admiroia.uboost.lat')
        .replaceAll('licencias-miro-ai.uboost.lat', 'admiroia.uboost.lat');
    }
    async function postJson(url, body){
      const response = await fetch(url, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        credentials:'same-origin',
        cache:'no-store',
        body:JSON.stringify(body)
      });
      const data = await response.json().catch(() => ({}));
      if(!response.ok) throw new Error(data.detail || data.error || 'No se pudo completar la solicitud.');
      return data;
    }
    function renderCards(platforms){
      cards.innerHTML = platforms.map((platform) => {
        const disabled = !platform.available;
        return '<article class="card '+(disabled?'empty':'')+'">' +
          '<span class="badge">'+escapeHtml(platform.badge)+'</span>' +
          '<h3>'+escapeHtml(platform.label)+'</h3>' +
          '<p>'+escapeHtml(platform.description)+'</p>' +
          '<div class="file">'+(platform.available ? escapeHtml(platform.filename) : 'Instalador Docker pendiente de publicar')+'</div>' +
          '<button class="download-btn" data-platform="'+escapeHtml(platform.id)+'" '+(disabled?'disabled':'')+'>'+escapeHtml(platform.button)+'</button>' +
        '</article>';
      }).join('');
    }
    function renderImprovements(items){
      improvements.innerHTML = (items || []).slice(0,3).map((item) =>
        '<div class="improvement"><strong>'+escapeHtml(buyerCopy(item.title || 'Mejora incluida'))+'</strong><span>'+escapeHtml(buyerCopy(item.body || item.impact || ''))+'</span></div>'
      ).join('');
    }
    function clampProgress(value){
      const number = Number(value || 0);
      if(!Number.isFinite(number)) return 0;
      return Math.max(0, Math.min(100, Math.round(number)));
    }
    function cloudStageLabel(data){
      if(data.ready || data.status === 'ready') return 'Dashboard listo';
      const stage = String(data.stage || data.status || '').replaceAll('_',' ');
      if(stage.includes('detenida') || stage.includes('failed')) return 'Instalacion detenida';
      if(stage.includes('creando')) return 'Creando servidor';
      if(stage.includes('ip')) return 'Esperando IP';
      if(stage.includes('paquetes')) return 'Preparando sistema';
      if(stage.includes('descargando')) return 'Descargando producto';
      if(stage.includes('archivos')) return 'Preparando archivos';
      if(stage.includes('dependencias')) return 'Instalando componentes';
      if(stage.includes('instalando')) return 'Instalando Admira IA';
      if(stage.includes('verificando')) return 'Verificando dashboard';
      if(stage.includes('dashboard')) return 'Preparando dashboard';
      if(stage.includes('tardando')) return 'Tardando mas de lo normal';
      if(stage.includes('final')) return 'Verificando dashboard';
      return 'Preparando servidor';
    }
    function cloudProgressMarkup(data){
      const isReady = Boolean(data.ready || data.status === 'ready');
      const rawProgress = clampProgress(data.progress || (isReady ? 100 : 18));
      const nextProgress = isReady ? 100 : Math.min(98, rawProgress);
      cloudDisplayedProgress = Math.max(cloudDisplayedProgress, nextProgress);
      const progress = isReady ? 100 : cloudDisplayedProgress;
      return '<div class="cloud-progress" style="--progress:'+progress+'%"><span></span></div>' +
        '<div class="cloud-progress-meta"><span>'+escapeHtml(cloudStageLabel(data))+'</span><span>'+progress+'%</span></div>';
    }
    function stopCloudCreatePreview(){
      if(cloudCreatePreviewTimer){
        clearInterval(cloudCreatePreviewTimer);
        cloudCreatePreviewTimer = null;
      }
    }
    function stopCloudProgressPolling(invalidate = false){
      if(cloudProgressTimer){
        clearInterval(cloudProgressTimer);
        cloudProgressTimer = null;
      }
      if(invalidate) cloudStateVersion += 1;
      cloudPollFailures = 0;
    }
    async function pollCloudProgress(expectedVersion = cloudStateVersion){
      if(!portalToken || cloudResetInProgress || cloudDeleteInProgress) return;
      const tokenInput = document.getElementById('digitalOceanToken');
      const recoveryToken = cloudRecoveryToken || (tokenInput ? tokenInput.value.trim() : '');
      const data = await postJson('/api/portal/cloud/digitalocean', { portal_token: portalToken, action: 'status', digitalocean_token: recoveryToken });
      if(expectedVersion !== cloudStateVersion) return data;
      cloudPollFailures = 0;
      if(!data.valid) throw new Error(data.detail || 'No pude revisar la instalacion.');
      if(data.cleared_deleted_cloud){
        stopCloudProgressPolling();
        cloudResult.classList.remove('active');
        cloudResult.innerHTML = '';
        renderInstallState(data);
        setStatus(data.detail || 'El servidor anterior ya no existe. Puedes crear uno nuevo.');
        return data;
      }
      if(data.status === 'not_started'){
        if(cloudResult.classList.contains('active')){
          setStatus(data.detail || 'Sigo revisando la instalacion. Si acabas de crear el servidor, espera unos segundos.');
          return data;
        }
        stopCloudProgressPolling();
        cloudResult.classList.remove('active');
        cloudResult.innerHTML = '';
        renderInstallState(data);
        setStatus(data.detail || 'Todavia no hay instalacion cloud.');
        return data;
      }
      renderCloudResult(data);
      renderInstallState({
        cloud_installation: data,
        install_state: {
          cloud: {
            installed: Boolean(data.provider || data.droplet_id || data.cloud_open_url || data.dashboard_url),
            status: data.status,
            dashboard_available: Boolean(data.ready),
            progress: data.progress
          },
          local: {}
        }
      });
      if(data.ready || data.status === 'ready'){
        stopCloudProgressPolling(true);
        cloudDisplayedProgress = 100;
        setStatus('Listo. Ya puedes acceder a tu dashboard.');
      }
      return data;
    }
    function handleCloudProgressError(error, expectedVersion = cloudStateVersion){
      if(expectedVersion !== cloudStateVersion) return;
      cloudPollFailures += 1;
      const message = cloudPollFailures > 1
        ? 'Sigo intentando leer el avance. Si DigitalOcean ya termino, lo detectare automaticamente en la siguiente revision.'
        : 'Estoy revisando el avance otra vez...';
      setStatus(message);
      if(cloudResult.classList.contains('active') && cloudPollFailures > 2){
        const note = '<div class="cloud-safe-note"><strong>Sigo revisando.</strong> La instalacion puede terminar aunque una revision falle. No necesitas refrescar; esta pagina vuelve a consultar sola.</div>';
        if(!cloudResult.innerHTML.includes('La instalacion puede terminar aunque una revision falle')){
          cloudResult.insertAdjacentHTML('beforeend', note);
        }
      }
      window.setTimeout(() => {
        pollCloudProgress(expectedVersion).catch((retryError) => handleCloudProgressError(retryError, expectedVersion));
      }, Math.min(12000, 2500 + cloudPollFailures * 1500));
    }
    function scheduleCloudTokenRecovery(){
      const tokenInput = document.getElementById('digitalOceanToken');
      const value = tokenInput ? tokenInput.value.trim() : '';
      cloudRecoveryToken = value;
      if(!portalToken || value.length < 40) return;
      if(cloudRecoveryRetryTimer) clearTimeout(cloudRecoveryRetryTimer);
      cloudRecoveryRetryTimer = setTimeout(() => {
        pollCloudProgress().catch(() => {});
      }, 650);
    }
    function startCloudProgressPolling(){
      if(cloudResetInProgress || cloudDeleteInProgress) return;
      stopCloudCreatePreview();
      stopCloudProgressPolling();
      cloudDisplayedProgress = 0;
      const expectedVersion = ++cloudStateVersion;
      cloudPollFailures = 0;
      pollCloudProgress(expectedVersion).catch((error) => handleCloudProgressError(error, expectedVersion));
      cloudProgressTimer = setInterval(() => {
        pollCloudProgress(expectedVersion).catch((error) => handleCloudProgressError(error, expectedVersion));
      }, 5000);
    }
    function renderCloudCreatePreview(progress = 8){
      const progressData = { status:'creating_request', stage:'creando_servidor', progress };
      downloadTitle.textContent = 'Creando tu servidor';
      downloadSubtitle.textContent = 'Estoy pidiendo a DigitalOcean que cree el Droplet y deje lista la instalacion.';
      installState.innerHTML =
        '<h2>Creando tu servidor cloud</h2>' +
        '<p>No cierres esta pagina. Primero DigitalOcean crea el servidor; despues Admira IA se instala solo y aqui aparecera el boton para entrar.</p>' +
        '<div class="state-grid">' +
          '<div class="state-card">' +
            '<span class="state-pill pending">Creacion iniciada</span>' +
            '<strong>DigitalOcean esta preparando tu Droplet</strong>' +
            '<p>Este primer paso puede tardar unos segundos. Luego veras el avance real de instalacion.</p>' +
            cloudProgressMarkup(progressData) +
          '</div>' +
          '<div class="state-card">' +
            '<span class="state-pill empty">Siguiente</span>' +
            '<strong>Instalacion automatica</strong>' +
            '<p>Cuando DigitalOcean responda, revisare el dashboard cada pocos segundos hasta que quede listo.</p>' +
          '</div>' +
        '</div>';
      installState.classList.add('active');
      cloudResult.innerHTML =
        '<strong>Creando tu servidor en DigitalOcean.</strong>' +
        '<p>Ya empece. Puedes dejar esta pagina abierta; la barra se actualiza sola.</p>' +
        cloudProgressMarkup(progressData) +
        '<span class="cloud-open-button pending" aria-disabled="true">Creando servidor...</span>';
      cloudResult.classList.add('active');
    }
    function startCloudCreatePreview(){
      stopCloudCreatePreview();
      let previewProgress = 8;
      renderCloudCreatePreview(previewProgress);
      cloudCreatePreviewTimer = setInterval(() => {
        previewProgress = Math.min(32, previewProgress + (previewProgress < 18 ? 3 : 2));
        renderCloudCreatePreview(previewProgress);
      }, 2400);
    }
    function updateDigitalOceanTokenUi(cloudSecrets){
      const tokenInput = document.getElementById('digitalOceanToken');
      const status = document.getElementById('cloudTokenSavedStatus');
      if(tokenInput){
        tokenInput.required = true;
        tokenInput.placeholder = 'Pega aqui tu token de DigitalOcean';
      }
      if(status){
        status.textContent = 'Lo usamos para crear el servidor, instalar el producto y configurar el acceso seguro. En DigitalOcean crea un token sin fecha de vencimiento, o con una duracion larga, para que el servidor pueda recuperar acceso si tu IP cambia.';
      }
    }
    function cloudOpenButtonMarkup(openUrl, directOnly){
      const label = directOnly ? 'Probar enlace directo' : 'Acceder a mi dashboard';
      return '<button class="cloud-open-button" type="button" data-cloud-open-url="'+escapeHtml(openUrl)+'" aria-label="Abrir mi dashboard">'+label+'</button>';
    }
    function renderInstallState(data){
      const state = data.install_state || {};
      const cloud = state.cloud || {};
      const local = state.local || {};
      const cloudInstallation = data.cloud_installation || {};
      const openUrl = safeHttpUrl(cloudInstallation.cloud_open_url || cloudInstallation.dashboard_url || '');
      const hasCloudRecord = Boolean(cloud.installed || cloudInstallation.droplet_id || cloudInstallation.provider || cloudInstallation.cloud_open_url || cloudInstallation.dashboard_url || cloudInstallation.firewall_id);
      if(hasCloudRecord){
        const ready = Boolean(openUrl && (cloud.dashboard_available || cloud.status === 'ready' || cloudInstallation.ready));
        const failed = Boolean(cloud.status === 'failed' || cloudInstallation.status === 'failed' || cloudInstallation.install_status === 'failed' || cloudInstallation.failed);
        const takingLonger = Boolean(cloud.taking_longer || cloud.status === 'taking_longer' || cloudInstallation.taking_longer);
        const waitingForIp = Boolean(cloud.status === 'waiting_for_ip' || cloudInstallation.status === 'waiting_for_ip' || cloudInstallation.install_status === 'waiting_for_ip' || (!openUrl && (cloudInstallation.droplet_id || cloudInstallation.provider)));
        const directOnly = Boolean(openUrl && !cloudInstallation.cloud_open_url && (cloudInstallation.attached_ip_at || cloudInstallation.direct_open_only || cloud.direct_open_only));
        const progressData = { ...cloudInstallation, ...cloud, ready, progress: cloud.progress || cloudInstallation.progress || (ready ? 100 : 18), status: failed ? 'failed' : (ready ? 'ready' : (cloud.status || cloudInstallation.install_status || 'installing')) };
        downloadTitle.textContent = 'Opciones de instalacion';
        downloadSubtitle.textContent = ready ? 'Tu servidor cloud ya existe. Los launchers Docker quedan abajo solo por si quieres instalar en otro equipo.' : (failed ? 'Esta instalacion se detuvo. Borra ese Droplet en DigitalOcean y crea uno nuevo desde aqui.' : (waitingForIp ? 'DigitalOcean ya creo el servidor. Estoy conectando el IP automaticamente.' : 'Tu servidor cloud se esta preparando. Te aviso aqui cuando puedas entrar.'));
        installState.innerHTML =
          '<h2>Estado de tu instalacion: '+(ready?'cloud lista':(failed?'cloud detenida':(waitingForIp?'cloud conectando IP':(takingLonger?'cloud tardando mas de lo normal':'cloud en preparacion'))))+'</h2>' +
          '<p>'+(ready?'Cuando quieras entrar, usa este boton. Primero prepara tu red de forma segura y despues abre el dashboard.':(failed?'La instalacion anterior no pudo terminar. Ya corregimos el instalador; empieza limpio con un Droplet nuevo.':(waitingForIp?'El servidor existe. Normalmente se conecta solo en unos minutos; deja esta pagina abierta.':(takingLonger?'DigitalOcean ya puede mostrar el Droplet activo, pero todavia no pude confirmar el dashboard. Sigo revisando.':'Estamos instalando el producto en DigitalOcean. Puedes dejar esta pagina abierta; el boton aparece cuando termine.'))))+'</p>' +
          '<div class="state-grid">' +
            '<div class="state-card">' +
              '<span class="state-pill '+(ready?'':(failed?'empty':'pending'))+'">'+(ready?'Instalacion cloud lista':(failed?'Necesita empezar de nuevo':(waitingForIp?'Conectando servidor':(takingLonger?'Revisando instalacion':'Instalacion en progreso'))))+'</span>' +
              '<strong>'+(ready?'Accede a tu dashboard':(failed?'Borra el Droplet y crea otro':(waitingForIp?'Esperando conexion automatica':(takingLonger?'Todavia no esta listo':'Preparando tu dashboard'))))+'</strong>' +
              '<p>'+(ready?'Tu dashboard ya puede abrirse.':(failed?'Puedes borrar el Droplet desde aqui o marcarlo como borrado si ya lo eliminaste manualmente.':(waitingForIp?'El Droplet va a avisar su IP al portal. Pega el IPv4 solo si esto no avanza despues de varios minutos.':(takingLonger?'Si sigue asi, abre la consola del Droplet y revisa el log de instalacion.':'Normalmente tarda 5 a 10 minutos. Estoy verificando automaticamente.'))))+'</p>' +
              cloudProgressMarkup(progressData) +
              '<div class="state-actions">'+((ready || directOnly) && openUrl?cloudOpenButtonMarkup(openUrl, directOnly):(failed?'<span class="cloud-open-button pending" aria-disabled="true">Instalacion detenida</span>':(waitingForIp?recoverWaitingForIpMarkup(cloudInstallation):'<span class="cloud-open-button pending" aria-disabled="true">Dashboard preparando...</span>')))+refreshCloudAccessMarkup()+'</div>' +
            '</div>' +
            '<div class="state-card">' +
              '<span class="state-pill empty">Datos guardados en tu licencia</span>' +
              '<strong>'+escapeHtml(cloudInstallation.droplet_name || 'Servidor DigitalOcean')+'</strong>' +
              '<p>Creado: '+escapeHtml((cloudInstallation.created_at || '').slice(0,10) || 'reciente')+'</p>' +
              '<p class="cloud-reset-note">Si quieres reinstalar, primero elimina este servidor real o marca que ya lo borraste manualmente.</p>' +
              '<p class="cloud-direct">Enlace del dashboard: '+escapeHtml(cloudInstallation.dashboard_url || 'preparando IP')+(cloudInstallation.dashboard_http_url && cloudInstallation.dashboard_http_url !== cloudInstallation.dashboard_url?'<br>Respaldo por IP: '+escapeHtml(cloudInstallation.dashboard_http_url):'')+'</p>' +
              (hasCloudRecord ? cloudManagementMarkup() : resetCloudInstallMarkup()) +
            '</div>' +
          '</div>';
        installState.classList.add('active');
        return 'cloud';
      }
      if(local.activated){
        downloadTitle.textContent = 'Opciones de instalacion';
        downloadSubtitle.textContent = 'Detectamos una instalacion local activada. Usa esta area solo si vas a reinstalar o cambiar de equipo.';
        const completed = Boolean(local.onboarding_completed_at);
        installState.innerHTML =
          '<h2>Estado de tu instalacion: local activada</h2>' +
          '<p>Para abrirla, usa el icono o acceso directo en el computador donde instalaste Admira IA. Desde aqui puedes descargar otra vez si necesitas reinstalar.</p>' +
          '<div class="state-grid">' +
            '<div class="state-card">' +
              '<span class="state-pill '+(completed?'':'pending')+'">'+(completed?'Onboarding completado':'Onboarding pendiente o no reportado')+'</span>' +
              '<strong>Estado local</strong>' +
              '<p>Equipos registrados: '+escapeHtml(local.device_count || 1)+'</p>' +
              '<p>Ultima activacion: '+escapeHtml((local.last_activation_at || '').slice(0,10) || 'reciente')+'</p>' +
            '</div>' +
            '<div class="state-card">' +
              '<span class="state-pill empty">Siguiente paso</span>' +
              '<strong>'+ (completed ? 'Abre tu dashboard local' : 'Termina la guia inicial') +'</strong>' +
              '<p>'+ (completed ? 'La configuracion se cambia desde el dashboard instalado.' : 'Cuando completes la guia, este portal lo mostrara como listo.') +'</p>' +
            '</div>' +
          '</div>';
        installState.classList.add('active');
        return 'local';
      }
      downloadTitle.textContent = 'Elige tu sistema';
      downloadSubtitle.textContent = 'Aun no vemos una instalacion activa. Para tu PC/Mac/Linux elige un launcher Docker; para nube crea un servidor en DigitalOcean.';
      installState.innerHTML =
        '<h2>Estado de tu instalacion: aun no instalada</h2>' +
        '<p>Empieza con una de las opciones de abajo. Si quieres que el agente quede encendido siempre, elige DigitalOcean.</p>' +
        '<div class="state-grid">' +
          '<div class="state-card"><span class="state-pill empty">PC o laptop</span><strong>Instalacion local con Docker</strong><p>Descarga el launcher de tu sistema, abre Docker Desktop y sigue la guia inicial.</p></div>' +
          '<div class="state-card"><span class="state-pill empty">Siempre encendido</span><strong>Instalacion cloud</strong><p>Crea un servidor en tu propia cuenta de DigitalOcean.</p></div>' +
        '</div>';
      installState.classList.add('active');
      return 'new';
    }
    function renderCloudResult(data){
      const dropletIp = data.droplet_ip || String(data.dashboard_http_url || data.dashboard_url || '').replace(/^https?:\\/\\//,'').split(':')[0];
      const openUrl = safeHttpUrl(data.cloud_open_url || data.dashboard_url || '');
      const ready = Boolean(openUrl && (data.ready || data.status === 'ready' || data.install_status === 'ready'));
      const failed = Boolean(data.failed || data.status === 'failed' || data.install_status === 'failed');
      const takingLonger = Boolean(data.taking_longer || data.status === 'taking_longer');
      const waitingForIp = Boolean(data.status === 'waiting_for_ip' || data.install_status === 'waiting_for_ip' || data.stage === 'esperando_ip' || (!openUrl && (data.droplet_id || data.droplet_name)));
      const directOnly = Boolean(openUrl && !data.cloud_open_url && (data.attached_ip_at || data.direct_open_only || data.stage === 'ip_guardada_sin_gate'));
      const title = ready ? 'Tu servidor cloud ya esta listo.' : (failed ? 'Esta instalacion se detuvo.' : (waitingForIp ? 'DigitalOcean creo el servidor. Estoy conectando el IP.' : (takingLonger ? 'La instalacion esta tardando mas de lo normal.' : 'Instalando tu servidor cloud.')));
      const openButton = (ready || directOnly) && openUrl
        ? cloudOpenButtonMarkup(openUrl, directOnly)
        : (failed ? '<span class="cloud-open-button pending" aria-disabled="true">Instalacion detenida</span>' : (waitingForIp ? recoverWaitingForIpMarkup(data) : '<span class="cloud-open-button pending" aria-disabled="true">'+(openUrl?'Dashboard preparando...':'DigitalOcean esta asignando la IP...')+'</span>'));
      const direct = data.dashboard_url
        ? '<p class="cloud-direct">Enlace del dashboard: '+escapeHtml(data.dashboard_url)+(data.dashboard_http_url && data.dashboard_http_url !== data.dashboard_url?'<br>Respaldo por IP: '+escapeHtml(data.dashboard_http_url):'')+(data.cloud_open_url?'<br>Si tu internet cambia de IP, usa siempre el boton de arriba.':'<br>Este enlace directo puede depender de que tu IP actual siga permitida en el firewall.')+'</p>'
        : '';
      const ssh = data.ssh_command ? '<p class="cloud-direct">Acceso tecnico de respaldo para soporte: '+escapeHtml(data.ssh_command)+'</p>' : '';
      const delayNote = takingLonger ? '<div class="cloud-safe-note"><strong>Importante:</strong> en DigitalOcean el Droplet puede verse como activo aunque Admira IA siga instalando Docker y el dashboard. Si pasan varios minutos mas, abre la consola del Droplet y revisa <code>tail -n 80 /var/log/admiro-cloud-install.log</code>.</div>' : '';
      const keeper = dropletIp ? '<div class="keeper-box"><strong>Protector automatico de acceso</strong><p>Incluido en el servidor cloud: cuando abres el boton de dashboard, el Droplet prepara tu red antes de cargar. No necesitas correr comandos para esto.</p><span class="cloud-direct" data-helper-endpoints="/api/portal/cloud/access-keeper /api/portal/cloud/access-keeper-ps">El helper local por hora queda disponible solo como respaldo avanzado.</span></div>' : '';
      cloudResult.innerHTML =
        '<strong>'+title+'</strong>' +
        '<p>'+(ready?'Ya puedes entrar. Usa siempre este boton para preparar tu red antes de abrir el dashboard.':(failed?'El instalador de ese Droplet se detuvo. Puedes borrarlo desde aqui o marcarlo como borrado si ya lo eliminaste manualmente.':(waitingForIp?'Puedes dejar esta pagina abierta. El Droplet reporta su IP automaticamente; usa el campo manual solo si se queda detenido.':(takingLonger?'El servidor existe, pero todavia no pude confirmar que el dashboard este listo. Sigo revisando automaticamente.':'Espera 5 a 10 minutos. Puedes dejar esta pagina abierta; reviso el avance automaticamente.'))))+'</p>' +
        cloudProgressMarkup(data) +
        openButton +
        refreshCloudAccessMarkup() +
        cloudManagementMarkup() +
        '<div class="cloud-safe-note">El boton prepara tu red automaticamente antes de abrir el dashboard. Si tu internet cambia de IP, no tienes que saberlo ni hacer nada especial.</div>' +
        delayNote +
        direct +
        ssh +
        keeper +
        '<p>'+escapeHtml(data.next_step || 'Cuando abra el dashboard, completa el onboarding.')+'</p>';
      cloudResult.classList.add('active');
    }
    function attachIpMarkup(data){
      const help = data.can_attach_ip === false
        ? '<p class="cloud-direct">Respaldo manual: esta instalacion se creo antes del auto-reporte de IP. Pega el IPv4 para probar enlace directo; si no abre, recrea el servidor.</p>'
        : '<p class="cloud-direct">Respaldo manual: normalmente no hace falta. Si pasan varios minutos, copia el IPv4 publico del Droplet y pegalo aqui.</p>';
      return '<form class="cloud-ip-form" onsubmit="attachDropletIp(event)">' +
        '<input id="dropletIpInput" inputmode="decimal" placeholder="IPv4 del Droplet, ej. 123.45.67.89" aria-label="IPv4 publico del Droplet">' +
        '<button class="cloud-open-button" type="submit">Guardar IP y revisar</button>' +
        help +
      '</form>';
    }
    function recoverWaitingForIpMarkup(data){
      return '<div class="cloud-ip-form">' +
        '<button class="cloud-open-button" type="button" onclick="focusDigitalOceanToken()">Buscar automaticamente con mi token</button>' +
        '<p class="cloud-direct">Si se queda en este paso, pega tu token de DigitalOcean abajo para encontrar el servidor y seguir.</p>' +
        '<details class="cloud-direct"><summary>Respaldo tecnico: pegar IPv4 manualmente</summary>'+attachIpMarkup(data)+'</details>' +
      '</div>';
    }
    function refreshCloudAccessMarkup(){
      return '<div class="cloud-ip-form">' +
        '<button class="cloud-open-button" type="button" onclick="refreshCloudAccess()">Actualizar acceso de esta red</button>' +
        '<p class="cloud-reset-note">Usalo si cambiaste de Wi-Fi, si SSH no entra, o si el portal se queda revisando. Autoriza esta red sin mostrar tu token.</p>' +
      '</div>';
    }
    function resetCloudInstallMarkup(){
      return '<div class="cloud-ip-form">' +
        '<button class="cloud-reset-button" type="button" data-cloud-action="reset-install">Ya lo borre manualmente. Crear uno nuevo</button>' +
        '<p class="cloud-reset-note">Esto solo limpia la memoria del portal. Antes de usarlo, borra el Droplet viejo en DigitalOcean para evitar cobros duplicados.</p>' +
      '</div>';
    }
    function cloudManagementMarkup(){
      return '<div class="cloud-ip-form cloud-danger-zone">' +
        '<strong>Reinstalar o borrar servidor</strong>' +
        '<button class="cloud-delete-button" type="button" data-cloud-action="delete-droplet">Borrar servidor en DigitalOcean ahora</button>' +
        '<p class="cloud-reset-note">Esto llama a DigitalOcean, apaga el Droplet real y luego limpia el portal para que puedas crear uno nuevo. Si el token guardado vencio, pega tu token abajo y vuelve a tocar el boton.</p>' +
        '<button class="cloud-reset-button" type="button" data-cloud-action="reset-install">Ya lo borre manualmente. Crear uno nuevo</button>' +
        '<p class="cloud-reset-note">Usa esta segunda opcion solo si ya lo eliminaste dentro de DigitalOcean y aqui sigue apareciendo.</p>' +
      '</div>';
    }
    function focusDigitalOceanToken(){
      cloudInstall.classList.add('active');
      cloudToggle.textContent = 'Ocultar instalacion cloud';
      cloudInstall.scrollIntoView({behavior:'smooth', block:'start'});
      const tokenInput = document.getElementById('digitalOceanToken');
      if(tokenInput) tokenInput.focus();
      startCloudProgressPolling();
      setStatus('Pega tu token de DigitalOcean y revisare el servidor automaticamente.');
    }
    async function attachDropletIp(event){
      event.preventDefault();
      const input = document.getElementById('dropletIpInput');
      const ip = input ? input.value.trim() : '';
      if(!ip){
        setStatus('Pega el IPv4 publico del Droplet.', true);
        return;
      }
      setStatus('Guardando IP del Droplet...');
      const data = await postJson('/api/portal/cloud/digitalocean', { portal_token: portalToken, action: 'attach_ip', droplet_ip: ip });
      if(!data.valid){
        setStatus(data.detail || 'No pude guardar ese IP.', true);
        return;
      }
      renderCloudResult(data);
      startCloudProgressPolling();
      setStatus('IP guardado. Sigo revisando la instalacion.');
    }
    async function refreshCloudAccess(){
      if(!portalToken) return;
      setStatus('Actualizando acceso de esta red...');
      try{
        const typedToken = document.getElementById('digitalOceanToken')?.value.trim() || '';
        const data = await postJson('/api/portal/cloud/digitalocean', {
          portal_token: portalToken,
          action: 'refresh_access',
          digitalocean_token: typedToken
        });
        if(!data.valid){
          setStatus(data.detail || 'No pude actualizar el acceso. Pega tu token de DigitalOcean y vuelve a intentar.', true);
          return;
        }
        renderCloudResult(data);
        renderInstallState({ cloud_installation: data, install_state: { cloud: { installed:true, status:data.status || 'installing', dashboard_available:Boolean(data.ready), progress:data.progress || 38 }, local: {} } });
        startCloudProgressPolling();
        setStatus(data.detail || 'Acceso actualizado. Intenta abrir o conectar por SSH otra vez.');
      }catch(error){
        setStatus(error.message || 'No pude actualizar el acceso de esta red.', true);
      }
    }
    async function openCloudDashboard(button){
      if(!portalToken || !button) return;
      const originalLabel = button.textContent;
      const fallbackUrl = safeHttpUrl(button.dataset.cloudOpenUrl || '');
      let pendingWindow = null;
      try{
        pendingWindow = window.open('about:blank', '_blank');
        if(pendingWindow){
          pendingWindow.opener = null;
          pendingWindow.document.write('<p style="font-family:system-ui;padding:24px">Preparando acceso seguro...</p>');
        }
      }catch{}
      button.disabled = true;
      button.textContent = 'Preparando acceso...';
      setStatus('Actualizando acceso de esta red antes de abrir...');
      try{
        const typedToken = document.getElementById('digitalOceanToken')?.value.trim() || '';
        const data = await postJson('/api/portal/cloud/digitalocean', {
          portal_token: portalToken,
          action: 'refresh_access',
          digitalocean_token: typedToken
        });
        if(!data.valid){
          if(fallbackUrl){
            if(pendingWindow){
              pendingWindow.location.href = fallbackUrl;
            }else{
              window.open(fallbackUrl, '_blank', 'noreferrer');
            }
            setStatus((data.detail || 'No pude actualizar el acceso desde el portal.') + ' Estoy intentando abrir con el acceso seguro del servidor.');
            return;
          }
          if(pendingWindow) pendingWindow.close();
          if(data.status === 'digitalocean_token_required') focusDigitalOceanToken();
          setStatus(data.detail || 'No pude actualizar el acceso. Pega tu token de DigitalOcean y vuelve a intentar.', true);
          return;
        }
        renderCloudResult(data);
        renderInstallState({ cloud_installation: data, install_state: { cloud: { installed:true, status:data.status || 'ready', dashboard_available:Boolean(data.ready || data.dashboard_url), progress:data.progress || 100 }, local: {} } });
        const directUrl = safeHttpUrl(data.cloud_open_url || fallbackUrl || data.dashboard_url || data.dashboard_https_url || data.dashboard_http_url || '');
        if(!directUrl){
          if(pendingWindow) pendingWindow.close();
          setStatus('Acceso actualizado, pero todavia no tengo enlace de dashboard. Espera unos segundos y vuelve a intentar.', true);
          return;
        }
        setStatus(data.detail || 'Acceso actualizado. Abriendo dashboard...');
        if(pendingWindow){
          pendingWindow.location.href = directUrl;
        }else{
          window.open(directUrl, '_blank', 'noreferrer');
        }
        startCloudProgressPolling();
      }catch(error){
        if(fallbackUrl){
          if(pendingWindow){
            pendingWindow.location.href = fallbackUrl;
          }else{
            window.open(fallbackUrl, '_blank', 'noreferrer');
          }
          setStatus((error.message || 'No pude preparar el acceso desde el portal.') + ' Estoy intentando abrir con el acceso seguro del servidor.');
          return;
        }
        if(pendingWindow) pendingWindow.close();
        setStatus(error.message || 'No pude preparar el acceso de esta red.', true);
      }finally{
        if(button.isConnected){
          button.disabled = false;
          button.textContent = originalLabel;
        }
      }
    }
    async function resetCloudInstall(button){
      if(!portalToken || cloudResetInProgress) return;
      const confirmed = window.confirm('Confirma que ya borraste el Droplet anterior en DigitalOcean. El portal solo olvidara ese servidor y te dejara crear uno nuevo.');
      if(!confirmed) return;
      cloudResetInProgress = true;
      const originalLabel = button ? button.textContent : '';
      if(button){button.disabled = true;button.textContent = 'Preparando reinstalacion...';}
      stopCloudCreatePreview();
      stopCloudProgressPolling(true);
      cloudDisplayedProgress = 0;
      const expectedVersion = cloudStateVersion;
      setStatus('Limpiando el servidor anterior del portal...');
      try{
        const data = await postJson('/api/portal/cloud/digitalocean', { portal_token: portalToken, action: 'reset_cloud_install' });
        if(expectedVersion !== cloudStateVersion) return;
        if(!data.valid){
          setStatus(data.detail || 'No pude limpiar esa instalacion.', true);
          return;
        }
        cloudResult.classList.remove('active');
        cloudResult.innerHTML = '';
        renderInstallState(data);
        cloudInstall.classList.add('active');
        cloudToggle.textContent = 'Ocultar instalacion cloud';
        const tokenInput = document.getElementById('digitalOceanToken');
        if(tokenInput) tokenInput.focus();
        cloudInstall.scrollIntoView({behavior:'smooth', block:'start'});
        setStatus('Listo. Ahora puedes crear un servidor nuevo.');
      }catch(error){
        if(expectedVersion === cloudStateVersion){
          setStatus(error.message || 'No pude limpiar esa instalacion.', true);
        }
      }finally{
        cloudResetInProgress = false;
        if(button && button.isConnected){button.disabled = false;button.textContent = originalLabel;}
      }
    }
    async function deleteCloudDroplet(button){
      if(!portalToken || cloudDeleteInProgress) return;
      const confirmed = window.confirm('Voy a borrar el Droplet real en DigitalOcean y limpiar el portal. Esto apaga ese servidor. ¿Continuar?');
      if(!confirmed) return;
      cloudDeleteInProgress = true;
      const originalLabel = button ? button.textContent : '';
      if(button){button.disabled = true;button.textContent = 'Borrando servidor...';}
      stopCloudCreatePreview();
      stopCloudProgressPolling(true);
      cloudDisplayedProgress = 0;
      const expectedVersion = cloudStateVersion;
      setStatus('Borrando el Droplet en DigitalOcean...');
      try{
        const typedToken = document.getElementById('digitalOceanToken')?.value.trim() || '';
        const data = await postJson('/api/portal/cloud/digitalocean', {
          portal_token: portalToken,
          action: 'delete_cloud_install',
          digitalocean_token: typedToken
        });
        if(expectedVersion !== cloudStateVersion) return;
        if(!data.valid){
          if(data.status === 'digitalocean_token_required') focusDigitalOceanToken();
          setStatus(data.detail || 'No pude borrar ese servidor.', true);
          return;
        }
        cloudResult.classList.remove('active');
        cloudResult.innerHTML = '';
        renderInstallState(data);
        cloudInstall.classList.add('active');
        cloudToggle.textContent = 'Ocultar instalacion cloud';
        const tokenInput = document.getElementById('digitalOceanToken');
        if(tokenInput) tokenInput.focus();
        cloudInstall.scrollIntoView({behavior:'smooth', block:'start'});
        setStatus(data.detail || 'Servidor borrado. Ahora puedes crear uno nuevo.');
      }catch(error){
        if(expectedVersion === cloudStateVersion){
          setStatus(error.message || 'No pude borrar ese servidor.', true);
        }
      }finally{
        cloudDeleteInProgress = false;
        if(button && button.isConnected){button.disabled = false;button.textContent = originalLabel;}
      }
    }
    function renderPortalData(data){
      portalToken = data.portal_token;
      updateDigitalOceanTokenUi(data.cloud_secrets || {});
      version.textContent = 'Version ' + (data.version || 'stable');
      renderCards(data.platforms || []);
      renderImprovements(data.improvements || []);
      downloads.classList.add('active');
      const installKind = renderInstallState(data);
      if(data.cloud_installation){
        cloudInstall.classList.add('active');
        cloudToggle.textContent = 'Ocultar instalacion cloud';
        renderCloudResult({...data.cloud_installation, status:data.install_state?.cloud?.status, ready:data.install_state?.cloud?.dashboard_available, progress:data.install_state?.cloud?.progress, existing:true, next_step:'Puedes cambiar configuracion dentro del dashboard cuando abras el producto.'});
        if(!(data.install_state?.cloud?.dashboard_available || data.install_state?.cloud?.status === 'ready')){
          startCloudProgressPolling();
        }
      }
      installState.scrollIntoView({behavior:'smooth', block:'start'});
      setStatus(installKind === 'cloud' ? 'Listo. Tu dashboard en la nube aparece abajo.' : (installKind === 'local' ? 'Listo. Detecte una instalacion local activa.' : 'Listo. Elige como instalar abajo.'));
    }
    async function restorePortalSession(){
      setStatus('Revisando si ya tenias acceso guardado...');
      try{
        const response = await fetch('/api/portal/session', { method:'GET', credentials:'same-origin' });
        const data = await response.json().catch(() => ({}));
        if(!response.ok || !data.valid){
          setStatus('');
          return;
        }
        renderPortalData(data);
        setStatus('Acceso restaurado.');
      }catch{
        setStatus('');
      }
    }
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = document.getElementById('loginButton');
      button.disabled = true;
      setStatus('Confirmando acceso...');
      try{
        const payload = {
          buyer_email: document.getElementById('buyerEmail').value,
          access_password: document.getElementById('accessPassword').value,
          remember_access: document.getElementById('rememberAccess').checked
        };
        const data = await postJson('/api/portal/session', payload);
        if(!data.valid) throw new Error(data.detail || 'No pude confirmar tu acceso.');
        renderPortalData(data);
      }catch(error){
        setStatus(error.message || 'No pude confirmar tu acceso.', true);
      }finally{
        button.disabled = false;
      }
    });
    cards.addEventListener('click', async (event) => {
      const button = event.target.closest('button[data-platform]');
      if(!button || button.disabled) return;
      button.disabled = true;
      const original = button.textContent;
      button.textContent = 'Preparando...';
      try{
        const data = await postJson('/api/portal/download', { portal_token: portalToken, platform: button.dataset.platform });
        if(!data.valid || !data.download_url) throw new Error(data.detail || 'No pude preparar la descarga.');
        window.location.href = data.download_url;
      }catch(error){
        setStatus(error.message || 'No pude preparar la descarga.', true);
      }finally{
        button.textContent = original;
        button.disabled = false;
      }
    });
    cloudToggle.addEventListener('click', () => {
      cloudInstall.classList.toggle('active');
      if(cloudInstall.classList.contains('active')){
        cloudToggle.textContent = 'Ocultar instalacion cloud';
        document.getElementById('digitalOceanToken').focus();
      }else{
        cloudToggle.textContent = 'Instalar en DigitalOcean';
      }
    });
    document.addEventListener('click', (event) => {
      const openButton = event.target.closest('button[data-cloud-open-url]');
      if(openButton){
        openCloudDashboard(openButton);
        return;
      }
      const deleteButton = event.target.closest('button[data-cloud-action="delete-droplet"]');
      if(deleteButton){
        deleteCloudDroplet(deleteButton);
        return;
      }
      const button = event.target.closest('button[data-cloud-action="reset-install"]');
      if(button) resetCloudInstall(button);
    });
    document.getElementById('digitalOceanToken').addEventListener('input', scheduleCloudTokenRecovery);
    cloudForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = document.getElementById('cloudButton');
      button.disabled = true;
      const original = button.textContent;
      button.textContent = 'Creando servidor...';
      const expectedVersion = ++cloudStateVersion;
      startCloudCreatePreview();
      installState.scrollIntoView({behavior:'smooth', block:'start'});
      setStatus('Creando tu servidor en DigitalOcean...');
      try{
        const digitalOceanToken = document.getElementById('digitalOceanToken').value.trim();
        cloudRecoveryToken = digitalOceanToken;
        const data = await postJson('/api/portal/cloud/digitalocean', {
          portal_token: portalToken,
          digitalocean_token: digitalOceanToken,
          ssh_public_key: document.getElementById('sshPublicKey').value,
          region: document.getElementById('cloudRegion').value,
          size: document.getElementById('cloudSize').value
        });
        if(expectedVersion !== cloudStateVersion) return;
        stopCloudCreatePreview();
        if(!data.valid) throw new Error(data.detail || 'No pude crear el servidor.');
        renderCloudResult(data);
        renderInstallState({
          cloud_installation: data,
          install_state: {
            cloud: { installed: Boolean(data.provider || data.droplet_id || data.cloud_open_url || data.dashboard_url), status: data.install_status || data.status || 'installing', dashboard_available: false, progress: data.progress || 18 },
            local: {}
          }
        });
        startCloudProgressPolling();
        setStatus('Servidor creado. Espera unos minutos para abrirlo.');
      }catch(error){
        if(expectedVersion !== cloudStateVersion) return;
        stopCloudCreatePreview();
        cloudResult.textContent = error.message || 'No pude crear el servidor.';
        cloudResult.classList.add('active');
        setStatus(error.message || 'No pude crear el servidor.', true);
      }finally{
        button.textContent = original;
        button.disabled = false;
      }
    });
    logoutButton.addEventListener('click', async () => {
      stopCloudCreatePreview();
      stopCloudProgressPolling(true);
      cloudDisplayedProgress = 0;
      await fetch('/api/portal/session', { method:'DELETE', credentials:'same-origin' }).catch(() => {});
      portalToken = '';
      cloudRecoveryToken = '';
      downloads.classList.remove('active');
      cloudInstall.classList.remove('active');
      cloudResult.classList.remove('active');
      setStatus('Sesion cerrada en este navegador.');
      form.scrollIntoView({behavior:'smooth', block:'center'});
    });
    restorePortalSession();
  </script>
</body>
</html>`);
}
