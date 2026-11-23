# tr4ker community actions

Observed on 23 November 2026. Read with [the integration research](tr4ker-integration.md) and [the application inventory](tr4ker-integration-inventory.md). Purpose: decide which c411 community features (comments, trust votes, general/class chat, seed eligibility, limits/cooldowns, duplicate detection, receipts) have a tr4ker counterpart. Nothing was posted, voted, sent or changed.

Evidence labels: **GET** = live-verified read with the research session; **FE** = observed in the first-party bundle [V6OUW5OR.js](https://tr4ker.net/assets/V6OUW5OR.js) (private contract, no guarantee, mutations never called); **WIKI** = stated in a signed-in wiki article. Field types only, no personal data: [observations](tr4ker-community-observations.json). About 35 sequential GETs were made, plus wiki reads. No cookie, key or passkey value was saved. `/api/me/api-key` was not called.

## Auth and CSRF

FE: every mutation uses `credentials: include` (session cookie) with `Content-Type: application/json`. The bundle contains no `csrf` string, no CSRF meta tag read and no custom token header, unlike c411 (`csrf-token` meta + header). Absence in the frontend does not prove the server ignores CSRF (SameSite may carry it). Global handler: 401 raises `api:unauthorized`; 403 with `code: "banned"` or `ban_reason`; 429 reads `Retry-After` (default 60); 503 with `code: "maintenance"` differs from a transient 503. Error bodies carry `{error: "<French message>"}`; there are no stable machine codes for community actions, so classification must lean on HTTP status.

Chat is a WebSocket at `/api/ws` on the same origin (cookie authenticated, JSON frames, `ping`/`pong` keepalive, exponential reconnect 1 s to 30 s). It is not a REST post. Opening it from a tab is possible; from the desktop app it needs a cookie-bearing client, so keep it in the companion tab, as for c411.

## Actions

| Action | Route and method | Payload / response | Evidence |
| --- | --- | --- | --- |
| List torrent comments | `GET /api/torrents/<slug>/comments?page=&limit=20` | `{comments[], limit, page, total}`; 200 with empty list observed | GET + FE |
| Post torrent comment | `POST /api/torrents/<slug>/comments` | `{body}`; BBCode, max 1000 chars (rich) or 5000; response is the new comment object | FE |
| Delete comment | `DELETE /api/torrents/<slug>/comments/<id>` | author or staff | FE |
| React to comment | `POST /api/comments/<id>/reactions` `{emoji}`; `DELETE /api/comments/<id>/reactions/<emoji>` | per-comment emoji counts, `my_reactions` | FE |
| Thanks (merci) | `GET /api/torrents/<slug>/thanks` ; `POST` same URL toggles | `{thanked, total}`; button hidden for own uploads; no body | GET + FE |
| Favorite | `POST /api/torrents/<slug>/favorite`; `GET /api/me/favorites`, `/ids` | gated by `feature.favorites` | FE + GET |
| Reseed request | `GET`/`POST /api/torrents/<slug>/reseed` | see main research | GET + FE |
| Chat channels | `GET /api/channels` ; `POST /api/channels/<slug>/join` | `{channels[{id,slug,name,description,is_private,color,message_retention_days,created_at,member_count,is_member}]}`; six public channels seen: general, petites-annonces, aide, wiki, migrations, hors-sujet | GET + FE |
| Channel history | `GET /api/conversations/<id>/messages?limit=` | `{has_more, messages[{id,sender_id,sender,sender_role,avatar_url,sender_title,body,content_type,parent,created_at}]}` | GET |
| Conversation list / unread | `GET /api/conversations`, `/api/me/notifications/unread` | `{conversations[{id,type,slug,name,last_message,last_at,unread_count,color}]}`; types include channel, dm, report, moderation, ticket | GET + FE |
| Send chat message | WS frame `{type:"msg.send", conv_id, body, parent_id?}` | optimistic row; failure arrives as `{type:"error", message}`; no ack contract beyond `msg.received`; client marks unsent after 10 s | FE |
| Edit / delete message | WS `msg.edit {message_id, body}`; `DELETE /api/messages/<id>` | own or staff | FE |
| Chat reactions | WS `reaction.add` / `reaction.remove {message_id, emoji}` | server `reaction.updated {message_id, counts, users}` | FE |
| Hide shoutbox | `PATCH /api/me/shoutbox` `{hidden}` | preference only | FE |
| DM | `POST /api/dm/<username>` returns `{conv_id, username}`; messages via WS | | FE |
| Block user | `GET/POST/DELETE /api/me/blocks[/<username>]` | `{blocks[]}` | GET + FE |
| Follow uploader | `GET/POST/DELETE /api/users/<name>/follow`, `GET /api/me/follows` | notification type `follow_release` | GET + FE |
| Torrent report (create) | route not found in the bundle (probably an upload-time or lazy path); UI button "Signaler" | categories seen in FE: fake, dangerous, duplicate, detag, bad_category, other; `reasons[]`, `explanation` | FE (partial) + WIKI |
| Report lifecycle | `GET /api/me/reports/submitted`, `/received`, `/received/count` (`{active,revision,to_verify}`); `PATCH /api/torrents/<slug>/reports/fixed {response}`; `PATCH /api/reports/<id>/verify {accepted, rejection_reason}`; `PATCH /api/reports/<id>/dispute-abusive` | statuses pending, uploader_fixed, escalated, dismissed, reviewed, closed_deleted | GET + FE |
| Requests (v2) | `GET /api/requests-v2?status=&limit=`, `/<id>`, `/<id>/comments`; `PUT /api/requests-v2/<id>/vote {value}`; legacy `/api/requests/<id>/claim, unclaim, participate {amount}, confirm, dispute {reason}, fulfill-existing` | credits bounty; `feature.requests_v2` true, `feature.requests` false | GET + FE |
| Suggestions / bugs boards | `/api/suggestions`, `/api/bugs` (same topic shape, vote and comments) | | GET + FE |
| Tickets | `POST /api/tickets {subject, body, priority, reason}`; `GET /api/tickets` | support, returns `conv_id` | FE |
| Notifications | `GET /api/me/notifications[?page]`, `/unread`; `PATCH .../read`, `/bulk`; types torrent_reported, report_fixed, mention, message, ticket_reply, follow_release... | | GET + FE |
| Polls, announcements, badges, teams, shop | `GET /api/polls/active` (204 when none), `/api/announcements` (+ comments), `/api/badges`, `/api/teams`, `/api/shop` | read paths for context | GET + FE |

Absent from the bundle and the 196 distinct routes: any trust-vote, upvote/downvote on torrents, `actions-catalog`, `slow-mode-status`, forum routes (`feature.forum` false in `/api/public/features`), chat GIFs (`feature.chat_gifs` false). Torrent detail has no `trust`, `commentAccess` or `commentsLocked` fields (keys listed in the main research); `thanked` is only on the separate thanks route. The only per-torrent opinion signals are thanks, favorites and reports.

## Eligibility, limits, cooldowns

- Comments: FE disables the composer when the viewer already commented on that torrent (`alreadyCommented`; `allowMultiple` is set only for requests/announcements), so one comment per member per torrent is a UI rule. No seed, completion or ratio gate appears in the frontend. Server rules unknown.
- Thanks: toggle, not for own uploads.
- Chat: send permission comes from channel `write_roles` and role (`allowed_roles` for private channels); the client shows channel-level role gating only. No slow-mode endpoint, no daily quota catalogue. Retention per channel 7-300 days. No class channels analogous to c411.
- Reports: WIKI says new users and members with illegitimate past reports cannot report; one active report per torrent per member; explanation minimum 25 characters; VirusTotal link required for virus/phishing, duplicate link required for duplicates; reporter silence for 72 h closes the report as accepted.
- Roles (WIKI): Membre, Uploader en herbe (7 days + 10 validated uploads), Uploader (7 days + 100), Team, Helpeur and Contributeur (manual), Moderateur, Administrateur. Roles gate uploads, not discovered chat or comment rights.
- Ratio floor 0.5 blocks downloads (WIKI `ratio`), not community actions as far as stated.
- Numeric rate limits: only the generic 429/`Retry-After` handler is observed. No documented per-action quota. Treat unknown limits as unknown; do not copy c411 values (daily limit 5, cooldown seconds).

## Moderation rules (WIKI regles-generales, signalements)

Charter sanctions run from warning to permanent ban. Zero tolerance for insults, harassment, hate speech in comments, forum and chat; doxxing is a serious fault; fake content and disguised advertising are forbidden; one account per person; ratio cheating is a permanent ban; images must not be sexual, violent or shocking (adult category excepted). Reporting is peer-correction first: the uploader is notified and can fix or contest, the reporter accepts or rejects, escalation goes to moderation. Abusive reports can harm the reporter's standing (`dispute-abusive`). Support tickets must not concern credits or seedtime (FE confirmation checkbox).

## Mapping to c411 features

| c411 feature | tr4ker | Verdict |
| --- | --- | --- |
| Torrent comments | `POST /api/torrents/<slug>/comments {body}`, one per member (UI), BBCode, 1000/5000 chars | Equivalent, with different payload (`body`, not `content`), no CSRF header observed, higher length cap than c411's 500, eligibility unknown |
| Trust votes (approve/disapprove) | no route; closest signals are thanks toggle and reports | None. Thanks is a partial stand-in for approve only; disapprove maps loosely to a report |
| General chat | WebSocket `msg.send` on `general` (`conv_id` 1); history REST | Partial: different transport (WS), no slow-mode check, no ack beyond `msg.received` |
| Class chat | channels are topic based, not class based; private channels have `allowed_roles` | None |
| Seed-based eligibility | not exposed; `active-seeds` equivalent absent (`/api/me/downloads` only) | None known; server may gate silently |
| Limits / cooldowns | no catalogue route; only 429 `Retry-After` | None for pre-checks; use reactive backoff only |
| Duplicate detection | history readable for chat (`/messages`) and comments (`/comments?page`) | Equivalent (client side, same method as c411) |
| Receipts | comment POST returns the comment object (id likely); chat has no REST id; thanks returns `{thanked,total}` | Partial: comments yes, chat uncertain by design |
| Tracker economy (not community) | credits shop, bounties on requests | tr4ker-only, out of scope |

## Open gaps

1. Torrent-report creation route and body, and whether it is the right substitute for disapprove, were not found; probably in a code path not in the main bundle.
2. Server-side eligibility and quotas for comments, thanks, chat were not measurable without a POST; first real send must treat 4xx messages as the source of truth.
3. Populated comment and chat-ack shapes: no torrent with comments was inspected, so the torrent comment row is assumed to match request comments.
4. CSRF requirement unproven; WS authorization on cross-origin handshake unproven.
5. Whether chat writes in `general` need a minimum ratio, age or role is undocumented; `aide` is joinable and auto-joined by the frontend along with `general`.
6. `/api/public/features` flags (`forum`, `requests`, `chat_gifs`, `duplicates` false) can change; read them at runtime.
