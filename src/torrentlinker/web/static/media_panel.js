"use strict";
// Media browsing is shared with Qt; the player, its queue and the chat remain host-owned.
const mediaFrame = document.createElement("iframe");
mediaFrame.id="media-frame";mediaFrame.title="Media";mediaFrame.src="static/media/view.html";
mediaFrame.style.cssText="width:100%;min-height:300px;border:0;display:block";
let mediaRevision=0;
async function loadMedia(){
  if(!mediaFrame.isConnected)$("view-media").append(mediaFrame);
  mediaPlayerLabels();mediaMusicBar();mediaRefreshView();
  if(!media.session && sessionStorage.getItem(`tl-media-session:${mediaClient()}`))await mediaSession();
}
function mediaRefreshView(){mediaRevision++;mediaEnvironment()}
function mediaEnvironment(){
  const active=state.view==="media"&&!$("workspace").hidden;
  if(active)mediaFrame.style.height=`${Math.max(300,innerHeight-mediaFrame.getBoundingClientRect().top-20)}px`;
  // Restored queues can contain uncached tracks; the server validates every saved item.
  const music=media.queue.every(id=>{const row=mediaItems.get(id);return !row||row.kind==="music"});
  mediaFrame.contentWindow?.postMessage({type:"media-environment",value:{mode:"web",active,kind:media.kind,view:media.view,queue:[...media.queue],queue_client:media.playerClient||mediaClient(),queue_music:music,player_clearance:$("media-player-shell").hidden?0:$("media-player-shell").getBoundingClientRect().height,chat_open:media.chat,center_mode:document.body.classList.contains("media-center-mode"),revision:mediaRevision,language,theme:document.documentElement.dataset.theme||"dark",client_id:mediaClient(),adult_content:state.setup?.adult_content}},location.origin);
}
window.addEventListener("message",async event=>{
  if(event.source!==mediaFrame.contentWindow||event.origin!==location.origin)return;
  const message=event.data;
  if(message?.type==="media-ready"){mediaEnvironment();return}
  if(message?.type!=="media-request")return;
  try{
    if($("workspace").hidden)throw Error("Sign in first.");
    let value=null;
    if(message.path==="host"){
      const {action,values={}}=message.body;
      if(action==="play")await mediaStart(values.media_ids,values.index||0);
      else if(action==="preview")await mediaPreview(values.media_id);
      else if(action==="enqueue")await mediaEnqueue(values.media_ids||[]);
      else if(action==="queue")mediaShowQueue();
      else if(action==="kind"&&mediaViewsByKind[values.kind]){media.kind=values.kind;media.view=mediaViewsByKind[values.kind][0];mediaMusicBar();rememberTab("media",media.kind)}
      else if(action==="context"){
        media.browseContext=values;
        if(mediaViewsByKind[values.kind]?.includes(values.view)||values.view==="adult"){media.kind=values.kind;media.view=values.view;rememberTab("media",media.kind,media.view===mediaViewsByKind[media.kind][0]?undefined:media.view)}
      }
      else if(action==="selection")media.selected=values.selected_ids?.[0]?{id:values.selected_ids[0]}:null;
      else if(action==="chat")await mediaToggleChat();
      else if(action==="center")await mediaToggleCenter();
      else if(action==="settings")await navigate("setup");
      else throw Error("Unknown Media action");
    }else if(message.path==="preferences"){
      if(mediaLayouts.includes(message.body.layout)){
        media.layout=message.body.layout;try{localStorage.setItem("tl-media-layout",media.layout)}catch{}
        $("view-media").dataset.layout=media.layout;
      }
      value={layout:mediaLayoutValue(media.layout),horizon:mediaHorizonValue(media.horizon)};
    }else{
      if(!/^(media(?:\?|\/home\?|\/items\/[^/]+(?:\?|\/(?:watched|forget-progress)$|\/artwork\?)|\/playlists(?:$|\?|\/[^/?]+\?))|media\/scan$|jobs\/[^/]+(?:\/cancel)?$)/.test(message.path))throw Error("Unknown Media operation");
      let client=mediaClient();
      if(message.path==="media/playlists" && message.body.method==="POST"){
        const owner=media.playerClient||client;
        if(message.body.body?.id && owner!==client)throw Error(say("Choose the playing Torrent Client before replacing a playlist.","Choisissez le client Torrent en lecture avant de remplacer une playlist."));
        client=owner;
      }
      const url=new URL("api/"+message.path,document.baseURI);url.searchParams.set("client_id",client);
      const path=url.pathname.replace(/^.*\/api\//,"")+url.search;
      if(url.pathname.endsWith("/artwork")){
        value={data_url:await mediaArtworkDataURL(url)};
      }else {
        if(url.pathname.includes("/jobs/")){
          const job=await api(`jobs/${url.pathname.split("/jobs/")[1].split("/")[0]}`);
          if(job.kind!=="media-scan"||job.client_id!==mediaClient())throw Error("This is not a Media scan for the selected client");
        }
        value=await api(path,message.body.body?{...message.body.body,client_id:client}:undefined,message.body.method);
      }
    }
    mediaFrame.contentWindow?.postMessage({type:"media-response",id:message.id,value},location.origin);
  }catch(error){mediaFrame.contentWindow?.postMessage({type:"media-response",id:message.id,error:error.message},location.origin)}
});
window.addEventListener("resize",mediaEnvironment);
document.addEventListener("tl-language-changed",mediaEnvironment);
new MutationObserver(mediaEnvironment).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
new MutationObserver(mediaEnvironment).observe($("view-media"),{attributes:true,attributeFilter:["hidden"]});

window.addEventListener("media-host-changed",mediaEnvironment);

new ResizeObserver(mediaEnvironment).observe($("media-player-shell"));
