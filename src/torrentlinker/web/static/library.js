"use strict";
// Candidate inspection lives in the bundled Reseed panel. This host retains
// server folder browsing, download settings and protected archive/repair dialogs.
const libraryUI={item:null,candidate:null,generation:0,client:null};
function resetLibraryReview(){
  if(libraryUI.client===state.clientId)return;
  libraryUI.client=state.clientId;libraryUI.item=null;libraryUI.candidate=null;libraryUI.generation++;
}
async function loadLibrary(){resetLibraryReview();await loadReseed();}
async function libraryTab(tab){
  resetLibraryReview();
  tab=["folders","activity"].includes(tab)?tab:"reseed";
  rememberTab("library",tab);$("library-reseed").hidden=false;
  reseedUI.tab=tab;await loadReseed();
}
async function browseLibraryFolder(path="",target="library-folder-path") {
  const result=await api(`folders?path=${encodeURIComponent(path)}`);
  const host=$("dialog-content");host.replaceChildren(element("h2",say("Folders on the TorrentLinker server","Dossiers du serveur TorrentLinker")),element("p",result.path || say("Mounted roots","Racines montées")));
  if(result.path) {
    host.append(button(say("Use this folder","Utiliser ce dossier"),()=>{$(target).value=result.path;$("dialog").close();},"primary"));
    host.append(button("↑",()=>browseLibraryFolder(result.parent,target)));
  }
  for(const folder of result.folders) host.append(button(folder,()=>browseLibraryFolder(folder,target),"directory-button"));
  if(!result.path && !result.folders.length) host.append(element("p",say("No mounted roots. Set TL_STORAGE_ROOTS on the TorrentLinker server.","Aucune racine montée. Configurez TL_STORAGE_ROOTS sur le serveur.")));
  if(!$("dialog").open) $("dialog").showModal();
}
$("settings-library-folders").onclick=()=>guard(()=>navigate("library", "folders"));

function renderLibraryDownloads() {
  const folders=state.setup.download_folders || {default:"",by_category:{},effective:{}};
  const categories=state.setup.indexer_categories || {};
  const select=$("library-download-category"), current=select.value;
  select.replaceChildren(new Option(say("Default","Par défaut"),""));
  for(const row of categoryRows(categories)) select.add(new Option(row.path,row.id));
  select.value=current;
  select.parentElement.querySelector(".category-picker")?.remove();
  select.after(categoryPicker(select,categories));
  const sequential=$("library-sequential-video");sequential.checked=!!state.setup.sequential_video;
  sequential.onchange=()=>guard(async()=>{await api("setup/sequential-video",{enabled:sequential.checked});await refreshSetup();});
  const adult=$("library-adult-content");adult.checked=!!state.setup.adult_content;
  adult.onchange=()=>guard(async()=>{await api("setup/adult-content",{enabled:adult.checked});await refreshSetup();});
  const host=$("library-download-destinations");host.replaceChildren();
  for(const [id,path] of [["",folders.default],...Object.entries(folders.by_category)]) {
    const row=element("div",undefined,"library-folder-row");
    row.append(element("span",`${id?(categoryRows(categories).find(row=>row.id===id)?.path || id):say("Default","Par défaut")} · ${path || say("Not set","Non configuré")}`));
    row.append(button(say("Edit","Modifier"),()=>{select.value=id;select.dispatchEvent(new Event("change"));$("library-download-path").value=path;}));
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
      element("p",preview.match==="partial"?say(`Partial Match: ${preview.missing} missing files. Missing files will not be downloaded; after verification the torrent seeds the pieces you have, with every file skipped.`,`Correspondance partielle : ${preview.missing} fichiers manquants. Ils ne seront pas téléchargés ; après vérification, le torrent partage les pièces que vous avez, tous ses fichiers étant ignorés.`):say("The Torrent Client will verify the extracted files before seeding.","Le client torrent vérifiera les fichiers extraits avant le seed.")));
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

function renderRepair(host,row) {
  const card=element("section");host.append(card);
  card.append(element("h4",`${row.name} · ${evidenceLabel(row.status)}`),element("p",say("Original retained: ","Original conservé : ")+row.source),element("p",`${bytes(row.verified_bytes)} / ${bytes(row.target_bytes)} · ${say("Missing payload","Contenu manquant")} ${bytes(row.missing_bytes)}`),element("p",say("Experimental: single-file v1 torrents, 1% / 50 MiB size difference, at least 90% verified, at most 500 MiB missing and 2 advertised seeders. Source/team claims remain unverified.","Expérimental : torrents v1 d’un fichier, écart de 1 % / 50 Mio, au moins 90 % vérifiés, au plus 500 Mio manquants et 2 seeders annoncés. Les déclarations de source/team restent à vérifier.")));
  if(row.copy)card.append(element("p",row.copy));
  const update=r=>{card.remove();renderRepair(host,r);};
  if(row.eligible && row.status==="awaiting-confirmation"){
    const label=element("label",say("Server folder for the copy","Dossier du serveur pour la copie")),input=element("input");label.append(input);card.append(label);
    const optLabel=element("label"),opt=element("input");opt.type="checkbox";
    optLabel.append(opt,document.createTextNode(say("Enable experimental repair (real-library trials pending)","Activer la réparation expérimentale (essais sur des bibliothèques réelles en attente)")));card.append(optLabel);
    const prepare=button(say("Prepare independent copy","Préparer une copie indépendante"),()=>guard(async()=>{
      await job({kind:"prepare-repair",repair_id:row.id,client_path:input.value,experimental:opt.checked},update);
    }));prepare.disabled=true;opt.onchange=()=>{prepare.disabled=!opt.checked;};card.append(prepare);
  }
  if(row.copy)card.append(button(say("Refresh verification","Actualiser la vérification"),()=>guard(async()=>{
    await job({kind:"refresh-repair",repair_id:row.id},update);
  })));
  if(row.status==="ready")card.append(button(say("Confirm download into copy…","Confirmer le téléchargement dans la copie…"),()=>guard(async()=>{
    if(!confirm(say(`Download missing content into ${row.copy}? The original is retained. Network traffic may exceed the estimate.`,`Télécharger le contenu manquant dans ${row.copy} ? L’original est conservé. Le trafic réseau peut dépasser l’estimation.`)))return;
    await job({kind:"start-repair",repair_id:row.id,confirmation:row.id},update);
  })));
}

function evidenceLabel(value) {
  const labels={filename:["Filename","Nom du fichier"],"embedded-title":["Embedded title","Titre intégré"],"writing-application":["Writing application","Application d’écriture"],resolution:["Resolution","Résolution"],"video-codec":["Video codec","Codec vidéo"],"audio-codec":["Audio codec","Codec audio"],"audio-channels":["Audio channels","Canaux audio"],processing:["Processing clue","Indice de traitement"],measured:["Measured contradiction","Contradiction mesurée"],hint:["Clue only","Simple indice"],review:["Review needed","À examiner"],verified:["Hash verified","Hashes vérifiés"],unverified:["Unverified","Non vérifié"],ambiguous:["Ambiguous","Ambigu"],partial:["Partially verified","Partiellement vérifié"],stale:["File changed; verify again","Fichier modifié ; vérifier à nouveau"],"awaiting-confirmation":["Copy not prepared","Copie à préparer"],ineligible:["Outside repair limits","Hors des limites de réparation"],preparing:["Preparing copy","Préparation de la copie"],adding:["Addition pending; inspect client","Ajout en cours ; inspecter le client"],checking:["Client verification","Vérification par le client"],ready:["Ready for confirmation","Prêt pour confirmation"],"needs-review":["Inspect the client before retrying","Inspecter le client avant de réessayer"],starting:["Start uncertain; inspect client","Démarrage incertain ; inspecter le client"],downloading:["Downloading into copy","Téléchargement dans la copie"],completed:["Completed","Terminé"]};
  return labels[value]?say(...labels[value]):value;
}
