"use strict";
let environment = {},
  generation = 0,
  busy = false,
  pendingReload = false,
  lastError = "",
  widths = {},
  commandId = 0;
const connection = TLPanel.connect("torrents", { asynchronous: true });
async function request(action, body = {}) {
  const current = generation,
    send = await connection;
  const result = await send(action, { ...body, _client: environment.client });
  if (current !== generation)
    throw Error(
      TLPanel.t("Le client cible a changé.", "The target client changed."),
    );
  return result;
}
// An action started by a button keeps that button busy until it ends.
async function guard(fn, node) {
  node ??= TLToast.trigger();
  if (node) return TLToast.press(node, fn);
  try {
    return await fn();
  } catch (e) {
    lastError = e.message;
    notify(e.message);
  }
}
function formatBytes(n) {
  let i = 0;
  while (n >= 1024 && i < 4) {
    n /= 1024;
    i++;
  }
  return `${Number(n.toFixed(1))} ${["B", "KiB", "MiB", "GiB", "TiB"][i]}`;
}
function peerText(connected, total) {
  return `${connected >= 0 ? connected : "?"} (${total >= 0 ? total : "?"})`;
}
async function savePreferences() {
  await guard(() => request("preferences", { columns: cols, widths }));
}
function applyWidths() {
  document.querySelectorAll("[data-sort]").forEach((b) => {
    const th = b.closest("th"),
      key = b.dataset.sort;
    if (Number.isFinite(widths[key]))
      th.style.minWidth = Math.max(80, Math.min(600, widths[key])) + "px";
    const grip = document.createElement("span");
    grip.className = "resize-grip";
    grip.tabIndex = 0;
    grip.setAttribute("role", "separator");
    grip.setAttribute(
      "aria-label",
      TLPanel.t("Largeur de colonne", "Column width") + " " + b.textContent,
    );
    grip.onpointerdown = (e) => {
      e.preventDefault();
      const start = e.clientX,
        width = th.getBoundingClientRect().width;
      grip.setPointerCapture(e.pointerId);
      grip.onpointermove = (ev) => {
        widths[key] = Math.max(80, Math.min(600, width + ev.clientX - start));
        th.style.minWidth = widths[key] + "px";
      };
      grip.onpointerup = () => {
        grip.onpointermove = null;
        savePreferences();
      };
    };
    grip.onkeydown = (e) => {
      if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
      e.preventDefault();
      widths[key] = Math.max(
        80,
        Math.min(
          600,
          (widths[key] || th.getBoundingClientRect().width) +
            (e.key === "ArrowRight" ? 20 : -20),
        ),
      );
      th.style.minWidth = widths[key] + "px";
      savePreferences();
    };
    th.append(grip);
  });
}
// What the filters and the order ask the client for.
function listBody() {
  const keys = { client: "client_name", down: "download", up: "upload" };
  const body = {
    client_id: client,
    q: query,
    ...(hashes.length ? { hashes } : {}),
    sort: keys[sortKey] || sortKey,
    descending: sortDir < 0,
    ...filters,
  };
  for (const [local, remote] of Object.entries({
    scope: "scope",
    sizeMin: "size_min",
    sizeMax: "size_max",
    noteMin: "note_min",
    zenMin: "zen_min",
    weightMin: "weight_min",
    seedMax: "seed_max",
    daysMin: "days_min",
  })) {
    if (metrics[local] !== "")
      body[remote] =
        local === "scope"
          ? metrics[local]
          : Number(metrics[local]) *
            (local.startsWith("size")
              ? 1024 ** (sizeUnits[local] === "MiB" ? 2 : 3)
              : 1);
  }
  return body;
}
const toRow = (raw) => ({
  raw,
  id: raw.key,
  name: raw.name,
  client: raw.client_name,
  category: raw.categories.map((c) => c.join(" / ")).join(", "),
  tracker: raw.trackers.join(", "),
  tag: raw.tags.join(", "),
  state: raw.status,
  progress: Math.round(raw.progress * 100),
  size: raw.size / 1024 ** 3,
  ratio: raw.ratio,
  c411: raw.c411,
  note: raw.note,
  zen: raw.zen,
  weight: raw.weight,
  seeds: raw.total_seeds,
  peers: raw.total_peers,
  seedtime: raw.seedtime,
});
async function load() {
  if (busy) {
    pendingReload = true;
    return;
  }
  busy = true;
  const current = generation;
  try {
    const body = { ...listBody(), offset: 0, limit: shown };
    const result = await request("list", body);
    if (current !== generation) return;
    snapshot = result;
    // A category or tag whose last torrent is gone shows as "all" in its list: filter as it
    // says, or the list stays empty on a value nothing carries any more.
    const gone = [["category", result.categories], ["tag", result.tags]].filter(
      ([key, values]) => filters[key] && !values.includes(filters[key]),
    );
    if (gone.length) {
      for (const [key] of gone) filters[key] = "";
      shown = STEP;
      pendingReload = true;
      return;
    }
    data = result.rows.map(toRow);
    data.forEach((r) => rowCache.set(r.id, r));
    // A ticked head box means every match: when the filters change, so does the selection.
    if (allMatching && allSignature !== JSON.stringify(listBody())) await selectAll();
    if (!focus || !rowCache.has(focus)) focus = data[0]?.id || "";
    scenario = "normal";
    lastError = "";
    render();
    if (result.client_errors.length)
      notify(
        result.client_errors.map((e) => e.name + ": " + e.message).join(" · "),
      );
  } catch (e) {
    const repeated = lastError === e.message;
    lastError = e.message;
    if (current === generation) {
      if (!data.length) scenario = "error";
      render();
      // The 5 s refresh must not bring a dismissed error back every time.
      if (!repeated) notify(lastError);
    }
  } finally {
    busy = false;
    if (pendingReload) {
      pendingReload = false;
      guard(load);
    }
  }
}
// Every torrent the filters match, across the whole list, becomes the selection.
async function selectAll() {
  const body = listBody(),
    result = await request("list", { ...body, offset: 0, limit: 1e9 });
  selected.clear();
  for (const raw of result.rows) {
    const row = toRow(raw);
    rowCache.set(row.id, row);
    selected.add(row.id);
  }
  allMatching = true;
  allSignature = JSON.stringify(body);
}
// The table loads the next rows as it is scrolled near its end.
async function loadMore() {
  if (busy || shown >= snapshot.total) return;
  shown += STEP;
  await load();
}
window.addEventListener("DOMContentLoaded", () => {
  render();
  window.addEventListener("torrents-environment", (e) =>
    guard(async () => {
      const next = e.detail,
        changed = environment.client !== next.client,
        languageChanged = lang !== next.language,
        newCommand = next.command && commandId !== next.command.id;
      environment = next;
      lang = next.language || "en";
      mode = next.mode || "web";
      theme = next.theme || "dark";
      TLPanel.setLanguage(lang);
      document.documentElement.dataset.theme = theme;
      if (changed) {
        generation++;
        client = next.client || "all";
        selected.clear();
        rowCache.clear();
        data = [];
        focus = "";
        shown = STEP;
        allMatching = false;
        $("dialog").close();
        const preferences = await request("preferences");
        if (preferences.columns)
          for (const k of Object.keys(cols))
            if (typeof preferences.columns[k] === "boolean")
              cols[k] = preferences.columns[k];
        widths = preferences.widths || {};
      }
      if (newCommand) {
        commandId = next.command.id;
        query = next.command.hash || "";
        hashes = next.command.hashes || [];
        if (typeof next.command.tracker === "string") filters.tracker = next.command.tracker;
        focus = "";
        shown = STEP;
        allMatching = false;
      }
      if (
        next.active &&
        (changed || languageChanged || !data.length || newCommand)
      )
        await load();
      else if (languageChanged) render();
    }),
  );
  connection.then(() => window.torrentsReady());
  // A refresh redraws the page, which closes an open list: it waits while a list has focus.
  // The 5 s count from the end of the last answer, so a slow client never chains them.
  const refresh = () =>
    setTimeout(async () => {
      if (
        environment.active &&
        !document.hidden &&
        !busy &&
        !$("dialog").open &&
        document.activeElement?.tagName !== "SELECT"
      )
        await guard(load);
      refresh();
    }, 5000);
  refresh();
});
