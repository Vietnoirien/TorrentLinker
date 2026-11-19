"use strict";
const mediaExternalURL=id=>new URL(`../../api/media/items/${encodeURIComponent(id)}/stream?${mediaQuery({})}`,location.href).href;
const mediaStart=async(ids,index=0)=>host("play",{media_ids:await ids,index});
const mediaPreview=id=>host("preview",{media_id:id});
const mediaToggleChat=()=>host("chat",{selected_ids:media.selected?[media.selected.id]:[]});
function mediaSelectionChanged(row){
  guard(async()=>{
    await host("context",{view:media.view,q:$("media-search").value,...Object.fromEntries(["genre","year","language","availability"].map(key=>[key,$(`media-${key}`).value]))});
    await host("selection",{selected_ids:row?[row.id]:[]});
  });
}
$("media-music-tab").onclick=()=>guard(()=>host("music"));
$("media-video-tab").onclick=()=>guard(async()=>{media.view="recent";media.gridMode=false;mediaViews();await loadMedia()});
$("media-toolbar-chat").onclick=()=>guard(mediaToggleChat);
$("media-toolbar-chat").title=say("Assistant","Assistant");
$("media-center-mode").onclick=()=>guard(()=>host("center"));
$("media-center-mode").title=say("Media Center mode","Mode Media Center");
$("media-layout-switch").onchange=event=>mediaSetLayout(event.target.value);
for(const node of document.querySelectorAll("[data-view=setup]"))node.onclick=()=>guard(navigate);
for(const node of document.querySelectorAll("[data-media-view]"))node.onclick=()=>guard(async()=>{
  media.gridMode=false;media.animeFilters={};
  for(const key of ["genre","year","language","availability"])$(`media-${key}`).value="";
  media.view=node.dataset.mediaView;$("media-view").value=media.view;await loadMedia();
});
$("media-view").onchange=()=>guard(async()=>{media.view=$("media-view").value;await loadMedia()});
for(const key of ["genre","year","language","availability"])$(`media-${key}`).onchange=()=>guard(loadMedia);
let searchTimer;
$("media-search").oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>guard(loadMedia),250)};
$("media-more").onclick=()=>guard(()=>loadMedia(true));
async function mediaScan(){
  const result=await api("media/scan",{client_id:state.clientId});media.scan=result.id;mediaStatus(say("Scanning Library Folders…","Analyse des dossiers…"));
  $("media-toolbar-refresh").setAttribute("aria-pressed","true");
}
async function refreshOrCancel(){if(media.scan)await api(`jobs/${encodeURIComponent(media.scan)}/cancel`,{});else await mediaScan()}
$("media-refresh").onclick=()=>guard(refreshOrCancel);
$("media-toolbar-refresh").onclick=()=>guard(refreshOrCancel);
$("media-toolbar-refresh").title=say("Refresh library","Actualiser la médiathèque");
$("media-cancel-scan").onclick=()=>guard(refreshOrCancel);
setInterval(()=>{if(!media.scan)return;guard(async()=>{
  const job=await api(`jobs/${encodeURIComponent(media.scan)}`);
  if(["queued","running"].includes(job.status))return;
  media.scan="";$("media-toolbar-refresh").setAttribute("aria-pressed","false");await loadMedia();if(job.error)toast(job.error);
})},1000);
$("media-details").addEventListener("click",event=>{if(event.target!==event.currentTarget)return;const box=event.target.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)event.target.close()});
document.addEventListener("keydown",event=>{
  const card=event.target.closest(".media-row-card,.media-focus-choice");if(!card)return;
  const direction={ArrowLeft:-1,ArrowRight:1}[event.key];
  if(direction){event.preventDefault();const cards=[...card.parentElement.querySelectorAll("button")];cards[(cards.indexOf(card)+direction+cards.length)%cards.length]?.focus()}
});

const moreObserver=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)&&media.next&&!media.loadingMore){media.loadingMore=true;guard(()=>loadMedia(true)).finally(()=>media.loadingMore=false)}},{rootMargin:"200px"});
moreObserver.observe($("media-more"));
document.addEventListener("keydown",event=>{
  if(!["ArrowUp","ArrowDown"].includes(event.key))return;
  const card=event.target.closest(".media-row-card"),row=card?.closest(".media-home-row");if(!row)return;
  const rows=[...document.querySelectorAll(".media-home-row")];
  const next=rows[rows.indexOf(row)+(event.key==="ArrowDown"?1:-1)];
  if(next){event.preventDefault();const index=[...row.querySelectorAll(".media-row-card")].indexOf(card),cards=next.querySelectorAll(".media-row-card");cards[Math.min(index,cards.length-1)]?.focus()}
});

document.addEventListener("keydown",event=>{if(event.key==="Escape"&&environment.center_mode&&!$("media-details").open)guard(()=>host("center"))});

// Announce readiness only after the browsing state and event handlers exist.
TLPanel.connect("media",{asynchronous:true}).then(request=>{panelRequest=request;window.mediaReady()});
