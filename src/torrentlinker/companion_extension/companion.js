import { collectProfile } from "./collect.js";
const $ = (id) => document.getElementById(id);
let preview = null,
  pairing = null,
  busy = false,
  lastRead = 0;
function status(message) {
  $("status").textContent = message;
}
function render() {
  $("preview").textContent = preview
    ? JSON.stringify(preview, null, 2)
    : "No current preview.";
  $("pair").disabled = busy || !preview;
  $("pair").textContent = pairing
    ? "Pair again with a new code"
    : "Pair with this account";
  $("send").disabled =
    busy || !preview || !pairing || preview.account.id !== pairing.accountId;
  $("read").disabled = busy;
  $("target").disabled = !!pairing || busy;
  $("details").disabled = $("seeds").disabled = busy;
  $("destination").textContent = pairing
    ? `Paired to ${pairing.target} · account ${pairing.accountId}`
    : "Not paired";
}
async function request(target, path, body, token) {
  const r = await fetch(target + path, {
    method: "POST",
    redirect: "error",
    credentials: "omit",
    signal: AbortSignal.timeout(10000),
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) {
    if (r.status === 403 && token) pairing = null;
    const error = new Error(
      data.detail || data.error || `Receiver returned ${r.status}`,
    );
    error.status = r.status;
    throw error;
  }
  return data;
}
async function run(fn) {
  if (busy) return;
  busy = true;
  render();
  try {
    await fn();
  } catch (e) {
    status(e.message);
  } finally {
    busy = false;
    render();
  }
}
$("read").onclick = () =>
  run(async () => {
    preview = null;
    if (Date.now() - lastRead < 30000)
      throw new Error("Wait 30 seconds between reads.");
    lastRead = Date.now();
    status("Reading selected fields from c411…");
    const tabId = Number(new URLSearchParams(location.search).get("source"));
    if (!Number.isSafeInteger(tabId) || tabId <= 0)
      throw new Error("Open c411 and click the extension icon.");
    const result = await chrome.scripting.executeScript({
      target: { tabId },
      world: "ISOLATED",
      func: collectProfile,
      args: [{ details: $("details").checked, seeds: $("seeds").checked }],
    });
    const value = result[0]?.result;
    if (!value?.account?.id)
      throw new Error("Read did not return a profile. Check the c411 tab.");
    preview = value;
    status(
      pairing && preview.account.id !== pairing.accountId
        ? "Different account. Disconnect and pair again before sending."
        : "Preview ready. Review it before sending.",
    );
  });
for (const id of ["details", "seeds"])
  $(id).onchange = () => {
    preview = null;
    status("Selection changed. Read a new preview.");
    render();
  };
$("pair").onclick = async () => {
  if (busy || !preview) return;
  let target;
  try {
    const u = new URL($("target").value);
    if (
      !(
        (u.protocol === "http:" &&
          ["127.0.0.1", "localhost"].includes(u.hostname)) ||
        u.protocol === "https:"
      ) ||
      u.username ||
      u.password ||
      u.search ||
      u.hash
    )
      throw new Error(
        "Use the receiver address shown in TorrentLinker: local HTTP or remote HTTPS.",
      );
    target = u.origin + u.pathname.replace(/\/$/, "");
  } catch (e) {
    status(e.message);
    return;
  }
  // Permission request must start directly in the user's click handler.
  const receiver = new URL(target);
  const granted = await chrome.permissions.request({
    origins: [receiver.protocol + "//" + receiver.hostname + "/*"],
  });
  if (!granted) {
    status("Receiver access was not granted. Nothing sent.");
    return;
  }
  await run(async () => {
    const data = await request(target, "/api/companion/pair", {
      code: $("code").value.trim(),
      accountId: preview.account.id,
    });
    pairing = { target, token: data.token, accountId: preview.account.id };
    $("code").value = "";
    status("Paired. Review the preview, then send when ready.");
  });
};
$("send").onclick = () =>
  run(async () => {
    if (!pairing || !preview) return;
    if (preview.account.id !== pairing.accountId)
      throw new Error("Account changed. Pair again.");
    if (Date.now() - Date.parse(preview.capturedAt) > 300000) {
      preview = null;
      throw new Error("Preview is older than five minutes. Read again.");
    }
    await request(
      pairing.target,
      "/api/companion/snapshot",
      preview,
      pairing.token,
    );
    status(
      `Snapshot sent to ${pairing.target}. Open Zen → Profile in TorrentLinker to view it.`,
    );
  });
$("forget").onclick = () =>
  run(async () => {
    const old = pairing;
    pairing = null;
    preview = null;
    $("code").value = "";
    if (old) {
      try {
        await request(old.target, "/api/companion/disconnect", {}, old.token);
      } catch (error) {
        status(
          error.status === 403
            ? "Local connection forgotten. Use Disconnect & clear in TorrentLinker to clear its saved snapshot. You can pair again now."
            : "Local connection forgotten. Receiver unreachable; use Disconnect & clear in TorrentLinker. Its token expires within one hour.",
        );
        return;
      }
    }
    status("Disconnected. Preview and receiver data cleared.");
  });
render();
