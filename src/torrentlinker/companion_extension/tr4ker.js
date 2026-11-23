// Runs in the tr4ker tab's ISOLATED world. Return filtered values only.
// Never accepts a URL, reads cookies/storage, follows redirects or writes to tr4ker. Every read
// is a GET of a fixed route below, with the tab's own session (same origin, cookies never
// leave it). executeScript serializes only this function, so it uses no outer names.
export async function collectTr4ker(options) {
  const ORIGIN = "https://tr4ker.net";
  if (location.origin !== ORIGIN)
    throw new Error("Open tr4ker.net. Sync resumes automatically.");
  // The whole allowlist. Never /api/me/api-key: it regenerates the key. Nothing writes.
  const ALLOWED = [
    /^\/api\/me$/,
    /^\/api\/me\/stats$/,
    /^\/api\/me\/downloads(?:\?[A-Za-z0-9_=&.-]{0,100})?$/,
    /^\/api\/me\/sw-rewards(?:\?[A-Za-z0-9_=&.-]{0,100})?$/,
    /^\/api\/shop$/,
    /^\/api\/shop\/history(?:\?[A-Za-z0-9_=&.-]{0,100})?$/,
    /^\/api\/torrents\/[A-Za-z0-9_-]{1,200}$/,
    /^\/api\/torrents\?[A-Za-z0-9_=&%.,+~-]{1,1500}$/,
    /^\/api\/public\/categories$/,
    /^\/api\/public\/features$/,
  ];
  const fail = (message, fatal = false) =>
    Object.assign(new Error(message), { fatal });
  const get = async (path) => {
    if (!ALLOWED.some((rule) => rule.test(path)) || path.includes("api-key"))
      throw fail("Route not allowed.", true);
    const r = await fetch(path, {
      method: "GET",
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
      signal: AbortSignal.timeout(12000),
    });
    if (r.status === 401 || r.status === 403)
      throw fail("Sign in on tr4ker. Sync resumes automatically.", true);
    if (r.status === 429)
      throw fail("tr4ker rate limit reached. Wait before retrying.", true);
    if (
      !r.ok ||
      !(r.headers.get("content-type") || "").includes("application/json")
    )
      throw fail("tr4ker did not return the expected JSON. Check the tr4ker tab.");
    const body = await r.json();
    if (!body || typeof body !== "object" || body.error)
      throw fail("tr4ker refused the read. Check your session.", true);
    return body;
  };
  const num = (x) => (typeof x === "number" && Number.isFinite(x) ? x : null);
  const str = (x, n = 160) => (typeof x === "string" && x ? x.slice(0, n) : null);
  const bool = (x) => (typeof x === "boolean" ? x : null);
  const id = (x) =>
    (typeof x?.id === "string" || Number.isSafeInteger(x?.id)) &&
    String(x.id).length > 0
      ? String(x.id)
      : null;
  // /api/me carries the API key, the passkey and the TOTP state. Only these fields leave
  // the tab; anything else, including a field added later, is dropped.
  const badges = (list) =>
    Array.isArray(list)
      ? list.slice(0, 20).map((b) => ({
          name: str(b?.name, 80),
          power_type: str(b?.power_type, 40),
          power_value: num(b?.power_value),
        }))
      : undefined;
  const filterMe = (me) => {
    const out = {
      id: id(me),
      username: str(me.username),
      role: str(me.role, 60),
      power: num(me.power),
      uploaded: num(me.uploaded),
      downloaded: num(me.downloaded),
      bonus_upload: num(me.bonus_upload),
      bonus_download: num(me.bonus_download),
      money: num(me.money),
      joined_at: str(me.joined_at, 40),
      last_seen_at: str(me.last_seen_at, 40),
      personal_freeleech_until: str(me.personal_freeleech_until, 40),
      freeleech_global: bool(me.freeleech_global),
      token_currency_name: str(me.token_currency_name, 40),
    };
    const owned = badges(me.badges);
    if (owned) out.badges = owned;
    return out;
  };
  const filterStats = (stats) => {
    const s = stats.summary && typeof stats.summary === "object" ? stats.summary : {};
    const summary = {};
    for (const key of ["uploaded", "downloaded", "raw_uploaded", "raw_downloaded",
      "bonus_upload", "bonus_download", "money"]) summary[key] = num(s[key]);
    summary.ratio_warning = bool(s.ratio_warning);
    const out = { summary, freeleech_count: num(stats.freeleech_count) };
    const owned = badges(stats.badges);
    if (owned) out.badges = owned;
    return out;
  };
  const filterShop = (body) => {
    const items = Array.isArray(body) ? body : body.items;
    if (!Array.isArray(items)) throw fail("Shop format changed. Nothing sent.");
    return items.slice(0, 50).map((item) => ({
      id: id(item),
      name: str(item?.name, 80),
      price: num(item?.price),
      bonus_bytes: num(item?.bonus_bytes),
    }));
  };
  // A payout keeps its amount and the inputs tr4ker paid it for. Field names beyond the
  // documented ones are tolerated aliases; anything else is dropped, including free text.
  const count = (x) => {
    const n = typeof x === "string" && /^\d+(?:\.\d+)?$/.test(x) ? Number(x) : x;
    return num(n);
  };
  const label = (x) => str(typeof x === "object" && x ? x.slug || x.name : x, 200);
  const when = (x) => {
    const t = typeof x === "number" ? (x < 1e12 ? x * 1000 : x) : Date.parse(x);
    return Number.isFinite(t) ? new Date(t).toISOString() : null;
  };
  const payout = (e) => ({
    id: id(e),
    amount: count(e?.amount),
    seeders: count(e?.seeders),
    size_bytes: count(e?.size_bytes),
    seedtime_seconds: count(e?.seedtime_seconds),
    at: when(e?.created_at ?? e?.paid_at ?? e?.at ?? e?.date ?? e?.timestamp),
    slug: str(e?.torrent?.slug ?? e?.torrent_slug ?? e?.slug, 200),
    category: label(e?.category ?? e?.torrent?.category),
    multiplier: count(e?.multiplier ?? e?.badge_multiplier ?? e?.credit_multiplier),
  });

  const first = await get("/api/me");
  const identity = { id: id(first), username: str(first.username) };
  if (!identity.id || !identity.username)
    throw fail("Missing account identity. Nothing can be synced.", true);
  if (options.identityOnly) return { account: identity };
  const me = filterMe(first);
  let stats = null;
  try {
    stats = filterStats(await get("/api/me/stats"));
  } catch (error) {
    if (error.fatal) throw error; // an empty or odd stats body leaves the figures null
  }
  const snapshot = {
    schema: 1,
    source: ORIGIN,
    tracker: "tr4ker",
    capturedAt: new Date().toISOString(),
    account: identity,
    me,
    ...(stats ? { stats } : {}),
  };
  if (options.shop) {
    try {
      snapshot.shop = filterShop(await get("/api/shop"));
    } catch (error) {
      if (error.fatal) throw error;
    }
  }
  let payoutPages = null;
  if (options.payoutPages > 0) {
    // Optional, like c411's ledger: a failed read leaves the log as it was.
    try {
      payoutPages = [];
      const limit = 50;
      for (let page = 0; page < options.payoutPages; page++) {
        const body = await get(`/api/me/sw-rewards?limit=${limit}&offset=${page * limit}`);
        if (!Array.isArray(body.entries)) throw fail("Payout format changed. Nothing sent.");
        payoutPages.push(body.entries.map(payout));
        if (
          body.entries.length < limit ||
          (Number.isSafeInteger(body.total) && (page + 1) * limit >= body.total)
        )
          break;
        await new Promise((done) => setTimeout(done, 400));
      }
    } catch (error) {
      if (error.fatal) throw error;
      payoutPages = null;
    }
  }
  const last = await get("/api/me");
  if (id(last) !== identity.id)
    throw fail("Account changed during the read. Waiting for the connected account.");
  // Last line of defence: nothing secret-looking may leave the tab.
  const secretKey = (value) =>
    Array.isArray(value)
      ? value.some(secretKey)
      : value && typeof value === "object"
        ? Object.entries(value).some(
            ([key, inner]) =>
              /api_?key|passkey|totp|recovery|secret|password/i.test(key) || secretKey(inner),
          )
        : false;
  if (secretKey([snapshot, payoutPages]))
    throw fail("Refusing to send an account field that looks secret.");
  snapshot.capturedAt = new Date().toISOString();
  return { snapshot, payoutPages };
}

// Runs in the tr4ker tab's ISOLATED world for the app's on-demand reads (native Search and
// torrent detail). Only the three fixed read-only routes below; never sort=seeders|title|size|
// leechers or search_in (tr4ker answers 500), which the app never asks for and this refuses
// again. Results go back as the raw JSON text with the status; nothing else leaves the tab.
export async function readTr4kerPages(commands) {
  const allowed = [
    /^\/api\/torrents\?[A-Za-z0-9_=&%.,+~-]{1,1500}$/,
    /^\/api\/torrents\/[A-Za-z0-9_-]{1,200}$/,
    /^\/api\/public\/categories$/,
  ];
  const broken = /(?:^|[?&])(?:search_in=|sort=(?:seeders|title|size|leechers)(?:&|$))/;
  const fail = (command, status, extra = {}) => ({
    id: command.id, accountId: command.accountId, status, ...extra,
  });
  const results = [];
  try {
    if (
      location.origin !== "https://tr4ker.net" ||
      commands.some((c) => !allowed.some((r) => r.test(c.path)) || broken.test(c.path))
    )
      return commands.map((c) => fail(c, 0, { reason: "origin" }));
    for (const command of commands) {
      const response = await fetch(command.path, {
        method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store",
        signal: AbortSignal.timeout(30000),
      });
      if (!response.ok) {
        const value = response.headers.get("retry-after") || "";
        const seconds = /^\d+$/.test(value) ? Number(value) : 60;
        results.push(fail(command, response.status, response.status === 429
          ? { retryAfter: Math.max(60, seconds) } : {}));
        if (response.status !== 404) break;
        continue;
      }
      const text = await response.text();
      results.push(text.length > 4 * 1024 * 1024
        ? fail(command, 0, { reason: "size" })
        : { id: command.id, accountId: command.accountId, status: 200, data: text });
    }
  } catch (error) {
    // Never send exception messages, response bodies or URLs.
    results.push(fail(commands[results.length], 0, { reason: error?.name === "TimeoutError" ? "timeout" : "network" }));
  }
  while (results.length < commands.length) results.push(fail(commands[results.length], 0, { reason: "stopped" }));
  return results;
}
