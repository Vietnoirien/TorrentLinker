"use strict";
// Video browsing is shared with Qt; the current player and music workspace remain host-owned.
const mediaFrame = document.createElement("iframe");
mediaFrame.id="media-frame";mediaFrame.title="Media";mediaFrame.src="static/media/view.html";
mediaFrame.style.cssText="width:100%;min-height:300px;border:0;display:block";
const loadLegacyMedia=loadMedia;
let mediaRevision=0;
loadMedia=async function(append=false){
  const video=media.kind==="video";
  if(!mediaFrame.isConnected)$("view-media").append(mediaFrame);
  for(const child of $("view-media").children)if(child!==mediaFrame)child.hidden=video;
  mediaFrame.hidden=!video;
  mediaMusicBar();
  if(!video)return loadLegacyMedia(append);
  mediaRevision++;mediaEnvironment();
  if(!media.session && sessionStorage.getItem(`tl-media-session:${mediaClient()}`))await mediaSession();
};
function mediaEnvironment(){
  const active=state.view==="media"&&media.kind==="video"&&!$("workspace").hidden;
  if(active)mediaFrame.style.height=`${Math.max(300,innerHeight-mediaFrame.getBoundingClientRect().top-20)}px`;
  mediaFrame.contentWindow?.postMessage({type:"media-environment",value:{mode:"web",active,player_clearance:$("media-player-shell").hidden?0:$("media-player-shell").getBoundingClientRect().height,chat_open:media.chat,center_mode:document.body.classList.contains("media-center-mode"),revision:mediaRevision,language,theme:document.documentElement.dataset.theme||"dark",client_id:mediaClient(),adult_content:state.setup?.adult_content}},location.origin);
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
      else if(action==="music"){$("media-music-tab").click();}
      else if(action==="context")media.browseContext=values;
      else if(action==="selection")media.selected=values.selected_ids?.[0]?{id:values.selected_ids[0]}:null;
      else if(action==="chat")await mediaToggleChat();
      else if(action==="center")$("media-center-mode").click();
      else if(action==="settings")await navigate("setup");
      else throw Error("Unknown Media action");
    }else if(message.path==="preferences"){
      if(mediaLayouts.includes(message.body.layout))localStorage.setItem("tl-media-layout",message.body.layout);
      value={layout:localStorage.getItem("tl-media-layout")||"cinematic"};
    }else{
      if(!/^(media(?:\?|\/home\?|\/items\/[^/]+(?:\?|\/watched$|\/artwork\?))|media\/scan$|jobs\/[^/]+(?:\/cancel)?$)/.test(message.path))throw Error("Unknown Media operation");
      const url=new URL("api/"+message.path,document.baseURI);url.searchParams.set("client_id",mediaClient());
      const path=url.pathname.replace(/^.*\/api\//,"")+url.search;
      if(url.pathname.endsWith("/artwork")){
        const response=await fetch(url,{credentials:"same-origin"});if(!response.ok)throw Error("Artwork unavailable");
        const blob=await response.blob();if(blob.size>8*1024*1024)throw Error("Artwork too large");
        value={data_url:await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(blob)})};
      }else {
        if(url.pathname.includes("/jobs/")){
          const job=await api(`jobs/${url.pathname.split("/jobs/")[1].split("/")[0]}`);
          if(job.kind!=="media-scan"||job.client_id!==mediaClient())throw Error("This is not a Media scan for the selected client");
        }
        value=await api(path,message.body.body?{...message.body.body,client_id:mediaClient()}:undefined,message.body.method);
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
