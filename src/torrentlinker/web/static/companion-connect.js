// Both desktop and WebUI use this same one-click handoff. The one-time code is
// removed from history immediately and never appears in an HTTP URL or log.
const extensionId = "jfnellfifmdbccmgmcfllkgglikdcaia";
const status = document.getElementById("status");
const install = document.getElementById("install");
let payload;
try {
  payload = JSON.parse(decodeURIComponent(location.hash.slice(1)));
} catch {}
history.replaceState(null, "", location.pathname);
let attempts = 0;
// The first companion able to pair tr4ker; an older one rejects it with a misleading error.
const TR4KER_COMPANION = [0, 7, 0];
const newer = (version, wanted) => {
  const parts = String(version).split(".").map(Number);
  for (let i = 0; i < wanted.length; i++)
    if ((parts[i] || 0) !== wanted[i]) return (parts[i] || 0) > wanted[i];
  return true;
};
async function companionVersion() {
  try {
    const reply = await chrome.runtime.sendMessage(extensionId, { action: "version" });
    return reply?.version || "0";
  } catch {
    return null; // not installed, or hidden from this page
  }
}
async function connect() {
  // Browsers hide the companion from remote HTTP pages, so waiting cannot succeed.
  if (
    location.protocol === "http:" &&
    !["127.0.0.1", "localhost"].includes(location.hostname)
  ) {
    status.textContent =
      "The companion connects to a remote TorrentLinker only over HTTPS. Open TorrentLinker through an HTTPS address (for example with tailscale serve or a reverse proxy), download the companion again from Settings at that address, install it, then click Connect companion.";
    return;
  }
  // tr4ker names no account: its signed-in tab does when the extension pairs.
  if (!payload?.code || !(payload?.accountId || payload?.tracker === "tr4ker")) {
    status.textContent =
      "Return to TorrentLinker → Settings → Connections → Companion and click Pair.";
    return;
  }
  if (++attempts > 120) {
    status.textContent =
      "Connection link expired. Click Connect companion in TorrentLinker again.";
    return;
  }
  const version = await companionVersion();
  if (version !== null && payload.tracker === "tr4ker" && !newer(version, TR4KER_COMPANION)) {
    status.textContent =
      "The companion in this browser is too old to pair tr4ker. Download it again from TorrentLinker → Settings → Connections → Companion, replace the old folder, reload it on the browser’s extensions page, then click Pair again.";
    install.hidden = false;
    return;
  }
  try {
    const reply = await chrome.runtime.sendMessage(extensionId, {
      ...payload,
      action: "connect",
    });
    if (reply?.error) {
      status.textContent = reply.error;
      return;
    }
    status.textContent =
      "Connected. Your profile updates automatically. You can close this tab and return to TorrentLinker.";
    payload = null;
    install.hidden = true;
  } catch {
    status.textContent = "Waiting for the companion in this browser.";
    install.hidden = false;
    setTimeout(connect, 5000);
  }
}
connect();
