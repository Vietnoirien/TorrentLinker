"use strict";
/* The proposal, layered on the real panel:
   - the box at the head of the table selects every torrent the filters match, not a page;
     while it is ticked the selection follows the filters, and unticking one row leaves the
     others selected;
   - pages are gone: the table loads 100 more rows as it is scrolled near its end.
   The selection stays the panel's own `selected` set, so Resume, Pause, Transfer…, More…
   and Remove… act on it without change. */

const STEP = 100;
let proposal = true,
  shown = STEP, // rows loaded so far
  lastListBody = {},
  allMatching = false, // the head box is ticked: the selection is every match
  allSignature = "",
  loadingMore = false;

// What the filters ask for, without the order or how far the table is loaded.
const listingSignature = (body = lastListBody) => {
  const { offset, limit, sort, descending, ...rest } = body;
  return JSON.stringify(rest);
};
const baseRequest = request;
request = async (action, body = {}) => {
  if (action === "list" && proposal) {
    // A filter change starts the table from its top again.
    if (listingSignature(body) !== listingSignature()) shown = STEP;
    body = { ...body, offset: 0, limit: shown };
  }
  if (action === "list") lastListBody = body;
  const result = await baseRequest(action, body);
  if (action === "list" && proposal && allMatching && allSignature !== listingSignature())
    await selectAll();
  return result;
};
// The same row shape load() builds in torrents/transport.js.
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
const count = (n) => n.toLocaleString(lang === "fr" ? "fr-FR" : "en-US");

async function selectAll() {
  const { offset, limit, ...body } = lastListBody;
  const result = await baseRequest("match", body);
  selected.clear();
  for (const raw of result.rows) {
    const row = toRow(raw);
    rowCache.set(row.id, row);
    selected.add(row.id);
  }
  allMatching = true;
  allSignature = listingSignature();
}

async function loadMore() {
  if (loadingMore || shown >= snapshot.total) return;
  loadingMore = true;
  shown += STEP;
  try {
    await load();
  } finally {
    loadingMore = false;
  }
}

const basePaint = paint;
paint = function () {
  basePaint();
  hint();
  if (!proposal || scenario !== "normal") return;
  const head = $("select-page"),
    total = snapshot.total;
  if (head) {
    const label = t(`Tout sélectionner (${count(total)})`, `Select all (${count(total)})`);
    head.setAttribute("aria-label", label);
    head.title = label;
    head.checked = allMatching && selected.size === total && total > 0;
    head.indeterminate = !head.checked && selected.size > 0;
    head.closest("th").classList.add("proposal");
    head.onchange = () =>
      guard(async () => {
        if (head.checked) await selectAll();
        else {
          selected.clear();
          allMatching = false;
        }
        render();
      });
  }
  // Unticking or ticking one row makes the selection a plain list again.
  document.querySelectorAll("[data-select]").forEach((box) => {
    const base = box.onchange;
    box.onchange = () => {
      allMatching = false;
      base();
    };
  });
  const status = document.querySelector("section.panel > .status > span");
  if (status && allMatching && selected.size === total)
    status.textContent = t(
      `Les ${count(total)} torrents correspondants sont sélectionnés`,
      `All ${count(total)} matching torrents selected`,
    );
  // The pager becomes a count of what is loaded.
  const pager = $("prev")?.closest(".status");
  if (pager) {
    pager.classList.add("proposal");
    pager.replaceChildren(
      Object.assign(document.createElement("small"), {
        textContent:
          data.length < total
            ? t(
                `${count(data.length)} sur ${count(total)} torrents affichés · la suite se charge au défilement`,
                `${count(data.length)} of ${count(total)} torrents shown · more load as you scroll`,
              )
            : t(`${count(total)} torrents, tous affichés`, `All ${count(total)} torrents shown`),
      }),
    );
  }
  const scroller = document.querySelector(".table-scroll");
  if (scroller)
    scroller.onscroll = () => {
      if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 400)
        guard(loadMore);
    };
};

function hint() {
  $("demo-hint").textContent = proposal
    ? t(
        "La case en tête du tableau sélectionne tout ce que les filtres trouvent. Faites défiler le tableau : plus de pages.",
        "The box at the head of the table selects everything the filters match. Scroll the table: no more pages.",
      )
    : t("Écran actuel, sans la proposition.", "Current screen, without the proposal.");
}
$("demo-theme").onclick = () => {
  theme = theme === "dark" ? "light" : "dark";
  $("demo-theme").textContent = theme === "light" ? "Thème : clair" : "Thème : sombre";
  render();
};
$("demo-lang").onclick = () => {
  lang = lang === "fr" ? "en" : "fr";
  TLPanel.setLanguage(lang);
  document.documentElement.lang = lang;
  $("demo-lang").textContent = lang.toUpperCase();
  render();
};
$("demo-proposal").onclick = () => {
  proposal = !proposal;
  $("demo-proposal").setAttribute("aria-pressed", String(proposal));
  $("demo-proposal").textContent = proposal ? "Proposition : activée" : "Proposition : désactivée";
  shown = STEP;
  allMatching = false;
  selected.clear();
  page = 0;
  guard(load);
};
