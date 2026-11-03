# Decks

- `deck/project/`: the full deck's slides, in the same format as the Claude Slides artifact used for the demo video.
- The seven-slide SFF pitch reuses slides from the same folder; its list is in `build_site_decks.py`.

Rebuild both site decks (`site/slides.html`, full; `site/pitch.html`, seven slides) from the repo root:

```bash
python deck/make_bookmap.py site/data/book-map.json deck/deck/project/slides/bookmap.html
python deck/build_site_decks.py site site/pitch.html
```
