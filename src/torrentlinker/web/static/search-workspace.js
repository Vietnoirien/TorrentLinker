"use strict";
const searchFrame = document.createElement("iframe");
searchFrame.id = "search-frame";
searchFrame.title = "Search and download queue";
searchFrame.src = "static/search/view.html";
searchFrame.style.cssText =
  "width:100%;height:calc(100vh - 160px);min-height:240px;border:0;display:block";
$("view-search").append(searchFrame);
function searchEnvironment() {
  const active =
    ["search", "queue"].includes(state.view) && !$("workspace").hidden;
  if (active) {
    if ($("view-search").hidden) $("view-search").hidden = false;
    if (!$("view-queue").hidden) $("view-queue").hidden = true;
    searchFrame.style.height = `${Math.max(240, innerHeight - searchFrame.getBoundingClientRect().top - 32)}px`;
  }
  searchFrame.contentWindow?.postMessage(
    {
      type: "search-environment",
      value: {
        mode: "web",
        language,
        client: state.clientId,
        active,
        page: state.view === "queue" ? "queue" : "search",
        theme: document.documentElement.dataset.theme || "dark",
      },
    },
    location.origin,
  );
}
function loadSearchPage() {
  searchEnvironment();
}
function loadQueue() {
  searchEnvironment();
}
function searchRetranslate() {
  searchEnvironment();
}
window.addEventListener("message", async (e) => {
  if (e.source !== searchFrame.contentWindow || e.origin !== location.origin)
    return;
  const m = e.data;
  if (m?.type === "search-ready") {
    searchEnvironment();
    return;
  }
  if (m?.type !== "search-request") return;
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    const body = { ...m.body };
    if (body._client !== state.clientId)
      throw Error("The target client changed.");
    delete body._client;
    let value = { ok: true };
    if (m.path === "preferences") {
      value = {};
      for (const key of ["tl-search-density", "tl-search-posters"]) {
        if (typeof body[key] === "string") localStorage.setItem(key, body[key]);
        value[key] = localStorage.getItem(key);
      }
    } else if (m.path === "navigate") {
      if (!["search", "queue"].includes(body.page))
        throw Error("Invalid page.");
      await navigate(body.page);
    } else if (m.path === "subscribe") await editFeed(null, body.query);
    else if (m.path === "torrents") await navigate("torrents");
    else if (m.path === "details")
      await details(body.row, async () => {
        const child = searchFrame.contentWindow;
        child.postMessage(
          { type: "search-enqueue", hash: body.row.hash },
          location.origin,
        );
        $("dialog").close();
      });
    else
      value = await api(
        "search/workspace/" +
          encodeURIComponent(m.path) +
          "?client_id=" +
          encodeURIComponent(state.clientId),
        body,
      );
    searchFrame.contentWindow?.postMessage(
      { type: "search-response", id: m.id, value },
      location.origin,
    );
  } catch (error) {
    searchFrame.contentWindow?.postMessage(
      { type: "search-response", id: m.id, error: error.message },
      location.origin,
    );
  }
});
window.addEventListener("resize", searchEnvironment);
document.addEventListener("tl-language-changed", searchEnvironment);
new MutationObserver(searchEnvironment).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["data-theme"],
});
new MutationObserver(() => {
  if (!["search", "queue"].includes(state.view)) searchEnvironment();
}).observe($("workspace"), { attributes: true, attributeFilter: ["hidden"] });

new MutationObserver(searchEnvironment).observe($("view-search"), {
  attributes: true,
  attributeFilter: ["hidden"],
});
