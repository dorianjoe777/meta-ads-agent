const origin = (() => {
  try {
    const value = new URL(process.env.ADMIRA_OPERATOR_ORIGIN || '');
    if (value.protocol !== 'https:' || value.username || value.password || value.pathname !== '/' || value.search || value.hash) return null;
    return value;
  } catch (_) {
    return null;
  }
})();
const proxyKey = process.env.ADMIRA_OPERATOR_PROXY_KEY;

export default async function handler(req, res) {
  if (!origin || !proxyKey) return res.status(503).json({error:'proxy_not_configured'});
  const incoming = new URL(req.url || '/', 'https://dashboard.uboost.lat');
  if (!incoming.pathname.startsWith('/api/operator')) return res.status(404).json({error:'not_found'});
  // The operator API has no query-based commands. Dropping the query also
  // prevents deployment or tracking parameters from reaching its strict
  // request-path validator.
  const target = new URL(incoming.pathname, origin);
  // Forward only the dashboard protocol headers. Vercel adds several
  // deployment and forwarding headers to the incoming request; passing them
  // through would make the upstream's strict host/origin checks describe the
  // Vercel edge instead of this authenticated origin.
  const headers = new Headers();
  for (const name of ['accept', 'accept-language', 'content-type', 'cookie', 'user-agent', 'x-csrf-token']) {
    const value = req.headers?.[name];
    if (value) headers.set(name, value);
  }
  headers.set('x-admira-operator-proxy-key', proxyKey);
  headers.set('host', origin.host);
  const hasBody = !['GET','HEAD'].includes(req.method);
  const response = await fetch(target, {
    method:req.method,
    headers,
    body:hasBody ? req : undefined,
    ...(hasBody ? {duplex:'half'} : {}),
  });
  res.status(response.status);
  for (const [key,value] of response.headers) {
    if (key.toLowerCase() === 'set-cookie') res.setHeader('set-cookie', value);
    else if (!['connection','transfer-encoding','content-encoding'].includes(key.toLowerCase())) res.setHeader(key,value);
  }
  res.send(Buffer.from(await response.arrayBuffer()));
}
