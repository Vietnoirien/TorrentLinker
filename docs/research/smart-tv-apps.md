# How Plex reaches smart TVs, and what Médias would need

Researched 2026-11-23. Question: Plex ships a client on every TV platform; what would it take for TorrentLinker's Médias player (a web app served by the owner's own server, see [media.md](../guide/en/media.md)) to be installable on smart TVs the same way?

Evidence labels: **[doc]** stated by the vendor's own page I read; **[search]** seen only in a search-result excerpt, not the full page; **[inference]** my reasoning, not a vendor statement; **[not found]** I could not find a primary source. Several vendor pages (Plex support, developer.roku.com, Amazon, Apple's membership page) returned 403/404 to my fetcher, so some points rest on search excerpts of those pages.

## What Médias is today (repo facts)

- Browser player: HTML `<video>`/`<audio>` over ranged HTTP, cookie authentication plus CSRF on mutations ([media-center.md](media-center.md)). Optional FFmpeg transcode to H.264/AAC at 360p to 1080p ([media.md](../guide/en/media.md)).
- Sign-in is a single Web UI password or a reverse proxy; there is no central account ([web-docker.md](../guide/en/web-docker.md)). The default bind is host-only; remote use is meant to sit behind an HTTPS reverse proxy.
- A "Media Center mode" exists (fullscreen, navigation hidden), but nothing in the docs says the UI is operable with a D-pad alone. [not found in repo docs]

## How Plex does it

Plex ships a separate native or store-published client per platform and keeps them signed in through plex.tv.

- Roku: standard app from the Roku Channel Store. Fire TV: the standard Android app from the Amazon Appstore. Android TV / Google TV: the regular Android app from Google Play. [Plex supported platforms and smart TV pages, search excerpts](https://support.plex.tv/articles/204080173-which-smart-tv-models-are-supported/)
- Apple TV: Plex's iOS page lists Apple TV 4th generation and Apple TV 4K. [search]
- Samsung, LG: Plex lists them as smart-TV brands with minimum models/OS versions; the old LG NetCast/webOS 1-2 apps are no longer supported. Plex also says most Samsung models lack the root certificates needed for secure connections to a personal server. [search of the supported-models article](https://support.plex.tv/articles/204080173-which-smart-tv-models-are-supported/) Whether Plex's TV apps come from a store listing or a manufacturer partnership is **[not found]**; I will not claim either.
- Sign-in: big-screen apps show a 4-character code; the user opens [plex.tv/link](https://www.plex.tv/link/) on a phone or computer, signs in, enters the code, and the TV app links itself within seconds. [Plex: connect app to your account, via search excerpt](https://support.plex.tv/articles/203395277-connect-app-to-your-plex-account/) The code is brokered by plex.tv, which also knows where the user's servers are. That central account and server directory is exactly what a self-hosted TorrentLinker lacks.

## Per platform

### Samsung Tizen
- Format: web app `.wgt` built in Tizen Studio; manifest `config.xml`, author and distributor signatures. Only packaged files are accepted. [doc](https://developer.samsung.com/tv-seller-office/guides/applications/registering-application.html)
- Publishing: Seller Office membership with a Samsung account; no fee mentioned on the pages I read. A new member is a Public Seller and can launch in the US only; wider launch needs an offline partner contract. [doc](https://developer.samsung.com/tv-seller-office/guides/membership/becoming-seller-office-member.html) Automated pre-test, then certification; a version may be rejected per model group. [doc](https://developer.samsung.com/tv-seller-office/guides/applications/registering-application.html)
- Hosted web app (`<content src="https://...">` in `config.xml`): Samsung's FAQ says hosted apps are "not allowed to submit due to security policy" except special cases agreed in advance with a Content Manager, require partner-group membership, get no Tizen APIs, and external scripts need Content Manager permission. [doc](https://developer.samsung.com/smarttv/develop/faq/hosted-applications.html) So a store listing of an app pointing at a user-chosen server URL is effectively closed to a public seller. A packaged app that fetches the server URL at runtime (and wraps the UI inside the package) is not addressed by that FAQ. [inference]
- Sideload (single owner): TV Developer mode (Apps panel, enter 12345, set the host PC's IP), Tizen Studio Device Manager, certificate profile; USB install is no longer supported. [doc](https://developer.samsung.com/smarttv/develop/getting-started/using-sdk/tv-device.html) The distributor certificate is tied to the TV's DUID. Certificate expiry for TV is unconfirmed: I found no official figure. [search] Precedent: [jellyfin-tizen](https://github.com/jellyfin/jellyfin-tizen) is installed this way.
- Input/codecs: TV remote with D-pad; Plex states 4K only on 2016+ Tizen models. [search] Model-specific codec matrix not checked.

### LG webOS
- Format: `.ipk` built with `ares-package`. Plain web tech (HTML/CSS/JS). [search](https://webostv.developer.lge.com/develop/getting-started/web-app-types)
- Hosted web app is an official app type: a local dummy package whose `index.html` redirects to a remote server (`ares-generate -t hosted_webapp`). LG notes you run the server and performance depends on the connection; the page says nothing on store approval differences for hosted apps. [doc](https://webostv.developer.lge.com/develop/getting-started/web-app-types)
- Publishing: LG Seller Lounge (same LG account as the developer site; individual or corporate seller). Submission needs the IPK, images, a UX scenario document and a mandatory self-checklist; LG QA runs pretest, function test and content test; every update needs a new approval. Fees: **[not found]**. [doc](https://webostv.developer.lge.com/distribute/app-approval-process), [search](https://webostv.developer.lge.com/distribute/app-approval-process)
- Sideload: Developer Mode app on the TV, add the TV with `ares-setup-device`, fetch the key from the TV's Key Server, then `ares-install`. The mode runs for a limited session (shown as "Remain Session"; extendable via EXTEND until it runs out); it is disabled after ten reboots without network, or a reboot after expiry, and then the dev-installed apps are removed. [doc](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app) Community guides cite a 50-hour cycle; the page I read does not give the number. [search] Precedent: [jellyfin-webos](https://github.com/sbou88/jellyfin-webos).
- Best technical fit of the TV platforms: hosted app is supported by design.

### Android TV / Google TV
- Format: AAB on Google Play (mandatory for TV apps), APK for sideload. Needs the leanback launcher intent, a 320x180 banner, touchscreen declared not required, minSdk 31 or lower; from 2026-08-01 64-bit and 16 KB page size. [doc](https://developer.android.com/distribute/essentials/quality/tv)
- Account: Google Play Console, US$25 one-time, identity verification; personal accounts have extra testing requirements before release. [doc](https://support.google.com/googleplay/android-developer/answer/6112435)
- Web content: the TV quality criteria say web content must use `WebView` and must not launch a browser app. [doc](https://developer.android.com/distribute/essentials/quality/tv) A WebView wrapper pointing at a user-set URL is therefore the standard shape; Trusted Web Activity support on TV is **[not found]**.
- Navigation: must be fully operable with D-pad, Back, Home; center button toggles play/pause, left/right seek, Back returns to the home screen. [doc](https://developer.android.com/distribute/essentials/quality/tv)
- Reviewers get login credentials via Play Console (TV-G5), which for a self-hosted server means shipping a demo server. [doc](https://developer.android.com/distribute/essentials/quality/tv)
- Sideload: enable developer options and install an APK by adb or file manager; no expiry. [inference from general Android behaviour; not re-verified here]
- Codecs: ExoPlayer/Media3 supports many more containers than a TV browser; a WebView inherits the system WebView's codecs. [inference]

### Amazon Fire TV
- Plex uses its standard Android app from the Amazon Appstore. [search of Plex's support page](https://support.plex.tv/articles/204080173-which-smart-tv-models-are-supported/) Fire OS apps are Android APKs; newer Fire TV devices use Vega OS with a `VPKG` binary submitted through the same Developer Console. [search](https://developer.amazon.com/docs/vega/2.0/app-submission)
- Web app options, Appstore fees, and review rules: **[not found]** (my fetch of Amazon's web-app page returned 404). A WebView-based Android APK is the plausible route [inference]; Vega OS support for such an app was not checked.
- Sideload: Developer Options (Settings, My Fire TV, About, then Back to reveal Developer Options) or Developer Mode with an Amazon developer account; non-`com.amazon` packages only. [search](https://developer.amazon.com/docs/vega/0.22/developer-mode)

### Roku
- Plex: Roku Channel Store app. [search]
- Stack: BrightScript and SceneGraph; there is **no browser or WebView**. [search of developer docs; I did not find a first-party page stating this verbatim] A hosted web app is impossible; Médias would need a native rewrite of the browsing UI against its HTTP API. Video: MP4/MOV/M4V/MKV, HLS and DASH preferred. [search](https://developer.roku.com/dev/docs/media)
- Publishing: developer account; certification criteria apply; publishing reported free by a third party; Roku says a physical device must be registered. [search](https://developer.roku.com/dev/docs/certification)
- Sideload: put the Roku in developer mode with a remote button sequence, upload a zip through the device's web installer; no store needed. [search](https://developer.roku.com/dev/docs/developer-setup) Limits (channel slots, expiry): **[not found]**. Also: private (non-certified) channels exist. [search](https://sdkdocs-archive.roku.com/Non-Certified-Channels_4265529.html)

### Apple TV (tvOS)
- Plex: App Store app. [search]
- Publishing: Apple Developer Program, US$99 per year; free accounts install to own devices with profiles that expire after 7 days. [search](https://developer.apple.com/support/compare-memberships) TestFlight and limited-device distribution exist for tvOS under the program license. [search]
- Web: tvOS has no public WebView; community sources say so, one 2021 Apple forum thread states it. I could not find an Apple primary page saying so, treat as **[probable, not primary-verified]**. A tvOS app would be native (SwiftUI + AVPlayer), not a wrapper. [search](https://developer.apple.com/forums/thread/849373)
- Review: App Store guideline 4.2 rejects apps that are mere repackaged websites; 5.2.3 forbids facilitating illegal file sharing; 4.7 allows HTML5 mini apps under conditions. [doc](https://developer.apple.com/app-store/review/guidelines/) tvOS usable with the Siri remote only (2.4.3). [doc]

### Casting and DLNA (alternatives)
- Google Cast: Default Media Receiver needs no registration; a Custom Receiver (your own web page on the Chromecast) needs a registered app ID, a one-time US$5 fee and device registration for testing. [search](https://developers.google.com/cast/docs/registration) The sender can be the Médias web page in Chrome. The Cast device fetches the stream itself and has no session cookie, so streams would need short-lived signed URLs or a reachable unauthenticated path. [inference] A Chromecast with Google TV also runs Android TV apps.
- AirPlay: Safari/iOS can send a `<video>` to an Apple TV or AirPlay-capable TV natively, with the same cookie problem. [not verified against Apple docs]
- DLNA/UPnP: would need a DLNA media-server component; TorrentLinker has none. [inference; not researched against the spec]

## Comparison

| Platform | Plex reaches it via | Hosted web app allowed? | Account and cost | Package | Single-owner sideload | Main limit for Médias |
| --- | --- | --- | --- | --- | --- | --- |
| Samsung Tizen | Smart-TV app (mechanism not found); Samsung secure-connection caveat | Store: generally no, partner group and Content Manager exception | Seller Office; no fee seen; US-only for public sellers | `.wgt` | Dev mode + certificate profile, DUID-bound | Store hostile to a user-URL app; D-pad UI |
| LG webOS | Smart-TV app (mechanism not found) | Yes, official "hosted web app" type | Seller Lounge; fee not found; UX doc, checklist, QA per version | `.ipk` | Dev Mode app, time-limited session, apps removed at expiry | QA review and per-update approval |
| Android TV / Google TV | Google Play | WebView allowed; TWA on TV not found | Play Console US$25 once | AAB / APK | Developer options + adb, no expiry (general knowledge) | Review needs test login; D-pad UI |
| Fire TV | Amazon Appstore (Android app) | Not found | Not found | APK (Fire OS) / VPKG (Vega) | Developer Options + adb | Web-app rules not verified |
| Roku | Channel Store | No (BrightScript/SceneGraph) | Free per third party; device registered | Zip channel | Dev mode, web installer | Native rewrite |
| Apple TV | App Store | No public WebView; 4.2 rejects wrapped sites | US$99 per year | App via Xcode | Free profile, 7-day expiry | Native rewrite; 5.2.3 |
| Google Cast | Cast receiver | Receiver is a web page | US$5 once (custom receiver) | URL | Device registered for testing | Auth on stream URLs |
| AirPlay / DLNA | System feature | n/a | none | n/a | n/a | Same auth caveat; DLNA needs a server |

## Server discovery and sign-in on a TV

Plex's link code works because plex.tv is the broker: TV asks plex.tv for a code, user authenticates elsewhere, plex.tv hands back a token and the list of servers. TorrentLinker has no such broker, so the pattern does not transfer as is. Workable alternatives, all [inference]:

1. Type the server URL once with the remote (poor on D-pad, but only once), then show a pairing code on the TV that the owner approves from a signed-in Médias session in a phone browser. This reuses the existing session-token idea in [media-center.md](media-center.md) and avoids typing a password.
2. Local-network discovery (mDNS/SSDP): not available to a hosted web page in a TV browser; possible in a native wrapper (Android TV, webOS service, Tizen) at extra effort.
3. QR code on the TV that opens the server's URL on the phone; fine for sign-in, not for server discovery.

TV remotes have no practical keyboard, and plain-HTTP LAN servers can be blocked or warned on by TV runtimes; Plex itself documents certificate trouble on Samsung TVs. A trusted-HTTPS hostname for the server is the safest assumption. [inference]

## Store-review points for a private-tracker-adjacent app

Factual rules only; none of these pages mentions private trackers, and I have no evidence of how any store treats such an app.

- Apple 5.2.3: apps "should not facilitate illegal file sharing"; 5.2.1/5.2.2 on third-party material and services; 4.2 on repackaged websites. [doc](https://developer.apple.com/app-store/review/guidelines/)
- Google Play and Android TV: apps must follow the Play Developer Policy Center (TV-G2); the app listing must match what the app does, and reviewers must be given working login credentials (TV-G3, TV-G5). Google's Deceptive Behavior policy bans misleading claims and hidden or undocumented features, and bans behaving differently for reviewers. [doc](https://developer.android.com/distribute/essentials/quality/tv), [doc](https://support.google.com/googleplay/android-developer/answer/9888077)
- Samsung: banned and partner-only APIs, no residential-proxy SDKs, hosted apps restricted. [doc](https://developer.samsung.com/tv-seller-office/guides/applications/registering-application.html)
- LG: a content test checks for inappropriate content. [doc](https://webostv.developer.lge.com/distribute/app-approval-process)
- Practical consequence [inference]: a player that only plays the owner's own local files and ships without tracker features is the lowest-risk presentation. The tracker, search, Reseed, and Zen screens of TorrentLinker are separate and should not be reachable from a TV build. The review credential requirement means a store submission would need a public demo server.

## Cheapest path for TorrentLinker (ranked by effort)

1. **Zero build: open Médias in the TV's own browser, or cast from a phone/PC.** Effort: none to small. Needs the server on trusted HTTPS, a TV-navigable "10-foot" UI (D-pad focus, large targets) and signed stream URLs if Cast is used. Today's Media Center mode is a starting point but D-pad operability is not documented.
2. **LG webOS hosted-app sideload, packaged as a tiny `.ipk`.** Effort: small (one `appinfo.json`, one redirect page, `ares-package`). The only platform whose docs name hosted web apps as an official type. Limits: Developer Mode session must be renewed (limited session, apps removed on expiry), so it suits one owner, not distribution. Store publication would add Seller Lounge QA and a demo server.
3. **Android TV / Fire TV WebView wrapper APK, sideloaded.** Effort: small to medium (a leanback activity with a WebView, a first-run server-URL screen, D-pad key mapping). No expiry. One APK covers Google TV, most Android TV boxes, and Fire OS TVs [inference]. Google Play listing later costs US$25 and requires TV-quality criteria and a reviewer login.
4. **Samsung Tizen packaged `.wgt` sideload.** Effort: medium. Hosted mode is not store-eligible for public sellers, so use a packaged shell and keep the owner on developer mode with a DUID-bound certificate; certificate lifetime must be checked.
5. **Cast receiver or DLNA service.** Effort: medium. Gives playback without a TV app, at the cost of signed URLs, no resume sync from the TV remote, and (Cast) US$5 registration.
6. **Native Roku and tvOS apps.** Effort: large (full rewrite against `/api/media`). tvOS also costs US$99 per year to run longer than seven days. Not recommended unless users demand it.

Things worth verifying before committing to option 2 or 3 (not established above): LG developer-mode session length on current webOS, Tizen TV certificate validity, the video codecs and HLS behaviour of the TV's WebView, and whether the Médias web UI is usable by D-pad.

## Sources

Samsung: [TV device setup](https://developer.samsung.com/smarttv/develop/getting-started/using-sdk/tv-device.html), [registering an application](https://developer.samsung.com/tv-seller-office/guides/applications/registering-application.html), [becoming a Seller Office member](https://developer.samsung.com/tv-seller-office/guides/membership/becoming-seller-office-member.html), [hosted applications Q&A](https://developer.samsung.com/smarttv/develop/faq/hosted-applications.html). LG: [Developer Mode app](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app), [web app types](https://webostv.developer.lge.com/develop/getting-started/web-app-types), [app approval process](https://webostv.developer.lge.com/distribute/app-approval-process). Android: [TV app quality](https://developer.android.com/distribute/essentials/quality/tv), [Play Console registration](https://support.google.com/googleplay/android-developer/answer/6112435). Apple: [membership comparison](https://developer.apple.com/support/compare-memberships), [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/). Roku: [certification](https://developer.roku.com/dev/docs/certification), [streaming specifications](https://developer.roku.com/dev/docs/media), [developer setup](https://developer.roku.com/dev/docs/developer-setup). Amazon: [Vega developer mode](https://developer.amazon.com/docs/vega/0.22/developer-mode), [Vega submission](https://developer.amazon.com/docs/vega/2.0/app-submission). Cast: [registration](https://developers.google.com/cast/docs/registration). Plex: [supported smart TV models](https://support.plex.tv/articles/204080173-which-smart-tv-models-are-supported/), [connect app to account](https://support.plex.tv/articles/203395277-connect-app-to-your-plex-account/), [plex.tv/link](https://www.plex.tv/link/). Precedents: [jellyfin-tizen](https://github.com/jellyfin/jellyfin-tizen), [jellyfin-webos](https://github.com/sbou88/jellyfin-webos).
