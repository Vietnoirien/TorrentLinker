"use strict";
const libraryUI = {folder:"", selected:new Set(), item:null, candidates:[], chosen:new Map(), candidate:null, client:null, generation:0, loadGeneration:0, detailGeneration:0, tab:"summary"};
const libraryMatch = value => ({full:say("Full Match","Correspondance complète"),partial:say("Partial Match","Correspondance partielle"),none:say("No Match","Aucune correspondance"),unchecked:say("Not checked","Non vérifié")}[value] || value);

async function loadLibrary() {
  if (libraryUI.client !== state.clientId) {
    libraryUI.client = state.clientId;
    libraryUI.selected.clear(); libraryUI.chosen.clear(); libraryUI.item = null;
    libraryUI.candidate = null; libraryUI.generation++; libraryUI.detailGeneration++;
    $("candidates").hidden = true; $("library-results").hidden = false;
    $("library-items").classList.remove("library-expanded");
  }
  const generation = ++libraryUI.loadGeneration;
  const params = new URLSearchParams({q:$("library-query").value, offset:state.libraryOffset, folder:libraryUI.folder, state:$("library-state").value});
  const response = await api(`library?${params}`);
  if (generation !== libraryUI.loadGeneration) return;
  table("library-table", response.rows, [
    {label:say("Local Item","Élément local"), name:true, render:r=>button(r.name,()=>reviewLibraryItem(r))},
    {label:say("State","État"),render:r=>({orphan:say("Orphan","Orphelin"),seeded:say("Seeded","Seedé"),"partially-seeded":say("Partially seeded","Partiellement seedé"),unknown:say("Seeding status unknown","État du seed inconnu")}[r.state] || r.state)},
    {label:say("Size","Taille"),render:r=>bytes(r.size)},
    {label:say("Folder","Dossier"),render:r=>{const path=element("span",r.folder,"library-folder-path");path.title=r.folder;return path;}},
    {label:"",render:r=>button(say("Find candidates","Chercher des candidats"),()=>check(r))},
    {label:"Upload",render:r=>button(say("Prepare","Préparer"),()=>prepareUpload(r))},
  ], libraryUI.selected, "path", updateLibrarySelection);
  $("library-count").textContent = `${response.total} · ${Math.floor(state.libraryOffset/100)+1}`;
  $("library-prev").disabled = !state.libraryOffset;
  $("library-next").disabled = state.libraryOffset+100 >= response.total;
  updateLibrarySelection();
  libraryUI.folderCounts=response.folder_counts; libraryUI.folderErrors=response.folder_errors;
  renderLibraryFolders();
}
function updateLibrarySelection() {
  $("library-selection-count").textContent = say(`${libraryUI.selected.size} selected`,`${libraryUI.selected.size} sélectionné(s)`);
  $("library-search-selected").disabled = !libraryUI.selected.size;
}
function renderLibraryFolders() {
  const folders = state.setup?.folders || [];
  if (libraryUI.folder && !folders.some(f=>f.local===libraryUI.folder)) libraryUI.folder="";
  const rail = $("library-folders"); rail.replaceChildren();
  for (const f of [{local:"",label:say("All folders","Tous les dossiers")},...folders]) {
    const b = button(f.label || f.local.split(/[\\/]/).filter(Boolean).pop() || f.local, async()=>{
      libraryUI.folder=f.local; state.libraryOffset=0; await loadLibrary();
    });
    const count=f.local?libraryUI.folderCounts?.[f.local]:Object.values(libraryUI.folderCounts || {}).reduce((a,b)=>a+b,0);
    if(count !== undefined) b.textContent+=` · ${count}`;
    if((libraryUI.folderErrors || []).some(path=>path===f.local || path.startsWith(f.local+"/"))) b.textContent+=say(" · Incomplete scan"," · Analyse incomplète");
    b.title=f.local; b.setAttribute("aria-pressed",String(libraryUI.folder===f.local)); rail.append(b);
  }
  const list=$("library-folder-list"); list.replaceChildren();
  for (const f of folders) {
    const row=element("div",undefined,"library-folder-row");
    const stale=(libraryUI.folderErrors || []).some(path=>path===f.local || path.startsWith(f.local+"/"));
    const health=stale?say("Scan incomplete · previous items kept","Analyse incomplète · éléments précédents conservés"):say("Scan to check file access","Analyser pour vérifier l’accès aux fichiers");
    row.append(element("span",`${f.local} · ${f.kind} · ${say("Depth","Profondeur")} ${f.depth} · ${health}`));
    const actions=element("div",undefined,"actions");
    actions.append(button(say("Edit","Modifier"),()=>editLibraryFolder(f)),button(say("Remove","Retirer"),async()=>{
      if (!confirm(say(`Remove ${f.local} from the Library? Files stay on disk.`,`Retirer ${f.local} de la bibliothèque ? Les fichiers sont conservés.`))) return;
      await api("setup/remove-folder",{local:f.local,purpose:"library"});
      if (libraryUI.item?.folder === f.local) { libraryUI.item=null; libraryUI.generation++; $("candidates").hidden=true; }
      await refreshSetup(); renderLibraryFolders();
    }));
    row.append(actions); list.append(row);
  }
}
async function libraryTab(tab) {
  document.querySelectorAll("[data-library-tab]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.libraryTab===tab)));
  $("library-items").hidden=tab!=="items";
  $("library-folder-manager").hidden=tab!=="folders";
  $("library-activity").hidden=tab!=="activity";
  if(tab==="folders") {await refreshSetup();renderLibraryFolders();}
  if(tab==="items") await loadLibrary();
  if(tab==="activity") await loadLibraryActivity();
}
function editLibraryFolder(folder) {
  $("library-folder-path").value=folder.local;
  $("library-folder-path").readOnly=true;
  $("library-folder-kind").value=folder.kind;
  const select=$("library-folder-depth");
  if(![...select.options].some(o=>o.value===String(folder.depth))) select.add(new Option(`Depth ${folder.depth}`,folder.depth));
  select.value=folder.depth;
  $("library-folder-form-title").textContent=say("Edit Library Folder","Modifier le dossier");
  $("library-folder-feedback").textContent="";
  $("library-folder-browse").disabled=true;
}
function newLibraryFolder() {
  $("library-folder-form").reset(); $("library-folder-path").readOnly=false;
  $("library-folder-browse").disabled=false;
  $("library-folder-form-title").textContent=say("Add a Library Folder","Ajouter un dossier");
  $("library-folder-feedback").textContent="";
}
async function browseLibraryFolder(path="") {
  const result=await api(`folders?path=${encodeURIComponent(path)}`);
  $("dialog-title").textContent=say("Folders on the TorrentLinker server","Dossiers du serveur TorrentLinker");
  const host=$("dialog-content");host.replaceChildren(element("p",result.path || say("Mounted roots","Racines montées")));
  if(result.path) {
    host.append(button(say("Use this folder","Utiliser ce dossier"),()=>{$("library-folder-path").value=result.path;$("dialog").close();},"primary"));
    host.append(button("↑",()=>browseLibraryFolder(result.parent)));
  }
  for(const folder of result.folders) host.append(button(folder,()=>browseLibraryFolder(folder),"directory-button"));
  if(!result.path && !result.folders.length) host.append(element("p",say("No mounted roots. Set TL_STORAGE_ROOTS on the TorrentLinker server.","Aucune racine montée. Configurez TL_STORAGE_ROOTS sur le serveur.")));
  if(!$("dialog").open) $("dialog").showModal();
}
async function reviewLibraryItem(row, search=false) {
  libraryUI.item=row; libraryUI.candidate=null; libraryUI.candidates=[];
  const generation=++libraryUI.generation;
  libraryUI.detailGeneration++;
  $("candidates").hidden=false; $("library-empty-review").hidden=true;
  $("candidate-title").textContent=`${row.name} · ${bytes(row.size)} · ${row.folder}`;
  $("candidate-table").replaceChildren(element("p",say("Loading Candidates…","Chargement des candidats…")));
  $("candidate-actions").replaceChildren();
  $("candidate-summary").replaceChildren(); $("candidate-files").replaceChildren();
  $("candidate-description").replaceChildren(); $("candidate-nfo").textContent="";
  await job({kind:search?"check":"library-review",path:row.path}, rows=>{
    if(generation!==libraryUI.generation) return;
    showLibraryCandidates(rows);
  });
}
async function check(row) { return reviewLibraryItem(row,true); }
function showLibraryCandidates(rows) {
  libraryUI.candidates=rows;
  const wanted=libraryUI.chosen.get(libraryUI.item.path);
  libraryUI.candidate=rows.find(c=>c.key===wanted) || rows[0] || null;
  renderCandidateChoices();
  showLibraryCandidate(libraryUI.candidate);
}
function renderCandidateChoices() {
  const host=$("candidate-table");host.replaceChildren();
  if(!libraryUI.candidates.length) host.append(element("p",say("No Candidates. Search this item to find matching torrents.","Aucun candidat. Lancez une recherche pour cet élément.")));
  for(const c of libraryUI.candidates) {
    const b=button(c.title,()=>{libraryUI.candidate=c;renderCandidateChoices();showLibraryCandidate(c);},"candidate-choice");
    b.append(element("small",`${libraryMatch(c.match)} · ${bytes(c.size)} · ${c.seeders} seeders${c.archive?" · Archive":""}`));
    b.setAttribute("aria-pressed",String(c===libraryUI.candidate));host.append(b);
  }
}
function showLibraryCandidate(candidate) {
  libraryUI.detailGeneration++;
  $("candidate-actions").replaceChildren(); $("candidate-files").replaceChildren();
  $("candidate-description").replaceChildren(); $("candidate-nfo").textContent="";
  $("candidate-summary").replaceChildren();
  if(!candidate) return;
  libraryUI.chosen.set(libraryUI.item.path,candidate.key);
  $("candidate-summary").append(element("h3",candidate.title),element("p",`${libraryMatch(candidate.match)} · ${bytes(candidate.size)} · ${candidate.seeders} seeders`),element("p",libraryUI.item.path),element("p",say("A Match compares file names and sizes. Your Torrent Client verifies the hashes before seeding.","La correspondance compare les noms et tailles. Le client torrent vérifie les hashes avant le seed."),"muted"));
  table("candidate-files",candidate.files,[{label:say("Torrent file","Fichier du torrent"),render:f=>f.torrent},{label:say("Local file","Fichier local"),render:f=>f.local || "—"},{label:say("Result","Résultat"),render:f=>f.status}],null);
  const actions=$("candidate-actions");
  const checkButton=button(say("Check Candidate","Vérifier le candidat"),()=>candidateAction("check-candidate"));
  checkButton.disabled=candidate.match!=="unchecked";
  actions.append(checkButton,button(say("Reject Candidate","Rejeter le candidat"),()=>candidateAction("library-reject")));
  const reseed=button(candidate.archive?say("Unpack and reseed…","Extraire et seeder…"):say("Verify & reseed","Vérifier et seeder"),async()=>{
    if(candidate.archive) {await previewArchive(candidate);return;}
    const path=libraryUI.item.path, hash=candidate.hash;
    if(!confirm(say(`Verify and reseed ${candidate.title}? Missing files will not be downloaded. Check the Files tab for renamed paths.`,`Vérifier et remettre en seed ${candidate.title} ? Les fichiers manquants ne seront pas téléchargés.`))) return;
    await job({kind:"reseed",path,hashes:[hash]},()=>toast(say("Verification started.","Vérification lancée.")));
  },"primary");
  reseed.disabled=!(candidate.archive?candidate.key:candidate.hash) || !["full","partial"].includes(candidate.match);
  actions.append(reseed);
  if(candidate.archive) $("candidate-summary").append(element("p",say("Review the extraction destination and available server space before unpacking and reseeding.","Examinez la destination et l’espace disponible sur le serveur avant d’extraire et de seeder.")));
  if(candidate.website) {const link=element("a",say("Open on website","Ouvrir sur le site"));link.href=candidate.website;link.target="_blank";link.rel="noopener noreferrer";actions.append(link);}
  candidateTab(libraryUI.tab);
}
async function candidateAction(kind) {
  const item=libraryUI.item, candidate=libraryUI.candidate, generation=libraryUI.generation;
  if(!item || !candidate) return;
  await job({kind,path:item.path,candidate_key:candidate.key},rows=>{if(generation===libraryUI.generation) showLibraryCandidates(rows);});
}
function candidateTab(tab) {
  libraryUI.tab=tab;
  document.querySelectorAll("[data-candidate-tab]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.candidateTab===tab)));
  for(const name of ["summary","files","description","nfo"]) $("candidate-"+name).hidden=name!==tab;
  if(["description","nfo"].includes(tab)) guard(loadLibraryDetails);
}
async function loadLibraryDetails() {
  const candidate=libraryUI.candidate, generation=libraryUI.detailGeneration;
  if(!candidate) return;
  if(!candidate.hash) {$("candidate-description").textContent=$("candidate-nfo").textContent=say("Open the Indexer website for these details.","Consultez ces détails sur le site de l’indexeur.");return;}
  if(candidate.details) {renderLibraryDetails(candidate.details);return;}
  if(candidate.loading) return;
  candidate.loading=true;
  $("candidate-description").textContent=$("candidate-nfo").textContent=say("Loading…","Chargement…");
  try {
    await job({kind:"details",hashes:[candidate.hash]},result=>{
      candidate.loading=false;candidate.details=result;
      if(generation===libraryUI.detailGeneration) renderLibraryDetails(result);
    }, error=>{candidate.loading=false;if(generation===libraryUI.detailGeneration) $("candidate-description").textContent=$("candidate-nfo").textContent=error;});
  } catch(error) {candidate.loading=false;throw error;}
}
function renderLibraryDetails(result) {
  // Same server-sanitized preview_html renderer used by Search.
  $("candidate-description").innerHTML=result.description || say("No description supplied.","Aucune description.");
  $("candidate-description").querySelectorAll("a").forEach(a=>{a.target="_blank";a.rel="noopener noreferrer";});
  $("candidate-nfo").textContent=result.nfo || say("No NFO supplied.","Aucun NFO.");
}
async function searchLibrary(selected) {
  const paths=selected?[...libraryUI.selected]:[];
  const generation=libraryUI.generation;
  await job({kind:"search-library",paths},result=>{
    toast(say(`Searched ${result.results.length} items. ${result.errors.length} errors.`,`${result.results.length} éléments cherchés. ${result.errors.length} erreurs.`));
    if(generation===libraryUI.generation && libraryUI.item) {
      const found=result.results.find(r=>r.path===libraryUI.item.path);if(found) showLibraryCandidates(found.rows);
    }
  });
}
async function loadLibraryActivity() {
  const rows=await api("jobs"),host=$("library-job-list");host.replaceChildren();
  for(const row of rows.filter(r=>["scan","check","check-all","reseed","reseed-all","search-library","library-review","library-reject","check-candidate","preview-unpack","unpack-reseed"].includes(r.kind))) {
    const card=element("div",undefined,"card");card.append(element("p",`${row.kind} · ${row.status}`));
    if(row.progress?.total) card.append(element("p",`${bytes(row.progress.done)} / ${bytes(row.progress.total)}`));
    if(row.error) card.append(element("p",row.error));
    if(["queued","running"].includes(row.status) && row.progress?.cancellable!==false) card.append(button(say("Cancel","Annuler"),async()=>{await api(`jobs/${row.id}/cancel`,{});await loadLibraryActivity();}));
    card.append(button(say("Details","Détails"),()=>navigate("jobs")));host.append(card);
  }
  if(!host.children.length) host.append(element("p",say("No Library activity yet.","Aucune activité pour le moment.")));
}
for(const b of document.querySelectorAll("[data-library-tab]")) b.onclick=()=>guard(()=>libraryTab(b.dataset.libraryTab));
for(const b of document.querySelectorAll("[data-candidate-tab]")) b.onclick=()=>candidateTab(b.dataset.candidateTab);
$("library-manage-folders").onclick=()=>guard(()=>libraryTab("folders"));
$("library-folder-browse").onclick=()=>guard(()=>browseLibraryFolder());
$("library-folder-new").onclick=newLibraryFolder;
$("library-folder-form").onsubmit=e=>{e.preventDefault();guard(async()=>{
  const local=$("library-folder-path").value.trim();
  await api("setup/folder",{local,kind:$("library-folder-kind").value,depth:Number($("library-folder-depth").value),purpose:"library"});
  await refreshSetup();renderLibraryFolders();newLibraryFolder();
  $("library-folder-feedback").textContent=say(`Saved ${local}. Scan folders to refresh the Library.`,`${local} enregistré. Analysez les dossiers pour actualiser la bibliothèque.`);
});};
$("library-state").onchange=()=>{state.libraryOffset=0;guard(loadLibrary);};
$("library-search-selected").onclick=()=>guard(()=>searchLibrary(true));
$("library-search-all").onclick=()=>guard(()=>searchLibrary(false));
$("candidate-search").onclick=()=>guard(()=>libraryUI.item && check(libraryUI.item));
$("candidate-expand").onclick=()=>{
  const expanded=!$("library-results").hidden;
  $("library-results").hidden=expanded;$("library-items").classList.toggle("library-expanded",expanded);
  $("candidate-expand").textContent=expanded?say("Back to Local Items","Retour aux éléments"):say("Expand review","Agrandir");
};

$("settings-library-folders").onclick=()=>guard(async()=>{await navigate("library");await libraryTab("folders");});

function renderLibraryDownloads() {
  const folders=state.setup.download_folders || {default:"",by_category:{},effective:{}};
  const categories=state.setup.indexer_categories || {};
  const select=$("library-download-category"), current=select.value;
  select.replaceChildren(new Option(say("Default","Par défaut"),""));
  for(const [id,category] of Object.entries(categories)) select.add(new Option(category.name,id));
  select.value=current;
  const host=$("library-download-destinations");host.replaceChildren();
  for(const [id,path] of [["",folders.default],...Object.entries(folders.by_category)]) {
    const row=element("div",undefined,"library-folder-row");
    row.append(element("span",`${id?(categories[id]?.name || id):say("Default","Par défaut")} · ${path || say("Not set","Non configuré")}`));
    row.append(button(say("Edit","Modifier"),()=>{select.value=id;$("library-download-path").value=path;}));
    if(path) row.append(button(id?say("Use inherited destination","Utiliser la destination héritée"):say("Clear default","Retirer le dossier par défaut"),async()=>{
      await api("setup/remove-folder",{purpose:"download",local:path,category:id?Number(id):null});await refreshSetup();
    }));
    host.append(row);
  }
  select.onchange=()=>{
    $("library-download-path").value=select.value?folders.by_category[select.value] || "":folders.default;
    $("library-download-feedback").textContent=say("Effective destination: ","Destination effective : ")+(select.value?folders.effective[select.value]:folders.default || "—");
  };
}
$("library-download-form").onsubmit=e=>{e.preventDefault();guard(async()=>{
  const category=$("library-download-category").value;
  await job({kind:"configure-download-folder",path:$("library-download-path").value.trim(),category:category?Number(category):null},async()=>{
    await refreshSetup();$("library-download-feedback").textContent=say("Destination verified and saved.","Destination vérifiée et enregistrée.");
  });
});};

$("scan").onclick=()=>guard(()=>job({kind:"scan"},async result=>{
  libraryUI.generation++; libraryUI.detailGeneration++;libraryUI.item=null;libraryUI.candidate=null;
  $("candidates").hidden=true;$("library-empty-review").hidden=false;
  $("library-results").hidden=false;$("library-items").classList.remove("library-expanded");
  $("candidate-expand").textContent=say("Expand review","Agrandir");
  await loadLibrary();
  if(result.client_unavailable) toast(say("Files scanned. The Torrent Client is unavailable, so seeding status is unknown.","Fichiers analysés. Le client torrent est indisponible : état du seed inconnu."));
}));


async function previewArchive(candidate) {
  const body={path:libraryUI.item.path,candidate_key:candidate.key,client_id:state.clientId};
  const generation=libraryUI.generation;
  await job({kind:"preview-unpack",...body},preview=>{
    if(generation!==libraryUI.generation || libraryUI.candidate?.key!==candidate.key) return;
    const content=$("dialog-content"), dialog=$("dialog");
    content.replaceChildren(element("h2",say("Unpack and reseed","Extraire et seeder")),
      element("h3",preview.title),
      element("p",say("Extraction happens on the TorrentLinker server. The original archive is kept. Nothing is overwritten.","L’extraction a lieu sur le serveur TorrentLinker. L’archive originale est conservée. Aucun fichier n’est écrasé.")),
      element("p",say("Archive: ","Archive : ")+preview.archive,"archive-path"),
      element("p",say("Destination: ","Destination : ")+preview.destination,"archive-path"),
      element("p",say(`${preview.files} files · ${bytes(preview.size)} to unpack · ${bytes(preview.free)} available`,`${preview.files} fichiers · ${bytes(preview.size)} à extraire · ${bytes(preview.free)} disponibles`)),
      element("p",preview.match==="partial"?say(`Partial Match: ${preview.missing} missing files. Missing files will not be downloaded; the torrent stays stopped after verification.`,`Correspondance partielle : ${preview.missing} fichiers manquants. Ils ne seront pas téléchargés ; le torrent restera arrêté après vérification.`):say("The Torrent Client will verify the extracted files before seeding.","Le client torrent vérifiera les fichiers extraits avant le seed.")));
    const cancel=button(say("Cancel","Annuler"),()=>dialog.close(),"quiet");
    const approve=button(say("Unpack and reseed","Extraire et seeder"),async()=>{
      if(body.client_id!==state.clientId) {dialog.close();return;}
      approve.disabled=true;cancel.disabled=true;
      const status=element("p",say("Waiting to extract…","En attente d’extraction…"));
      status.setAttribute("role","status");
      const meter=element("progress");meter.max=preview.size;meter.value=0;
      content.append(status,meter);
      let identifier, canCancel=true;
      const showProgress=p=>{
        if(!p) return;
        meter.value=p.done;meter.max=p.total;
        canCancel=p.cancellable!==false;
        if(!canCancel) {cancel.disabled=true;status.textContent=say("Starting verification…","Démarrage de la vérification…");return;}
        status.textContent=say(`Extracting ${bytes(p.done)} / ${bytes(p.total)}`,`Extraction ${bytes(p.done)} / ${bytes(p.total)}`);
      };
      const finish=message=>{status.textContent=message;cancel.textContent=say("Close","Fermer");cancel.disabled=false;cancel.onclick=()=>dialog.close();};
      try {
        identifier=await job({kind:"unpack-reseed",...body,confirmation:preview.token},()=>{
          meter.value=preview.size;
          finish(say("Verification started. The original archive has been kept. Follow verification in Torrents.","Vérification lancée. L’archive originale est conservée. Suivez la vérification dans Torrents."));
          content.append(button(say("Open in Torrents","Ouvrir dans Torrents"),async()=>{dialog.close();await navigate("torrents");}));
          guard(()=>job({kind:"scan",client_id:body.client_id},loadLibrary));
        },error=>finish(error || say("Extraction cancelled. The original archive has been kept.","Extraction annulée. L’archive originale est conservée.")),showProgress);
        // A short extraction can complete during job()'s initial poll.
        if(state.jobs.has(identifier)) {
          cancel.disabled=!canCancel;cancel.textContent=say("Cancel extraction","Annuler l’extraction");
          cancel.onclick=()=>guard(async()=>{cancel.disabled=true;await api(`jobs/${identifier}/cancel`,{});status.textContent=say("Cancelling…","Annulation…");});
        }
      } catch(error) {finish(error.message);}
    },"primary");
    content.append(cancel,approve);dialog.showModal();cancel.focus();
  });
}
