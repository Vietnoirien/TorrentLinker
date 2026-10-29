// Runs in the c411 tab's ISOLATED world. Return allowlisted values only.
// Never accepts a URL, reads cookies/storage, follows redirects or writes to c411.
export async function collectProfile(options) {
  if (location.origin !== "https://c411.org")
    throw new Error("Open c411.org. Sync resumes automatically.");
  const get = async (path) => {
    const r = await fetch(path, {
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
      signal: AbortSignal.timeout(12000),
    });
    if (r.status === 401 || r.status === 403)
      throw new Error("Sign in on c411. Sync resumes automatically.");
    if (r.status === 429)
      throw new Error("c411 rate limit reached. Wait before retrying.");
    if (
      !r.ok ||
      !(r.headers.get("content-type") || "").includes("application/json")
    )
      throw new Error(
        "c411 did not return the expected JSON. Check the c411 tab.",
      );
    const body = await r.json();
    if (!body || body.error || body.success === false)
      throw new Error("c411 refused the read. Check your session.");
    return body;
  };
  const num = (x) => (typeof x === "number" && Number.isFinite(x) ? x : null);
  const str = (x) => (typeof x === "string" ? x.slice(0, 160) : null);
  const first = await get("/api/user/profile");
  const id = (x) =>
    (typeof x.id === "string" || Number.isSafeInteger(x.id)) &&
    String(x.id).length > 0
      ? String(x.id)
      : null;
  if (!id(first) || !str(first.username))
    throw new Error("Missing account identity. Nothing can be synced.");
  const snapshot = {
    schema: 1,
    source: "https://c411.org",
    capturedAt: new Date().toISOString(),
    account: { id: id(first), username: str(first.username) },
    profile: {
      balance: num(first.zen?.balance),
      classSlug: str(first.class?.effectiveSlug || first.class?.slug),
      level: num(first.level?.level),
    },
    details: null,
    activeSeeds: null,
  };
  if (options.details) {
    const { stats } = await get("/api/profile/detailed-stats");
    if (!stats || typeof stats !== "object")
      throw new Error("Detailed statistics format changed. Nothing sent.");
    snapshot.details = {};
    for (const key of [
      "actualDownloaded",
      "actualUploaded",
      "creditedDownloaded",
      "creditedUploaded",
      "totalSeedingTimeSec",
      "validatedUploadsCount",
    ])
      snapshot.details[key] = num(stats[key]);
  }
  if (options.seeds) {
    const body = await get("/api/profile/active-seeds?page=1&perPage=2");
    const count = body.meta?.total;
    if (!Number.isSafeInteger(count) || count < 0)
      throw new Error("Active seed count format changed. Nothing sent.");
    snapshot.activeSeeds = { total: count }; // Never return titles, hashes or file lists.
  }
  const last = await get("/api/user/profile");
  if (id(last) !== snapshot.account.id)
    throw new Error("Account changed during the read. Waiting for the connected account.");
  snapshot.capturedAt = new Date().toISOString();
  return snapshot;
}
