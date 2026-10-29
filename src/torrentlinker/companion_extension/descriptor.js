// Runs in the c411 tab's isolated world. Session credentials never leave it.
// Only a fixed-origin descriptor route is allowed; never opens a file or client.
// executeScript serializes only this function, so it must not use outer names.
export async function collectDescriptors(commands, concurrency = 1) {
  const MAXIMUM = 8 * 1024 * 1024;
  const account = commands[0]?.accountId;
  const get = (path) => fetch(path, {
    credentials: "same-origin", redirect: "error", cache: "no-store",
    signal: AbortSignal.timeout(30000),
  });
  const fail = (command, status, reason, extra = {}) => ({
    id: command.id, accountId: command.accountId, status, reason, ...extra,
  });
  const refusal = (command, response) => {
    const extra = {};
    if (response.status === 429) {
      const value = response.headers.get("retry-after") || "";
      const seconds = /^\d+(?:,\s*\d+)*$/.test(value)
        ? Math.max(...value.split(",").map(Number))
        : Math.ceil((Date.parse(value) - Date.now()) / 1000);
      extra.retryAfter = Number.isFinite(seconds) ? Math.max(60, seconds) : 60;
    }
    return fail(command, response.status, undefined, extra);
  };
  // One identity check at each end of the batch, not around every file.
  const same = async () => {
    const response = await get("/api/user/profile");
    return response.ok ? String((await response.json()).id) === account : response;
  };
  const rejected = (response) =>
    commands.map((c) => ({ ...refusal(c, response), reason: "profile" }));
  const results = [];
  const stopAll = (status, reason) => {
    for (const command of commands.slice(results.length))
      results.push(fail(command, status, reason));
    return results;
  };
  try {
    if (location.origin !== "https://c411.org" ||
        commands.some((c) => !/^[a-f0-9]{40}$/.test(c.infohash) || c.accountId !== account))
      return stopAll(0, "origin");
    const before = await same();
    if (before !== true)
      return before === false ? stopAll(403, "account") : rejected(before);
    // Worker pool: `concurrency` requests at once, results kept in request order.
    const slots = new Array(commands.length);
    let next = 0, stalled = 0, halted = false;
    const one = async (command) => {
      const started = Date.now();
      const took = () => ({ ms: Date.now() - started });
      let response;
      try {
        response = await get(`/api/torrents/${command.infohash}/download`);
      } catch (error) {
        if (error?.name !== "TimeoutError") throw error;
        // One slow torrent is skipped; repeated stalls look like throttling.
        if (++stalled >= 3) halted = true;
        return fail(command, 0, "timeout", took());
      }
      if (!response.ok) {
        if (response.status !== 404) halted = true;
        return { ...refusal(command, response), ...took() };
      }
      const kind = (response.headers.get("content-type") || "").split(";")[0].trim();
      if (!["application/x-bittorrent", "application/octet-stream"].includes(kind) ||
          Number(response.headers.get("content-length")) > MAXIMUM) {
        await response.body?.cancel();
        halted = true;
        return fail(command, 0, "type");
      }
      const reader = response.body.getReader();
      const chunks = [];
      let size = 0;
      try {
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          size += value.length;
          if (size > MAXIMUM) { await reader.cancel(); break; }
          chunks.push(value);
        }
      } catch (error) {
        if (error?.name !== "TimeoutError") throw error;
        if (++stalled >= 3) halted = true;
        return fail(command, 0, "timeout", took());
      } finally { reader.releaseLock(); }
      if (!size || size > MAXIMUM) {
        halted = true;
        return fail(command, 0, size ? "size" : "empty");
      }
      stalled = 0;
      let binary = "";
      for (const chunk of chunks)
        for (let i = 0; i < chunk.length; i += 8192)
          binary += String.fromCharCode(...chunk.subarray(i, i + 8192));
      return {
        id: command.id, accountId: command.accountId, status: 200, data: btoa(binary), ...took(),
      };
    };
    const worker = async () => {
      while (!halted && next < commands.length) {
        const index = next++;
        try { slots[index] = await one(commands[index]); }
        catch (error) {
          halted = true;
          slots[index] = fail(commands[index], 0, error?.name === "TimeoutError" ? "timeout" : "network");
        }
      }
    };
    const width = Math.max(1, Math.min(Number(concurrency) || 1, 16));
    await Promise.all(Array.from({ length: width }, worker));
    for (let i = 0; i < commands.length; i++)
      results.push(slots[i] || fail(commands[i], 0, "stopped"));
    const after = await same();
    if (after !== true)
      return after === false
        ? commands.map((c) => fail(c, 403, "account")) : rejected(after);
    return results;
  } catch (error) {
    // Never send exception messages, response bodies, login tokens or URLs.
    const reason = error?.name === "TimeoutError" ? "timeout" : "network";
    results.push(fail(commands[results.length], 0, reason));
    return stopAll(0, "stopped");
  }
}
