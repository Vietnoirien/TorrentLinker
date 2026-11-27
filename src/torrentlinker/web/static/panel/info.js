"use strict";
// The app's one ⓘ info box. TLInfo.html(text, label, action) returns the button; the box opens on a
// click, on Enter/Space, or on hover (with a close delay so the pointer can reach a button inside it),
// closes on Esc, a click elsewhere or a scroll, and works on a phone (tap). An action names a button
// in the box: it dispatches "tl-info-action" (detail = the action) on the document.
(() => {
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const french = () => {
    try { return (parent.document.documentElement.lang || document.documentElement.lang || "fr") === "fr"; } catch { return true; }
  };
  const html = (text, label, action = "", actionLabel = "") =>
    `<button type="button" class="info" data-info="${esc(text)}" ${action ? `data-info-act="${esc(action)}" data-info-act-label="${esc(actionLabel)}"` : ""} aria-label="${esc(label || (french() ? "Plus d'informations" : "More information"))}" aria-expanded="false">i</button>`;
  let box = null, current = null, timer = 0, byHover = false;
  const hide = () => { if (box) box.hidden = true; current?.setAttribute("aria-expanded", "false"); current = null; };
  function open(btn) {
    if (!box) { box = document.createElement("div"); box.className = "tip"; box.id = "tl-tip"; box.setAttribute("role", "tooltip"); box.hidden = true; }
    current?.setAttribute("aria-expanded", "false");
    (btn.closest("dialog") || document.body).append(box);
    current = btn; btn.setAttribute("aria-expanded", "true");
    const act = btn.dataset.infoAct;
    box.innerHTML = `<span></span>${act ? `<button type="button" data-info-do="${esc(act)}">${esc(btn.dataset.infoActLabel || (french() ? "Ouvrir" : "Open"))}</button>` : ""}`;
    box.firstChild.textContent = btn.dataset.info;
    box.hidden = false;
    const r = btn.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + "px";
    box.style.top = (r.bottom + 6 + h > innerHeight - 8 && r.top - h - 6 > 8 ? r.top - h - 6 : r.bottom + 6) + "px";
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".info"), go = e.target.closest("#tl-tip [data-info-do]");
    if (go) { const a = go.dataset.infoDo; hide(); document.dispatchEvent(new CustomEvent("tl-info-action", { detail: a })); return; }
    if (b) { e.preventDefault(); e.stopPropagation(); if (current === b && !byHover) hide(); else { byHover = false; open(b); } }
    else if (!e.target.closest("#tl-tip")) hide();
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  const hover = () => matchMedia("(hover:hover)").matches;
  document.addEventListener("mouseover", (e) => {
    if (!hover()) return;
    const b = e.target.closest?.(".info");
    if (b || e.target.closest?.("#tl-tip")) clearTimeout(timer);
    if (b && current !== b) { byHover = true; open(b); }
  });
  document.addEventListener("mouseout", (e) => {
    if (!hover() || !(e.target.closest?.(".info") || e.target.closest?.("#tl-tip"))) return;
    const to = e.relatedTarget;
    if (to?.closest?.("#tl-tip") || (current && to?.closest?.(".info") === current)) return;
    clearTimeout(timer);
    timer = setTimeout(hide, 300);
  });
  addEventListener("scroll", hide, true);
  window.TLInfo = { html, hide };
})();
