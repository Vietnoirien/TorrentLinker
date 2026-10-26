# Media playback acceptance

Validated on 2026-10-26 after the compact Media Center and music interface changes. Tests used isolated configuration, conversations, playlists and player sessions. Existing media files were read in place. Their sizes and modification times were unchanged.

## Local assistant with existing media

The configured local Qwen3.8-27B-MXFP4-off model completed six conversations through the authenticated Assistant and Media APIs. All 13 assertions passed:

- Found the 18 local Aïoliwood tracks, saved their exact IDs in a playlist and presented cards without starting playback.
- Replaced the playback queue, removed its second item and saved the remaining 17 exact IDs in another playlist.
- Queued pause, volume 0.25 and seek to 30 seconds for the attached player only. A second player received no commands.
- Presented Mandibules from the local library and explicitly reported its missing synopsis.
- Declined to substitute another track for a nonexistent title.
- Reported the missing attachment when a separate conversation requested player controls.

Player reports in these assistant tests were simulated. They establish command routing and selection correctness, not physical playback. Decoder tests below provide separate playback evidence.

An initial seventh conversation confirmed that audio/subtitle selection tools were missing. Following the user’s request, `read_media_tracks`, `select_media_track` and optional track preferences on `play_media` were added to Assistant and MCP. A further real-model run controlled the actual Qt player: it recovered from an ambiguous VFF subtitle preference, selected English audio and full French subtitles, then changed to French VFF audio and disabled subtitles during playback. Decoder output and the unchanged source token were verified. Source-bound commands and acknowledged preparation prevent choosing tracks from another file or resuming after an unsupported or ambiguous choice. A separate exact-preference MCP run passed all seven checks against the actual film: preparation stayed paused, both tracks were selected, playback resumed, PCM/video/subtitle output decoded and the original file stayed unchanged. The initial model run’s strict “automatic request completed” assertion remained false after its ambiguous request, while all final user-outcome checks passed through the model’s manual recovery; the separate exact-preference run verifies the automatic path.

## Desktop audio and subtitles

Muted Qt playback of two existing films verified decoded PCM, video frames and decoded subtitle text, rather than only selected track indices:

| Film | Audio checked | Subtitles checked |
| --- | --- | --- |
| The Running Man | Three EAC3 tracks: French VFF, French VFQ, English | Five SubRip tracks: two French VFF, two French VFQ, English SDH |
| Sirat | Spanish EAC3 | French ASS and Spanish SubRip |

All tested tracks decoded without a player error. Audio and subtitle choices survived seeking, track-list refreshes and player fullscreen. Changing files reset the choices. Output stayed muted; no listening assessment was performed.

A generated regression fixture uses distinct 440 Hz and 880 Hz audio tracks and distinct subtitle text. The test observes decoded frequency and caption changes through the desktop selectors. Decoded-audio observation requires Qt 6.8 or newer; the test skips on older supported Qt versions.

The tests exposed and fixed two desktop gaps: there was no audio-track selector, and rebuilding the subtitle list disabled the user's selected subtitles.

## Browser limits

Chromium decoded video and sought successfully in The Running Man, Sirat and Pulp Fiction. AAC audio in Pulp Fiction decoded. EAC3 audio in the other two films did not, despite the browser reporting no playback error. This Chromium build exposed neither an audio-track selection API nor the embedded subtitle tracks for these files.

The web player therefore displays a compatibility note and an explicit link to the original for use in an external player, even when video appears to play. It does not claim to switch unsupported embedded tracks or transcode files. Browser and platform support can differ from these observations. The browser regression also exercises a real MCP request with an external English subtitle: it prepares paused, waits for the track, selects it and acknowledges resume through to completed status. An unsupported audio preference remains paused and shows the preparation error.

Authenticated range requests returned the requested bytes for all three files. Availability, removed-folder and replaced-symlink rejection, player-token isolation and partial-download boundaries are also covered by the automated Media API tests.

## Verification scope

The full automated suite passed with 1,517 tests and 116 skips after the track-selection workflow was added. The two opt-in browser scenarios passed separately in Chromium, including external subtitle cues and complete MCP preparation. The final long-track-title fix also passed focused native and browser tests. Ruff, formatting checks and mypy passed; the French catalog has no unfinished translations. Acceptance on this Linux Qt/Chromium installation does not establish codec support on every operating system or browser.

## Integrated player controls

Desktop video now uses a composited video surface with its transport controls inside the image and track choices in the player/context menu. Regression checks verify decoded video pixels behind controls, visible embedded captions, pointer auto-hide/reveal, keyboard pause, context-menu access and fullscreen. The real Running Man capture contains decoded film pixels, one decoded French caption and the native menu in the same screenshot. Music retains its persistent transport bar. A cue-gap regression caught a subtitle that remained visible after expiry; the player now preserves decoder subtitle state and forwards only video frames to the display sink. The regression verifies that the caption disappears in the blank interval.

Browser checks cover keyboard, right-click and touch access, external subtitle selection, menu focus across heartbeat updates, source changes and fullscreen geometry. Real Pulp Fiction playback was captured with the options menu. The existing browser codec and embedded-track limitations still apply.

The integrated-controls full suite passed with 1,517 tests and 116 skips. After the final subtitle-expiry correction, all seven native playback tests passed again, including the blank cue interval. Both focused browser scenarios passed separately. Static checks passed.
