import { collectProfile } from "./collect.js";

const PERIOD = 120000;
const ready = chrome.storage.local.setAccessLevel({
  accessLevel: "TRUSTED_CONTEXTS",
});
let queue = Promise.resolve();
function serial(task) {
  const result = queue.then(() => ready).then(task);
  queue = result.catch(() => {});
  return result;
}
async function request(connection, path, body) {
  const response = await fetch(connection.target + "/api/companion/" + path, {
    method: "POST",
    credentials: "omit",
    redirect: "error",
    signal: AbortSignal.timeout(10000),
    headers: {
      "Content-Type": "application/json",
      ...(connection.token
        ? { Authorization: "Bearer " + connection.token }
        : {}),
    },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.detail || "TorrentLinker is unavailable.");
    error.status = response.status;
    throw error;
  }
  return data;
}
async function note(message) {
  await chrome.storage.local.set({ message });
}
async function validateConnection(message, sender) {
  const target = new URL(message.target);
  const source = new URL(sender.url);
  const base = target.href.replace(/\/$/, "");
  const receiver = await (
    await fetch(chrome.runtime.getURL("receiver.json"))
  ).json();
  if (target.protocol === "https:" && base !== receiver.webTarget)
    throw new Error(
      "Install the companion downloaded from this TorrentLinker server.",
    );
  if (
    message.action !== "connect" ||
    target.origin !== source.origin ||
    sender.frameId !== 0 ||
    source.pathname !== new URL(base + "/companion/connect").pathname ||
    !["https:", "http:"].includes(target.protocol) ||
    (target.protocol === "http:" &&
      !["127.0.0.1", "localhost"].includes(target.hostname)) ||
    target.username ||
    target.password ||
    target.search ||
    target.hash ||
    !/^[A-Za-z0-9_-]{40,100}$/.test(message.code) ||
    typeof message.accountId !== "string" ||
    !message.accountId ||
    message.accountId.length > 160
  )
    throw new Error("Start the connection from TorrentLinker’s Profile tab.");
  return { target: base, code: message.code, accountId: message.accountId };
}
async function connect(pending) {
  // Validate the app's one-time capability before reading anything from c411.
  const paired = await request(pending, "pair", {
    code: pending.code,
    accountId: pending.accountId,
  });
  const { connection: old } = await chrome.storage.local.get("connection");
  const connection = {
    target: pending.target,
    token: paired.token,
    accountId: pending.accountId,
    paused: false,
  };
  await chrome.storage.local.set({
    connection,
    lastAttempt: 0,
    lastSync: null,
  });
  if (old && old.target !== connection.target) {
    try {
      await request(old, "disconnect", {});
    } catch {
      /* Old receiver may be offline. */
    }
  }
  await ensureAlarm();
  if (!(await chrome.tabs.query({ url: "https://c411.org/*" })).length)
    await chrome.tabs.create({ url: "https://c411.org/", active: true });
  await sync();
}
async function sync() {
  const { connection, lastAttempt = 0 } = await chrome.storage.local.get([
    "connection",
    "lastAttempt",
  ]);
  if (!connection || connection.paused || Date.now() - lastAttempt < PERIOD)
    return;
  const tabs = await chrome.tabs.query({
    url: "https://c411.org/*",
    status: "complete",
  });
  if (!tabs.length) {
    await note(
      "Waiting for a signed-in c411 tab. Updates resume automatically when it opens.",
    );
    return;
  }
  await chrome.storage.local.set({ lastAttempt: Date.now() });
  try {
    const result = await chrome.scripting.executeScript({
      target: { tabId: tabs[0].id },
      world: "ISOLATED",
      func: collectProfile,
      args: [{ details: true, seeds: true }],
    });
    const snapshot = result[0]?.result;
    if (!snapshot?.account?.id)
      throw new Error("Sign in to c411. Sync will resume automatically.");
    if (snapshot.account.id !== connection.accountId)
      throw new Error(
        "Different c411 account. Sign in with the account connected in TorrentLinker.",
      );
    await request(connection, "snapshot", snapshot);
    await chrome.storage.local.set({ lastSync: Date.now() });
    await note("Connected. Profile updates automatically every two minutes.");
  } catch (error) {
    if (error.status === 403) {
      await chrome.storage.local.remove("connection");
      await note(
        "Connection revoked. Click Connect in TorrentLinker to reconnect.",
      );
    } else
      await note(error.message || "Sync unavailable. Retrying automatically.");
  }
}
async function ensureAlarm() {
  if (!(await chrome.alarms.get("profile-sync")))
    await chrome.alarms.create("profile-sync", { periodInMinutes: 2 });
}
async function state() {
  const { connection, message, lastSync } = await chrome.storage.local.get([
    "connection",
    "message",
    "lastSync",
  ]);
  return {
    target: connection?.target,
    accountId: connection?.accountId,
    paused: connection?.paused,
    connected: !!connection,
    message,
    lastSync,
  };
}
chrome.runtime.onMessageExternal.addListener((message, sender, reply) => {
  serial(async () => {
    await connect(await validateConnection(message, sender));
    return { connected: true };
  }).then(reply, (error) => reply({ error: error.message }));
  return true;
});
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.url !== chrome.runtime.getURL("companion.html")) return false;
  serial(async () => {
    if (message.action === "disconnect") {
      const { connection } = await chrome.storage.local.get("connection");
      await chrome.storage.local.clear();
      if (connection) {
        try {
          await request(connection, "disconnect", {});
        } catch {
          await note(
            "Forgotten in this browser. Use Disconnect & clear in TorrentLinker if it was offline.",
          );
        }
      }
    } else if (message.action === "pause") {
      const { connection } = await chrome.storage.local.get("connection");
      if (connection) {
        connection.paused = !connection.paused;
        await chrome.storage.local.set({ connection });
        await note(
          connection.paused
            ? "Automatic sync paused."
            : "Automatic sync resumed.",
        );
        if (!connection.paused) await sync();
      }
    }
    return state();
  }).then(reply, (error) => reply({ error: error.message }));
  return true;
});
chrome.action.onClicked.addListener(() =>
  chrome.tabs.create({ url: chrome.runtime.getURL("companion.html") }),
);
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "profile-sync") serial(sync);
});
chrome.tabs.onUpdated.addListener((_id, change, tab) => {
  if (change.status === "complete" && tab.url?.startsWith("https://c411.org/"))
    serial(sync);
});
// Recreate alarms after browser restart or extension upgrade. Connection state
// survives service-worker suspension. No cookies or login tokens are exported.
serial(async () => {
  await ensureAlarm();
  await sync();
});
