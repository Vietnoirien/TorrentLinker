# Maximum playback quality for Members, and a remembered quality — preview

Status: preview, awaiting the Owner's pick. Nothing is implemented.

The real Web UI (Settings and Médias) with example data, plus one script that adds only the proposed change. The film's
playback facts are stubbed; no real client or account is reached.

```bash
.venv/bin/python docs/specs/quality-limit/serve.py
```

- http://127.0.0.1:8767/quality-preview/owner: Paramètres > Utilisateurs > Léa > Modifier. **Qualité maximale** sits next
  to the Age limit; choosing a value is what Léa's player then obeys.
- http://127.0.0.1:8767/quality-preview/member: Léa's Médias. Play a film, ⚙ > Qualité: choices above the limit are gone
  (Original too, since it can exceed the limit).

## Proposed behaviour

- **Per Member**, like the Age limit and visible folders: "Aucune limite", 360p, 480p, 720p, 1080p. A Member's Profiles and
  Shared Screens follow it. Only a manager may raise it; they cannot exceed their own.
- **Server-enforced.** Under a limit, the original-file stream and any quality above it are refused; the compatible stream
  is the only way to watch. The original stays playable when the file's own height is within the limit.
- **Plays at once**, with no prompt: at the last quality chosen on this device (localStorage), else the highest allowed (Original without a limit).

## Open questions

- One setting per Member (shown), or a single limit for all Members?
- Should a limited Member lose Original even when FFmpeg is missing on the host (no playback at all), or keep it?
