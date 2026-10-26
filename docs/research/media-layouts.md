# Media interface layouts

Implementation baseline: `35d2f02`. The user approved all three visual draft layouts and explicitly selected **Cinematic home** as the default.

The visual reference is the interactive Media design study, initially served at `http://127.0.0.1:18819/`, with variants A, B and C. The draft uses fictional titles and sample photographs. Production must use the registered library's actual metadata and validated artwork.

## Layouts

- **Cinematic home**: a large featured title with artwork, a readable synopsis and Play/Resume/Details actions, followed by continue-watching and poster browsing. Folder maintenance and advanced filters do not dominate the screen.
- **Focus**: the selected title owns the large artwork and description area, with a compact title selection strip. Selecting another title updates the featured content without starting playback.
- **Collection**: a dense library grid with search and filtering, without the large featured area. Title details expose available releases, episodes, subtitles and partial-download availability.

All three are available in desktop and web interface settings. The saved values are `cinematic`, `focus` and `collection`. Missing or invalid preferences fall back to `cinematic`. Desktop persists the preference in Settings; web persists it per browser alongside its existing theme preference. This is an appearance preference, not a Torrent Client setting. A Media view selector can provide a shortcut to the same preference.

Changing layout must preserve the current media source, playback position, queue, player session, contextual chat and preview handle. It must not start playback or enable sequential downloading. All existing availability checks and explicit partial-preview behavior remain in force. Music browsing, paging, search, release/episode selection and playback controls remain accessible. Do not claim missing metadata, fabricate artwork associations or fetch images on the GUI thread.

## Validation

Use the previously user-approved desktop/web UI and streaming seams. Cover default layout, saved selection after reopening, switching all layouts during playback, empty or missing-art libraries, detail and partial-preview actions, and chat. Run focused tests during implementation, then the full suite once, static checks, visual inspection and separate standards/spec review. Commit on the current branch; publication is not part of this request.

## Media Center mode

The user clarified that fullscreen should apply to the entire Media interface, not only the playing video. A persistent Media toolbar offers **Media Center mode** and **Return to TorrentLinker**. Desktop hides the application sidebar, workspace header and status bar, enters fullscreen and restores the earlier window geometry on exit. Web hides the same application navigation and uses browser fullscreen when supported. Browsing video and music, changing layouts, playback and contextual chat remain available. Escape returns to the normal interface; leaving Media for another workspace exits the mode. The separate player fullscreen control remains available and retains captions and transport controls.

## Music presentation

The user also requested a visual pass for music. Give music its own presentation with visible Albums, Artists and Tracks navigation, square album artwork, compact track information, and clear playback queue and playlist actions. Use the registered library's actual metadata and artwork; unknown tags remain unknown. Music presentation must preserve album editions, group pagination, playback and queued track identities. It does not reuse the video's giant featured-title layout or change the saved video layout preference.
