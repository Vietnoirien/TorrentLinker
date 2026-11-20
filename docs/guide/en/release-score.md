# ReleaseScore

ReleaseScore compares a release’s video and audio facts with your selected profile. The small pill in Search shows an approximate score from listing data. A question mark means there are not enough facts, including season packs without a reliable total duration. It makes no additional Indexer requests.

Colour expresses profile fit, independently of the number: green fits, yellow misses one criterion, grey misses two or more, and red exceeds the profile’s size cap. The star marks the highest scoring green result on the current page. Open a result for the MediaInfo calculation and its explanation, when MediaInfo is available. A calculated score is not a guarantee of subjective quality or playback compatibility.

In Settings → Search & Matching, choose the active profile, edit or reset a built-in profile, and create, duplicate, rename or delete custom profiles. The equipment questionnaire recommends a profile only when you apply it. Dolby Vision, AVI, AV1 and DTS capabilities affect all profiles. Changes re-score open results and details locally. Advanced Poussée scoring is deferred.

## Credits and licence

The Rapide formula follows [ReleaseScore](https://github.com/Pilaleur/releasescore) 0.3.0 by Pila33, commit `cb65746203871d29a04acdf5447c3f662ba072cb`. TorrentLinker ports the calculation to Python. Estimates follow the author’s documented rules; they may differ substantially from measured facts.

```text
MIT License

Copyright (c) 2026 Pila33

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

```
