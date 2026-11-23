import { communityInTab } from "./community.js";
import { collectProfile } from "./collect.js";
import { collectDescriptors } from "./descriptor.js";
import { readPages } from "./read.js";
import { collectTr4ker } from "./tr4ker.js";
import { reloadIfNewer } from "./update.js";
import { TRACKERS, tabPattern, ownsUrl } from "./trackers.js";

const PERIOD = 120000;
const LEDGER_PERIOD = 6 * 3600000; // the Zen ledger changes about once a day
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
    body: JSON.stringify(
      connection.tracker ? { ...body, tracker: connection.tracker } : body,
    ),
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.detail || "TorrentLinker is unavailable.");
    error.status = response.status;
    throw error;
  }
  // Never reload mid-pairing: the caller has not stored the token yet; the next sync does.
  if (path !== "pair") await reloadIfNewer(data.companion_version);
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
  // tr4ker has no account id before its tab is read; c411's comes from the app.
  const tracker = message.tracker === "tr4ker" ? "tr4ker" : "c411";
  if (message.tracker !== undefined && message.tracker !== tracker)
    throw new Error("Start the connection from TorrentLinker → Settings → Connections → Companion.");
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
    (tracker === "c411" &&
      (typeof message.accountId !== "string" ||
        !message.accountId ||
        message.accountId.length > 160))
  )
    throw new Error("Start the connection from TorrentLinker → Settings → Connections → Companion.");
  return {
    target: base,
    code: message.code,
    accountId: message.accountId,
    ...(tracker === "tr4ker" ? { tracker } : {}),
  };
}
async function connect(pending) {
  if (pending.tracker === "tr4ker") return connectTr4ker(pending);
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
  if (!(await chrome.tabs.query({ url: tabPattern("c411") })).length)
    await chrome.tabs.create({ url: TRACKERS.c411.origin + "/", active: true });
  await sync();
  await commands();
}
// A command keeps the worker polling for a short while, so a queued batch does
// not wait one alarm period per file. Any refusal ends the run immediately.
async function commands() {
  await communityCommands();
  let idle = 0;
  for (let worked = false; idle < 80; ) {
    const outcome = await step();
    if (outcome === "stop" || (outcome === "idle" && !worked)) return;
    worked = true;
    idle = outcome === "idle" ? idle + 1 : 0;
    if (outcome === "idle") await new Promise((done) => setTimeout(done, 250));
  }
}
async function step() {
  const { connection, downloadRetryAt = 0 } = await chrome.storage.local.get([
    "connection", "downloadRetryAt",
  ]);
  if (!connection || connection.paused || Date.now() < downloadRetryAt) return "stop";
  const tabs = await chrome.tabs.query({ url: tabPattern("c411"), status: "complete" });
  if (!tabs.length) return "stop";
  try {
    const reply = await request(connection, "commands", { limit: 25 });
    const all = reply.commands || (reply.command ? [reply.command] : []);
    if (!all.length) return "idle";
    const reads = all.filter((c) => c.path);
    const commands = all.filter((c) => !c.path);
    if (reads.length) {
      // Fixed catalogue pages (adult content the API key cannot see), one at a time.
      let pages = reads.map((c) => ({ id: c.id, accountId: connection.accountId, status: 0 }));
      if (reads.every((c) => c.accountId === connection.accountId)) {
        try {
          const frames = await chrome.scripting.executeScript({
            target: { tabId: tabs[0].id }, world: "ISOLATED", func: readPages, args: [reads],
          });
          pages = frames[0]?.result || pages;
        } catch { /* A closed or navigated tab ends this attempt without retrying. */ }
      }
      for (const page of pages) {
        try { await request(connection, "result", page); }
        catch (error) { if (error.status === 403) throw error; }
      }
      const refused = pages.find((r) => r.status === 429);
      if (refused)
        await chrome.storage.local.set({
          downloadRetryAt: Date.now() + Math.max(60, refused.retryAfter || 60) * 1000,
        });
      if (!commands.length) return pages.every((r) => r.status === 200) ? "command" : "stop";
    }
    let results = commands.map((c) => ({ id: c.id, accountId: connection.accountId, status: 0 }));
    if (commands.every((c) => c.accountId === connection.accountId)) {
      // An extension API call every few seconds stops the browser from
      // suspending this worker while a slow batch is still running.
      const beat = setInterval(() => chrome.runtime.getPlatformInfo(), 10000);
      try {
        // A frozen or discarded tab never answers; report it instead of vanishing.
        const hung = new Promise((done) => setTimeout(() => done("watchdog"), 90000));
        const frames = await Promise.race([
          chrome.scripting.executeScript({
            target: { tabId: tabs[0].id }, world: "ISOLATED",
            func: collectDescriptors, args: [commands, reply.concurrency || 1],
          }),
          hung,
        ]);
        results = frames === "watchdog"
          ? commands.map((c) => ({ id: c.id, accountId: connection.accountId, status: 0, reason: "watchdog" }))
          : frames[0]?.result || results;
      } catch { /* A closed or navigated tab ends this attempt without retrying. */
      } finally { clearInterval(beat); }
    }
    const limited = results.find((r) => r.status === 429);
    if (limited)
      await chrome.storage.local.set({
        downloadRetryAt: Date.now() + Math.max(60, limited.retryAfter || 60) * 1000,
      });
    // Each upload is independent: one rejected result must not strand the rest.
    let uploadError = "";
    for (const result of results) {
      try { await request(connection, "result", result); }
      catch (error) {
        if (error.status === 403) throw error;
        uploadError = String(error.status || error.message || "failed").slice(0, 60);
      }
    }
    if (uploadError) await note("Result upload failed: " + uploadError);
    return results.every((r) => [200, 404].includes(r.status) || r.reason === "timeout")
      ? "command" : "stop";
  } catch (error) {
    if (error.status === 403) {
      await chrome.storage.local.remove("connection");
      await note("Connection revoked. Connect again in TorrentLinker.");
    }
    await note("Download batch error: " + String(error?.message || error).slice(0, 80));
    return "stop";
  }
}
// A durable receipt is saved before executeScript. If the worker dies, report
// uncertainty on restart rather than run a second POST. Acknowledgements may retry.
async function communityCommands() {
  const {connection, communityReceipts = {}, communityRetry = {}} = await chrome.storage.local.get([
    "connection", "communityReceipts", "communityRetry",
  ]);
  if (!connection || connection.paused) return;
  const key = connection.target + "/" + connection.accountId;
  try {
    const pending = communityReceipts[key];
    if (pending) {
      await request(connection, "actions-receipt", pending);
      delete communityReceipts[key];
      await chrome.storage.local.set({communityReceipts});
    }
    if (Date.now() < (communityRetry[key] || 0)) return;
    const demand = await request(connection, "actions-demand", {accountId: connection.accountId});
    if (!demand.collect || Date.now() < demand.retry_at * 1000) return;
    const tabs = await chrome.tabs.query({url: tabPattern("c411"), status: "complete"});
    if (!tabs.length) return;
    const run = async (input) => {
      let watchdog;
      const beat = setInterval(() => chrome.runtime.getPlatformInfo(), 10000);
      try {
        const frames = await Promise.race([
          chrome.scripting.executeScript({target: {tabId: tabs[0].id}, world: "ISOLATED",
            func: communityInTab, args: [input]}),
          new Promise((_, reject) => {watchdog = setTimeout(() => reject(new Error("Community timeout")), 120000);}),
        ]);
        return frames[0]?.result;
      } finally {clearTimeout(watchdog); clearInterval(beat);}
    };
    const observed = await run({accountId: connection.accountId, page: demand.page, seeds: demand.seeds, scan: demand.scan});
    if (!observed?.snapshot) {
      communityRetry[key] = Date.now() + Math.max(60, observed?.retryAfter || 60) * 1000;
      await chrome.storage.local.set({communityRetry});
      await note("Community: " + (observed?.reason || "read unavailable"));
      return;
    }
    await request(connection, "actions-observe", {accountId: connection.accountId, snapshot: observed.snapshot});
    const {command} = await request(connection, "actions-claim", {accountId: connection.accountId});
    if (!command) return;
    const base = {accountId: connection.accountId, id: command.id, attempt: command.attempt};
    communityReceipts[key] = {...base, outcome: "uncertain", reason: "network"};
    await chrome.storage.local.set({communityReceipts});
    let result;
    try { result = await run({accountId: connection.accountId, command}); }
    catch { result = {outcome: "uncertain", reason: "network"}; }
    const receipt = {...base, ...(result || {outcome: "uncertain", reason: "receipt"})};
    communityReceipts[key] = receipt;
    await chrome.storage.local.set({communityReceipts});
    await request(connection, "actions-receipt", receipt);
    delete communityReceipts[key];
    await chrome.storage.local.set({communityReceipts});
    await note("Community: " + receipt.outcome);
  } catch (error) {
    // Keep receipts, even when the app is offline or the pairing has changed.
    await note("Community waiting: " + String(error.status || "connection").slice(0, 60));
  }
}

async function sync() {
  const {
    connection,
    lastAttempt = 0,
    lastLedger = 0,
  } = await chrome.storage.local.get(["connection", "lastAttempt", "lastLedger"]);
  if (!connection || connection.paused || Date.now() - lastAttempt < PERIOD)
    return;
  const tabs = await chrome.tabs.query({
    url: tabPattern("c411"),
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
      args: [
        {
          details: true,
          seeds: true,
          ledger: Date.now() - lastLedger >= LEDGER_PERIOD,
        },
      ],
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
    if (snapshot.zenLedger) await chrome.storage.local.set({ lastLedger: Date.now() });
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
// ---- tr4ker: its own connection, tab, account binding and messages ----
const T4K = {
  connection: "connection-tr4ker",
  attempt: "lastAttempt-tr4ker",
  sync: "lastSync-tr4ker",
  shop: "lastShop-tr4ker",
  deep: "payoutsDone-tr4ker",
  message: "message-tr4ker",
};
const PAYOUT_PAGES = 40; // the first sync reads the whole log, later ones only the newest page
async function noteTr4ker(message) {
  await chrome.storage.local.set({ [T4K.message]: message });
}
async function tr4kerTab(open) {
  let tabs = await chrome.tabs.query({ url: tabPattern("tr4ker") });
  if (!tabs.length && open)
    tabs = [await chrome.tabs.create({ url: TRACKERS.tr4ker.origin + "/", active: true })];
  for (let i = 0; i < 60 && tabs[0] && tabs[0].status !== "complete"; i++) {
    await new Promise((done) => setTimeout(done, 500));
    tabs = [await chrome.tabs.get(tabs[0].id)];
  }
  return tabs[0]?.status === "complete" ? tabs[0] : null;
}
async function connectTr4ker(pending) {
  // The account comes from the signed-in tr4ker tab (id and name only), and the first
  // pairing binds it. Nothing else is read before the app accepts the code.
  const tab = await tr4kerTab(true);
  if (!tab) throw new Error("Open tr4ker.net in this browser, then connect again.");
  let identity;
  try {
    const frames = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: "ISOLATED", func: collectTr4ker,
      args: [{ identityOnly: true }],
    });
    identity = frames[0]?.result?.account;
  } catch {
    /* Not signed in, or the tab was closed. */
  }
  if (!identity?.id)
    throw new Error("Sign in to tr4ker in this browser, then click Retry in TorrentLinker.");
  const paired = await request({ target: pending.target, tracker: "tr4ker" }, "pair", {
    code: pending.code, accountId: identity.id, username: identity.username,
  });
  const connection = {
    target: pending.target, token: paired.token, accountId: identity.id,
    tracker: "tr4ker", paused: false,
  };
  const { connection: old } = await chrome.storage.local.get(T4K.connection);
  await chrome.storage.local.set({
    [T4K.connection]: connection, [T4K.attempt]: 0, [T4K.sync]: null, [T4K.deep]: false,
  });
  if (old && old.target !== connection.target) {
    try { await request(old, "disconnect", {}); } catch { /* Old receiver may be offline. */ }
  }
  await ensureAlarm();
  await syncTr4ker();
}
async function syncTr4ker() {
  const stored = await chrome.storage.local.get(Object.values(T4K));
  const connection = stored[T4K.connection];
  if (!connection || connection.paused || Date.now() - (stored[T4K.attempt] || 0) < PERIOD) return;
  const tabs = await chrome.tabs.query({ url: tabPattern("tr4ker"), status: "complete" });
  if (!tabs.length) {
    await noteTr4ker("Waiting for a signed-in tr4ker tab. Updates resume automatically when it opens.");
    return;
  }
  await chrome.storage.local.set({ [T4K.attempt]: Date.now() });
  try {
    const result = await chrome.scripting.executeScript({
      target: { tabId: tabs[0].id }, world: "ISOLATED", func: collectTr4ker,
      args: [{
        shop: Date.now() - (stored[T4K.shop] || 0) >= LEDGER_PERIOD,
        payoutPages: stored[T4K.deep] ? 1 : PAYOUT_PAGES,
      }],
    });
    const { snapshot, payoutPages } = result[0]?.result || {};
    if (!snapshot?.account?.id)
      throw new Error("Sign in to tr4ker. Sync will resume automatically.");
    if (snapshot.account.id !== connection.accountId)
      throw new Error(
        "Different tr4ker account. Sign in with the account connected in TorrentLinker.",
      );
    await request(connection, "snapshot", snapshot);
    const done = { [T4K.sync]: Date.now() };
    if (snapshot.shop) done[T4K.shop] = Date.now();
    if (payoutPages) {
      for (const entries of payoutPages)
        if (entries.length) await request(connection, "payouts", { accountId: connection.accountId, entries });
      done[T4K.deep] = true;
    }
    await chrome.storage.local.set(done);
    await noteTr4ker("Connected. Profile updates automatically every two minutes.");
  } catch (error) {
    if (error.status === 403) {
      await chrome.storage.local.remove(T4K.connection);
      await noteTr4ker("Connection revoked. Click Connect in TorrentLinker to reconnect.");
    } else await noteTr4ker(error.message || "Sync unavailable. Retrying automatically.");
  }
}
async function ensureAlarm() {
  if (!(await chrome.alarms.get("profile-sync")))
    await chrome.alarms.create("profile-sync", { periodInMinutes: 2 });
  if (!(await chrome.alarms.get("companion-commands")))
    await chrome.alarms.create("companion-commands", { periodInMinutes: 0.5 });
}
async function state() {
  const { connection, message, lastSync } = await chrome.storage.local.get([
    "connection",
    "message",
    "lastSync",
  ]);
  const t = await chrome.storage.local.get(Object.values(T4K));
  const tr4ker = {
    target: t[T4K.connection]?.target,
    accountId: t[T4K.connection]?.accountId,
    paused: t[T4K.connection]?.paused,
    connected: !!t[T4K.connection],
    message: t[T4K.message],
    lastSync: t[T4K.sync],
  };
  return {
    tr4ker,
    target: connection?.target,
    accountId: connection?.accountId,
    paused: connection?.paused,
    connected: !!connection,
    message,
    lastSync,
  };
}
chrome.runtime.onMessageExternal.addListener((message, sender, reply) => {
  // Lets the connect page tell an outdated companion apart; older ones answer with an error.
  if (message?.action === "version") {
    reply({ version: chrome.runtime.getManifest().version, trackers: ["c411", "tr4ker"] });
    return false;
  }
  serial(async () => {
    await connect(await validateConnection(message, sender));
    return { connected: true };
  }).then(reply, (error) => reply({ error: error.message }));
  return true;
});
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.url !== chrome.runtime.getURL("companion.html")) return false;
  serial(async () => {
    if (message.action === "creation") {
      const { connection } = await chrome.storage.local.get("connection");
      if (!connection || connection.paused) throw new Error("Connect and resume the companion first.");
      if (!["prepare", "publish", "cancel"].includes(message.operation)) throw new Error("Unknown creation action.");
      return request(connection, "creation", {accountId:connection.accountId,operation:message.operation,value:message.value});
    }
    if (message.tracker === "tr4ker" && ["disconnect", "pause"].includes(message.action)) {
      const { [T4K.connection]: connection } = await chrome.storage.local.get(T4K.connection);
      if (message.action === "disconnect") {
        await chrome.storage.local.remove(Object.values(T4K));
        if (connection) {
          try { await request(connection, "disconnect", {}); }
          catch {
            await noteTr4ker("Forgotten in this browser. Use Disconnect & clear in TorrentLinker if it was offline.");
          }
        }
      } else if (connection) {
        connection.paused = !connection.paused;
        await chrome.storage.local.set({ [T4K.connection]: connection });
        await noteTr4ker(connection.paused ? "Companion paused." : "Companion resumed.");
        if (!connection.paused) await syncTr4ker();
      }
      return state();
    }
    if (message.action === "disconnect") {
      const { connection } = await chrome.storage.local.get("connection");
      const keep = await chrome.storage.local.get(Object.values(T4K)); // tr4ker stays paired
      const {communityReceipts, communityRetry} = await chrome.storage.local.get(["communityReceipts", "communityRetry"]);
      await chrome.storage.local.clear();
      await chrome.storage.local.set({
        ...keep,
        communityReceipts: communityReceipts || {},
        communityRetry: communityRetry || {},
      });
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
            ? "Companion paused. Queued actions wait."
            : "Companion resumed.",
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
  if (alarm.name === "profile-sync") {
    serial(sync);
    serial(syncTr4ker);
  }
  if (alarm.name === "companion-commands") serial(commands);
});
chrome.tabs.onUpdated.addListener((_id, change, tab) => {
  if (change.status !== "complete") return;
  if (ownsUrl("c411", tab.url)) serial(async () => { await sync(); await commands(); });
  if (ownsUrl("tr4ker", tab.url)) serial(syncTr4ker);
});
// Recreate alarms after browser restart or extension upgrade. Connection state
// survives service-worker suspension. No cookies or login tokens are exported.
serial(async () => {
  await ensureAlarm();
  await sync();
  await commands();
  await syncTr4ker();
});
