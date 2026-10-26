# Local Upload presentations

The Assistant connection assessment tests structured arguments, reading a tool receipt,
repairing a rejected call, input images and tool images. Setup uses generated stripe
images and harmless in-memory tools. Results persist for the endpoint and model;
changing either invalidates them. A failed probe leaves chat and drafting available.
Context discovery reports server/provider metadata, not a verified usable limit.

Upload preparation returns structured file facts and copies extracted technical fields
into the description and generated NFO. Original NFOs are preserved. Unknown rip source
stays unknown. Research and owner-supplied fields can carry separate provenance through
`update_upload_fields`. This tool edits an exact saved revision and preserves unrelated
form values. Incomplete work remains saveable.

Presentation Images are private immutable assets in application data. EPUB and audio
covers, local artwork, explicitly imported public images and generated model renders
can be attached by ID. Asset access is scoped to the Local Item; IDs cannot select
arbitrary paths. Saved cards retain the captured images and camera metadata when later
revisions change. Local artwork satisfies local review, while sending still requires
a public hosted image. TorrentLinker does not automatically publish images.

The shared 3D tools are `inspect_3d_models`, `render_3d_preview`,
`create_3d_contact_sheet` and `attach_upload_assets`. The web Upload editor also exposes
inspection, per-piece presets and sheet capture. Desktop captures use the same CPU
renderer. Inspection preserves folders, scale/support variants and assembled-name hints;
filenames never prove that a mesh is assembled. Geometry reports bounds and triangle
counts, without inferring physical units.

Rendering runs in a disposable process with cancellation and a 120-second deadline.
One operation accepts at most 108 pieces, nine per labelled sheet, and reports every
covered or unsupported piece. Input meshes are bounded to 256 MB per file, with a
4 GB worker address-space limit on platforms supporting resource limits. Renders use
at most 20,000 display triangles per piece and never rewrite source geometry. Pillow
and NumPy support the same renderer without Qt or a GPU on headless servers.

Camera state includes yaw, pitch, roll, zoom and framing offsets. Each render asset
records its exact camera and geometry bounds. Only a model that passed both image
probes receives rendered pixels for visual review. Other models use presets and ask
the user to confirm the images. A setup probe is evidence about that connection, not
a guarantee of every subsequent visual judgement.

Review and send checks remain separate. No part of preparing facts, rendering,
attaching assets or saving a Local Draft creates a torrent, contacts c411 to write,
or changes source files or Torrent Client torrents.
