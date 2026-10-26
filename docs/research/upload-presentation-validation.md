# Upload presentation validation

Validation completed on 2026-10-26 for the capability and presentation changes after
baseline `2f9d937`. RSS was excluded.

## Automated checks

- Full suite: 1,396 passed, 110 skipped.
- Ruff passed for `src` and `tests`; mypy passed for 154 source files.
- Node syntax checks passed for the changed web application, Assistant and card scripts.
- Public MCP/API acceptance covered 13 pieces across two pages, native image results,
  private asset attachment, identical saved-card and queue-preview images, revision
  edits, retained owner provenance, and rejected incomplete page coverage.
- Rendering checks covered source preservation, camera-dependent pixels, reproducible
  camera metadata, unsupported geometry and cancellation.
- Provider protocol checks covered compatible Chat Completions, OpenAI Responses,
  Anthropic and Gemini image pixels, plus bounded context estimates for image input.

## Real files, read only

The real film yielded two Upload files, one inspected video, all audio/subtitle stream
facts and one private artwork asset. The generated presentation lacked only its
editorial synopsis and explicitly verified rip source.

The Aïoliwood album yielded 19 files, 18 audio tracks, measured bitrate, sample rate,
bit depth and a complete timed tracklist. Its generated NFO retained file/track counts
and bitrate. Only editorial synopsis and verified rip source remained missing.

The Colette EPUB yielded its title, author, French language and embedded artwork.
Generated technical fields and NFO were complete; only editorial synopsis remained.

Marika inventory retained all 54 meshes and variant folders. Triangle counts were
available for 50 meshes; four files exceeded the 256 MB per-file render limit. One
bounded full-set render produced four pages covering 33 meshes and explicitly reported
21 unsupported or unfinished pieces after reaching resource limits. Such a partial
page set cannot be presented as a complete Local Draft. This set still needs smaller
selected batches or external previews for meshes over the size limit.

No source files, Torrent Client torrents or running user application were changed.
Artifacts and isolated test configuration were written under `/tmp` only.

## Configured local model

The configured Qwen endpoint passed structured arguments and reading a tool receipt.
Rejected-call correction passed one assessment and failed another, so it is not a
reliable guarantee. Both generated input-image and tool-image probes were rejected
with HTTP 400 and recorded as untested connection/adapter failures. This does not prove
a model limitation. Tools and drafting remain enabled; visual inspection is unverified
and requires user confirmation.

## Standards

Two independent Sol review passes found three issues: duplicated preparation,
duplicated render publication and an outdated Presentation Image definition. The
shared preparation/publication functions and `CONTEXT.md` update resolved them.
The follow-up and final-delta reviews found no serious remaining issue.

## Spec

The independent Sol review found three issues: owner/research edits overwritten by
extraction, incidental NFO text treated as rip source, and inconsistent send readiness.
All were corrected and covered by regression tests. Final review also checked the
selected-piece coverage guard and unreadable audio accounting without finding a
serious remaining issue.

## Follow-up correction review

The independent follow-up identified eight gaps. The corrections align cardinal
camera axes with the desktop Z-up conversion and preserve live orbit distance/aspect,
accept wrapped angles and desktop zoom extremes, classify malformed model tool JSON
as a failed behavior probe, detect recognized original NFO contradictions without
rewriting it, add per-piece web camera controls, retain inventory beyond 108 pieces,
bound artwork extraction across books and local files, and preserve editorial sections
following multiline field edits.

Focused regression validation after these corrections: **66 passed**, including the
Qt capture seam, independent Qt quaternion/basis comparison, opposite occluding
surfaces, 109-piece inventory, 25 embedded EPUB covers, malformed provider arguments,
NFO conflicts/aliases/rounded durations and the web camera controls. Mypy passed for
158 source files; scoped Ruff and JavaScript syntax checks passed. The broader
Upload/model regression set then passed **270 tests**. The final shared suite will
run after the concurrent RSS implementation settles.

The standards correction review was clear. The spec correction review found two
false NFO conflicts: using only the first MediaInfo video duration, and treating
its inferred video count as a declared count of all files. A regression covering
two videos plus subtitle/artwork reproduces both and verifies the correction,
including detection of a genuinely wrong second duration. All 34 completeness tests
pass after that delta; mypy remains clear.
