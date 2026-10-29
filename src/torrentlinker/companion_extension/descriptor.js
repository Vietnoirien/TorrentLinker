// Runs in the c411 tab's isolated world. Session credentials never leave it.
// Only a fixed-origin descriptor route is allowed; never opens a file or client.
export async function collectDescriptor(command) {
  const result = { id: command.id, accountId: command.accountId, status: 0 };
  if (location.origin !== "https://c411.org" ||
      !/^[a-f0-9]{40}$/.test(command.infohash)) return result;
  const signal = AbortSignal.timeout(20000);
  const get = (path) => fetch(path, {
    credentials: "same-origin", redirect: "error", cache: "no-store", signal,
  });
  const refused = (response) => {
    result.status = response.status;
    if (response.status === 429) {
      const value = response.headers.get("retry-after") || "";
      const seconds = /^\d+(?:,\s*\d+)*$/.test(value)
        ? Math.max(...value.split(",").map(Number))
        : Math.ceil((Date.parse(value) - Date.now()) / 1000);
      result.retryAfter = Number.isFinite(seconds) ? Math.max(60, seconds) : 60;
    }
    return result;
  };
  const account = async () => {
    const response = await get("/api/user/profile");
    if (!response.ok) { refused(response); return false; }
    const profile = await response.json();
    if (String(profile.id) !== command.accountId) {
      result.status = 403;
      return false;
    }
    return true;
  };
  try {
    if (!(await account())) return result;
    const root = `/api/torrents/${command.infohash}`;
    const integrity = await get(root + "/check-integrity");
    // Like the website: a failed check only blocks when c411 explains why.
    if ([401, 403, 429].includes(integrity.status)) return refused(integrity);
    if (integrity.ok) {
      const check = await integrity.json().catch(() => ({}));
      if (check.ok === false && check.message) return result;
    }
    const response = await get(root + "/download");
    if (!response.ok) return refused(response);
    const kind = (response.headers.get("content-type") || "").split(";")[0].trim();
    if (!["application/x-bittorrent", "application/octet-stream"].includes(kind)) return result;
    const maximum = 8 * 1024 * 1024;
    if (Number(response.headers.get("content-length")) > maximum) {
      await response.body?.cancel();
      return result;
    }
    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > maximum) { await reader.cancel(); return result; }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    if (!size || !(await account())) return result;
    let binary = "";
    for (const chunk of chunks)
      for (let i = 0; i < chunk.length; i += 8192)
        binary += String.fromCharCode(...chunk.subarray(i, i + 8192));
    return { ...result, status: 200, data: btoa(binary) };
  } catch {
    // Never send exception messages, response bodies, login tokens or URLs.
    return { ...result, status: result.status === 429 ? 429 : 0 };
  }
}
