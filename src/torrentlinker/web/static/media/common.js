"use strict";
/* Helpers shared by the Media browsing view and the Web player host. */
const mediaLayouts = ["cinematic", "focus", "collection"];
const mediaClient = () => state.clientId === "all" ? state.setup?.default_client_id || "default" : state.clientId || "default";
const mediaQuery = values => new URLSearchParams({client_id: mediaClient(), ...values}).toString();
function mediaOption(select, value, label) { const option = element("option", label); option.value = value; select.append(option); }
const mediaTime = n => {
  const seconds = Math.max(0, Math.floor(Number(n) || 0)), clock = `${String(seconds % 60).padStart(2, "0")}`;
  return seconds >= 3600 ? `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds / 60) % 60).padStart(2, "0")}:${clock}` : `${Math.floor(seconds / 60)}:${clock}`;
};
function mediaArt(row, className = "") {
  const art = element("div", undefined, `media-art ${className}`);
  if (row.artwork_url) {
    const image = element("img"); if (typeof mediaImage === "function") mediaImage(image, row); else image.src = row.artwork_url; image.alt = ""; image.loading = "lazy";
    image.onerror = () => { image.remove(); art.classList.add("missing-art"); };
    art.append(image);
  } else art.classList.add("missing-art");
  const fallback = element("span", row.title || row.album || say("Artwork unavailable", "Illustration indisponible"), "media-art-title");
  art.append(fallback); return art;
}
