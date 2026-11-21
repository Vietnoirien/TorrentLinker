# Pre-roll layout previews, #141

Throwaway preview. Seven screens, three structures per screen: A cards and sections, B list with inspector, C guided steps. Fictional data; controls never call app services. Uses the approved panel palette in a Media shell.

Run `python3 -m http.server 3181 --bind 127.0.0.1 --directory docs/specs/prerolls-preview` and open http://localhost:3181/?screen=library&variant=A.

Choose layouts for library, sequence, calendar, rules, trailers, studio and playback. Pending owner selection.
