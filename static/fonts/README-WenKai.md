# Conversation title handwriting

Chinese title glyphs use LXGW WenKai TC, regular (400), from Google Fonts v11.
English title glyphs retain the existing Caveat font. Chat message bodies are unchanged.

- Author/source: https://github.com/lxgw/LxgwWenKaiTC
- Official distribution: https://github.com/google/fonts/tree/main/ofl/lxgwwenkaitc
- Webfont manifest: `https://fonts.googleapis.com/css2?family=LXGW+WenKai+TC&display=swap`
  requested with a Chrome user agent on 2026-10-02. Assets are pinned copies
  from `https://fonts.gstatic.com/s/lxgwwenkaitc/v11/`.
- License: SIL Open Font License 1.1; original copyright and the full
  Google Fonts distribution license are preserved in `OFL-WenKai.txt`.

The 115 official WOFF2 subsets are mirrored unchanged under `wenkai/`.
`wenkai.css` preserves the supplied `unicode-range` values, changes URLs to
local paths and assigns the CSS family alias `Ash WenKai`. No font binaries,
names or outlines were edited. Both simplified and traditional Chinese are
supported; browser fallback handles characters outside the original font.

Font files and CSS are served locally. Browsers download only shards needed
by visible conversation titles; do not preload the complete set. No external
font service is contacted when the dashboard is used.
