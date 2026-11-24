"use strict";
// Preview overlay: adds only the proposed change to the real screens.
// 1. Utilisateurs > Modifier: a "Qualité maximale" select next to the Age limit.
// 2. Médias: the quality choice is remembered on this device and opens films at it,
//    else the highest allowed; the menu lists only what the limit allows.
const STEPS = [["", "Aucune limite"], ["360", "360p"], ["480", "480p"], ["720", "720p · HD"], ["1080", "1080p · Full HD"]];
const cookie = (name) => document.cookie.split("; ").find((c) => c.startsWith(name + "="))?.split("=")[1] || "";
const cap = () => cookie("preview_cap");
const KEY = "torrentlinker.quality";
const rank = (q) => (q === "original" ? 99999 : Number(q));

function addLimitField() {
  if (document.querySelector("[data-preview-quality]")) return;
  const age = [...document.querySelectorAll("label.settings-field")].find((l) => /Limite d’âge|Age limit/.test(l.firstChild?.textContent || ""));
  if (!age) return;
  const label = document.createElement("label");
  label.className = "settings-field"; label.dataset.previewQuality = "1";
  label.append("Qualité maximale");
  const select = document.createElement("select");
  for (const [value, text] of STEPS) select.add(new Option(text, value));
  select.value = cap();
  select.onchange = () => { document.cookie = `preview_cap=${select.value}; Path=/`; };
  const note = document.createElement("small");
  note.textContent = "Un Membre ne peut pas lire au-dessus, même en ouvrant le fichier d’origine. Ses Profils la suivent. Sans limite : l’original reste lisible.";
  label.append(select, note);
  age.after(label);
}

new MutationObserver(addLimitField).observe(document.documentElement, {childList: true, subtree: true});

window.addEventListener("DOMContentLoaded", () => {
  if (typeof mediaQuality !== "undefined") {
    let remembered = "";
    try { remembered = localStorage.getItem(KEY) || ""; } catch { /* nothing remembered */ }
    const set = mediaPlaybackFacts.set.bind(mediaPlaybackFacts);
    mediaPlaybackFacts.set = (id, facts) => {
      const allowed = facts.qualities || ["original"];
      // The last chosen quality, else the highest the Member may watch; never above the limit.
      const wanted = remembered && allowed.includes(remembered) ? remembered : "";
      mediaQuality = wanted || allowed[allowed.length - 1];
      return set(id, facts);
    };
    const change = mediaChangeQuality;
    mediaChangeQuality = async (values = {}) => {
      await change(values);
      try { if (values.quality) { remembered = values.quality; localStorage.setItem(KEY, values.quality); } } catch { /* not remembered */ }
    };
  }
});
