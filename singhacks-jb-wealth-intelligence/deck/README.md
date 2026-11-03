# Decks

- `deck/project/`: the full deck's slides, in the same format as the Claude Slides artifact used for the demo video.
- `sff/`: slides written only for the seven-slide SFF pitch.

Rebuild both site decks (`site/slides.html`, full; `site/pitch.html`, seven slides) from the repo root:

```bash
python deck/sff/make_bookmap.py site/data/book-map.json deck/sff/bookmap.html
python deck/build_site_decks.py site site/slides.html
```
