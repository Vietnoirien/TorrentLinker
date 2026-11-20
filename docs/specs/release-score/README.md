# ReleaseScore preview for #117

Throwaway design preview, stored on `codex/release-score-preview`, outside main. All sample scores and equipment recommendations are illustrative. It makes no network requests and keeps changes only in memory. The production formula is not implemented here.

## Decisions

The operator chose equipment questions in this issue, advanced Poussée scoring later, profile editing inside Search settings, and unknown season scores until sufficient facts are available. On reviewing the first preview, the operator requested a small coloured pill instead of the large score block. The revised rows show `≈ 92`, a colour and a star where applicable. ReleaseScore identification, estimate status and the full explanation remain available through the accessible label, tooltip and click.

This preserves the approved Search row structure and shared theme tokens. It explores only the ReleaseScore addition, not alternative Search layouts.

## Open locally

```sh
python3 -m http.server 18817 --bind 127.0.0.1 --directory docs/specs/release-score
```

- [Desktop Search](http://127.0.0.1:18817/prototype.html?mode=desktop)
- [Web Search](http://127.0.0.1:18817/prototype.html?mode=web)
- [Search settings](http://127.0.0.1:18817/prototype.html?mode=desktop&area=settings)
- [French, light theme](http://127.0.0.1:18817/prototype.html?mode=web&area=settings&lang=fr&theme=light)

The file is self-contained and also opens directly.

## Review paths

1. Compare green, yellow, red and grey pills, the best-match star and unknown runtime/season rows. Switch Compact/Comfortable.
2. Click a pill. Compare the estimated explanation with the MediaInfo sample. Unknown rows explain the missing facts.
3. Switch the active profile to 4KLight and return to HDLight. Sample scores and the star move immediately.
4. Open Search settings. Duplicate, create, edit, rename and delete personal profiles; reset a built-in. Built-in names cannot be renamed or deleted.
5. Fill equipment questions, save them, or explicitly create an illustrative equipment profile. Nothing persists after reload.
6. Use French/English, light/dark, desktop/Web mode and a narrow viewport. The bottom bar exposes current preview state.

Some surrounding Search controls are context only. Profile fields store preview choices, while sample scoring illustrates the profile switch rather than reproducing the final engine. Equipment recommendation logic is also illustrative until implementation approval.

## Upstream reference

Profile defaults and field vocabulary follow ReleaseScore 0.3.0, commit `cb65746203871d29a04acdf5447c3f662ba072cb`, by Pila33. Source: <https://github.com/Pilaleur/releasescore>. The MIT notice is retained in `LICENSE.ReleaseScore`.

The issue requires owner approval of the concrete preview before production implementation. No such approval is recorded yet.
