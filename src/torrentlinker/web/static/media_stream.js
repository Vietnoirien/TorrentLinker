"use strict";
// The host owns source changes; the shared view only sends source-bound commands.
const mediaStreams = new WeakMap();
const mediaPlaybackFacts = new Map();
let mediaQuality = "original", mediaAudioChoice = 0, mediaSwitching = false;
// The last quality chosen on this device opens the next film; failing that, the best allowed one.
const mediaQualityKey = "torrentlinker.quality";
let mediaQualityChosen = "";
try { mediaQualityChosen = localStorage.getItem(mediaQualityKey) || ""; } catch { /* nothing remembered */ }
function mediaQualityRemember(quality) {
  mediaQualityChosen = quality;
  try { localStorage.setItem(mediaQualityKey, quality); } catch { /* not remembered */ }
}
// What this device decodes, probed once per browser version, and what playing taught it since:
// a probe can say yes to what the device then fails to show (HEVC without the hardware, Matroska
// "maybe"), so a failure is remembered for files made the same way.
const mediaDecodeKey = "torrentlinker.decode", mediaDecodeVersion = 1;
const mediaDecodeForget = 30 * 86400 * 1000; // a failure is tried again after a month
const mediaDecodeTypes = {
  video: {
    h264: 'video/mp4; codecs="avc1.640028"', h264_10: 'video/mp4; codecs="avc1.6E0028"',
    hevc: 'video/mp4; codecs="hvc1.1.6.L150.90"', hevc_10: 'video/mp4; codecs="hvc1.2.4.L150.90"',
    av1: 'video/mp4; codecs="av01.0.08M.08"', av1_10: 'video/mp4; codecs="av01.0.08M.10"',
    vp9: 'video/webm; codecs="vp09.00.40.08"', vp9_10: 'video/mp4; codecs="vp09.02.40.10"', vp8: 'video/webm; codecs="vp8"',
  },
  audio: {
    aac: 'audio/mp4; codecs="mp4a.40.2"', mp3: "audio/mpeg", ac3: 'audio/mp4; codecs="ac-3"',
    eac3: 'audio/mp4; codecs="ec-3"', opus: 'audio/webm; codecs="opus"', vorbis: 'audio/webm; codecs="vorbis"',
    flac: "audio/flac",
  },
  container: {mp4: "video/mp4", matroska: "video/x-matroska", webm: "video/webm", ogg: "video/ogg"},
};
let mediaDecode = null;
function mediaDecodeSave() {
  try { localStorage.setItem(mediaDecodeKey, JSON.stringify(mediaDecode)); } catch { /* probed again next time */ }
}
function mediaDecodeProfile() {
  const agent = globalThis.navigator?.userAgent || "";
  if (mediaDecode?.agent === agent) return mediaDecode;
  try { mediaDecode = JSON.parse(localStorage.getItem(mediaDecodeKey) || "null"); } catch { mediaDecode = null; }
  if (mediaDecode?.version === mediaDecodeVersion && mediaDecode.agent === agent) return mediaDecode;
  const probe = document.createElement("video");
  const plays = type => probe.canPlayType(type) !== "" || mediaStreamReads(type);
  mediaDecode = {version: mediaDecodeVersion, agent, learned: {}};
  for (const [kind, types] of Object.entries(mediaDecodeTypes))
    mediaDecode[kind] = Object.fromEntries(Object.entries(types).map(([name, type]) => [name, plays(type)]));
  mediaDecodeSave();
  mediaDecodeRefine(mediaDecode);
  return mediaDecode;
}
// A picture the browser names but cannot decode at 1080p (no hardware for it) is a no.
async function mediaDecodeRefine(profile) {
  if (!globalThis.navigator?.mediaCapabilities) return;
  for (const [name, type] of Object.entries(mediaDecodeTypes.video)) {
    if (!profile.video[name]) continue;
    try {
      const info = await navigator.mediaCapabilities.decodingInfo({type: "file", video: {contentType: type, width: 1920, height: 1080, bitrate: 8000000, framerate: 24}});
      if (!info.supported) profile.video[name] = false;
    } catch { /* the probe stands */ }
  }
  if (mediaDecode === profile) mediaDecodeSave();
}
function mediaPictureName(facts) {
  return facts?.video_codec ? `${facts.video_codec}${(facts.bit_depth || 8) > 8 ? "_10" : ""}` : "";
}
// How a file is made, as far as playing it is concerned: what a success or failure is remembered by.
function mediaDecodeSignature(facts, quality) {
  if (quality === "sound") return `sound:${mediaPictureName(facts)}`;
  return `original:${facts?.container || ""}/${mediaPictureName(facts)}/${facts?.audio?.[mediaAudioChoice]?.codec || ""}`;
}
function mediaDecodeLearned(facts, quality) {
  const found = mediaDecodeProfile().learned[mediaDecodeSignature(facts, quality)];
  if (!found || (!found.ok && Date.now() - found.at > mediaDecodeForget)) return undefined;
  return found.ok;
}
// Only what the device decodes as it is is learned: a picture with converted sound or an original.
function mediaDecodeLearn(facts, quality, ok) {
  if (!facts?.video_codec || !["original", "sound"].includes(quality)) return;
  const profile = mediaDecodeProfile();
  profile.learned[mediaDecodeSignature(facts, quality)] = {ok, at: Date.now()};
  mediaDecodeSave();
}
// Whether this device plays a sound codec as FFprobe names it. An unknown one is tried as it is:
// a failure still falls back.
function mediaSoundPlayable(codec) {
  const known = mediaDecodeProfile().audio[codec];
  if (known !== undefined) return known;
  return !["dts", "truehd", "mlp"].includes(codec) && !String(codec).startsWith("pcm_");
}
// Whether this device shows the picture as it is; an unknown codec (MPEG-2, VC-1…) is converted.
function mediaPicturePlayable(facts) {
  if (!facts?.video_codec) return true;
  return Boolean(mediaDecodeProfile().video[mediaPictureName(facts)]);
}
function mediaContainerPlayable(facts) {
  if (!facts?.container) return true;
  return Boolean(mediaDecodeProfile().container[facts.container]);
}
// The picture is copied when this browser reads it as a stream, else the whole film is converted.
function mediaPictureCopies(facts) {
  if (!facts?.sound || !mediaPicturePlayable(facts)) return false;
  const learned = mediaDecodeLearned(facts, "sound");
  if (learned !== undefined) return learned;
  return facts.video_codec !== "hevc" || mediaStreamReads(mediaStreamType(facts, "sound"));
}
function mediaQualityStart(facts) {
  const allowed = facts?.qualities || ["original"];
  const chosen = allowed.includes(mediaQualityChosen) ? mediaQualityChosen : allowed.includes("original") ? "original" : allowed[allowed.length - 1] || "original";
  if (chosen !== "original" || !facts?.available) return chosen;
  // The original plays when this device decodes all of it and never failed on a file made the same way.
  const sound = facts.audio?.[mediaAudioChoice]?.codec;
  const learned = mediaDecodeLearned(facts, "original");
  const whole = learned ?? (mediaContainerPlayable(facts) && (!sound || mediaSoundPlayable(sound)));
  if (mediaPicturePlayable(facts) && whole) return "original";
  // A picture it shows is kept; only the sound (and the container) is converted.
  if (mediaPictureCopies(facts)) return "sound";
  return "source";
}
// Whether a quality is a conversion these facts offer: a preset, the film's own resolution, or its
// picture with converted sound.
function mediaQualityConverted(facts, quality) {
  if (quality === "source") return Boolean(facts?.available);
  if (quality === "sound") return Boolean(facts?.sound);
  return quality !== "original" && (facts?.qualities || []).includes(quality);
}
// The stream type the browser is given: a copied HEVC picture, else the H.264 every conversion makes.
function mediaStreamType(facts, quality) {
  if (quality === "sound" && facts?.video_codec === "hevc") return `video/mp4; codecs="hvc1.${(facts.bit_depth || 8) > 8 ? "2.4" : "1.6"}.L150.90,mp4a.40.2"`;
  return `video/mp4; codecs="avc1.${(facts?.height || 0) > 1080 ? "640033" : "640028"},mp4a.40.2"`;
}
function mediaStreamReads(type) {
  return typeof MediaSource !== "undefined" && MediaSource.isTypeSupported(type);
}
// The best transcoded quality strictly below `than`: below the film's own height for "source",
// below everything for the original.
// What to try when the current source cannot play: nothing while a switch is under way (it reports
// its own failure).
// The resolution is never lowered by itself: an original that cannot play keeps its picture with
// converted sound, else is converted at its own resolution (only a Member's limit lowers that).
// A conversion that fails is reported, not replaced by a smaller one.
function mediaQualityFallback(facts, current, switching) {
  if (switching) return "";
  if (current === "original" && mediaPictureCopies(facts)) return "sound";
  if (["original", "sound"].includes(current) && facts?.available) return "source";
  return "";
}
// An original playing without sound (a codec the browser opens but cannot decode raises no
// error) is switched to its picture with converted sound, or else converted whole.
function mediaSilentSwitch(player, facts) {
  if (player.paused || player.dataset.streamOffset || !facts?.audio?.length) return "";
  const silent = player.webkitAudioDecodedByteCount === 0 || player.mozHasAudio === false;
  if (!silent) return "";
  return facts.sound ? "sound" : facts.available ? "source" : "";
}
function mediaFilmPosition(player) { return (player.currentTime || 0) + Number(player.dataset.streamOffset || 0); }
function mediaFilmDuration(player) {
  return player.dataset.streamOffset ? Number(mediaItems.get(player.dataset.mediaId)?.duration || mediaPlaybackFacts.get(player.dataset.mediaId)?.duration || 0) : (Number.isFinite(player.duration) && player.duration > 0 ? player.duration : Number(mediaItems.get(player.dataset.mediaId)?.duration || mediaPlaybackFacts.get(player.dataset.mediaId)?.duration || 0));
}
async function mediaStreamStop(player) {
  const stream = mediaStreams.get(player);
  if (!stream) return;
  mediaStreams.delete(player); stream.abort.abort();
  if (stream.objectURL) URL.revokeObjectURL(stream.objectURL);
  await api(stream.cancel, undefined, "DELETE").catch(() => {});
}
function mediaStreamError(player, stream, error) {
  if (stream.abort.signal.aborted || mediaStreams.get(player) !== stream) return;
  stream.abort.abort();
  api(stream.cancel, undefined, "DELETE").catch(() => {});
  // An original whose stream fails is retried converted at its own resolution; a conversion that
  // fails is shown.
  const lower = mediaQualityFallback(mediaPlaybackFacts.get(player.dataset.mediaId), mediaQuality, mediaSwitching);
  if (lower) { mediaChangeQuality({quality:lower}).catch(() => mediaCodecShow(error.message)); return; }
  $("media-codec-message").textContent = error.message || say("Compatible playback failed.", "La lecture compatible a échoué.");
  $("media-codec-error").hidden = false;
  mediaPlayerEnvironment();
}
function mediaWait(target, event, signal) {
  return new Promise((resolve, reject) => {
    const clean = () => {target.removeEventListener(event, done); target.removeEventListener("error", failed); signal.removeEventListener("abort", failed);};
    const done = () => {clean(); resolve();};
    const failed = () => {clean(); reject(signal.aborted ? new DOMException("Cancelled", "AbortError") : Error("Video stream failed."));};
    if (signal.aborted) {failed(); return;}
    target.addEventListener(event, done, {once: true}); target.addEventListener("error", failed, {once: true}); signal.addEventListener("abort", failed, {once: true});
  });
}
function mediaStreamLoad(player, id, start) {
  const playbackId = mediaNewSourceToken(), client = media.playerClient || mediaClient();
  const base = `media/items/${encodeURIComponent(id)}/playback`;
  const query = new URLSearchParams({client_id:client, playback_id:playbackId, quality:mediaQuality, start, audio:mediaAudioChoice});
  const url = new URL(`api/${base}/stream?${query}`,location.href).href;
  const stream = {abort:new AbortController(), cancel:`${base}/${playbackId}?${new URLSearchParams({client_id:client})}`, objectURL:null};
  mediaStreams.set(player,stream);
  player.dataset.streamOffset=String(start); player.dataset.streamQuality=mediaQuality;
  const mime=mediaStreamType(mediaPlaybackFacts.get(id), mediaQuality);
  if (!window.MediaSource || !MediaSource.isTypeSupported(mime)) {
    player.src=url; player.load(); return;
  }
  const source=new MediaSource(), signal=stream.abort.signal;
  const opened=mediaWait(source,"sourceopen",signal);
  stream.objectURL=URL.createObjectURL(source); player.src=stream.objectURL; player.load();
  (async()=>{
    await opened;
    const buffer=source.addSourceBuffer(mime);
    const response=await fetch(url,{signal});
    if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(detail||`Playback failed (${response.status}).`);}
    const reader=response.body.getReader();
    try {
      while(!signal.aborted){
        while(buffer.buffered.length && buffer.buffered.end(buffer.buffered.length-1)-player.currentTime>120)await mediaWait(player,"timeupdate",signal);
        if(player.currentTime>60 && buffer.buffered.length && buffer.buffered.start(0)<player.currentTime-60){const removed=mediaWait(buffer,"updateend",signal);buffer.remove(0,player.currentTime-30);await removed;}
        const {done,value}=await reader.read();if(done)break;
        const appended=mediaWait(buffer,"updateend",signal);buffer.appendBuffer(value);await appended;
        mediaPlayerEnvironment();
      }
      if(!signal.aborted&&source.readyState==="open")source.endOfStream();
    } finally {await reader.cancel().catch(()=>{});}
  })().catch(error=>mediaStreamError(player,stream,error));
}
async function mediaChangeQuality(values={}) {
  if(mediaSwitching)throw Error(say("Playback is changing. Please wait.","Le lecteur change de source. Patientez."));
  const player=mediaPlayer(), id=player.dataset.mediaId, facts=mediaPlaybackFacts.get(id);
  const quality=values.quality ?? mediaQuality;
  if(!id || media.preview || !(quality==="original"?(facts?.qualities||["original"]).includes(quality):mediaQualityConverted(facts,quality)))throw Error(say("Quality unavailable.","Qualité indisponible."));
  if(values.audio!==undefined && !facts.audio.some(track=>track.id===values.audio))throw Error("Audio track unavailable.");
  const paused=player.paused, rate=player.playbackRate, source=player.dataset.sourceToken;
  const start=Math.max(0, Math.min((facts?.duration || mediaFilmDuration(player))-0.1,values.position ?? mediaFilmPosition(player)));
  mediaSwitching=true;
  try {
    await mediaStreamStop(player);
    if(player.dataset.sourceToken!==source)return;
    player.pause(); player.removeAttribute("src");player.load();
    mediaQuality=quality; if(values.audio!==undefined)mediaAudioChoice=values.audio;
    player.dataset.sourceToken=mediaNewSourceToken(); media.trackResult=null;
    $("media-codec-error").hidden=true;
    player.onloadedmetadata=()=>{if(quality==="original")player.currentTime=start;};
    if(quality==="original"){delete player.dataset.streamOffset;delete player.dataset.streamQuality;player.src=mediaURL(id);player.load();}
    else mediaStreamLoad(player,id,start);
    mediaPositionCaptions();
    player.defaultPlaybackRate=rate;player.playbackRate=rate;
    if(!paused)await mediaTryPlay(player);
    mediaPlayerEnvironment();
  } finally {mediaSwitching=false;}
}
async function mediaSeek(position) {
  const player=mediaPlayer();
  if(!player.dataset.streamOffset){player.currentTime=Math.max(0,Math.min(mediaFilmDuration(player),position));return;}
  const local=position-Number(player.dataset.streamOffset);
  for(let i=0;i<player.buffered.length;i++)if(local>=player.buffered.start(i)&&local<=player.buffered.end(i)){player.currentTime=local;return;}
  await mediaChangeQuality({position});
}
