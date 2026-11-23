# Identity page assets

`identity-companions.png` was generated with the built-in imagegen tool for this
page. It has an RGBA transparent background. The left kitten represents the user;
the right puppy represents the assistant. It is decorative UI, not a ChatGPT Pet.

Prompt: Two cute hand-drawn animal stickers shoulder-to-shoulder, cream and pale
apricot kitten on the left, cream and light caramel floppy-eared puppy on the
right. Equal-height full bodies, wobbly dark ink outlines, simple dot eyes,
dusty-rose smiles, uneven watercolor/crayon fills, warm naive doodle style.
Horizontal composition, small transparent margins, no text or extra objects.

The former dashboard illustration is retained as
`identity-companions.0a482df39a3a.webp` (287,340 bytes), alongside the 2.4 MB source
PNG. The smaller file is a format/encoding optimization using
Sharp WebP quality 85, alpha quality 100; dimensions and transparent alpha are
preserved. The content-hashed URL has a one-year immutable cache lifetime and
does not change when unrelated dashboard styles change. The PNG is retained as
the source asset. These illustrations are no longer loaded by the identity page.

The current page uses two touching circular portraits. Their defaults are inline
SVG faces; each portrait can be replaced with a custom image or restored to its
default. `identity-avatars.js` crops a selected image to a centered square and
compresses it to WebP (or JPEG when needed), with a maximum encoded image size
of 10 KiB. Only the compressed image is uploaded. The two avatar data URLs are
stored separately in `identity_presets`; saving names preserves both portraits.
Startup adds the avatar columns to existing databases automatically.

`lined-prompt-paper.jpg` is the original ruled, creased-paper image supplied by
the user for this page; it has not been altered and is retained as a reference.
The page and prompt editor now use solid backgrounds.
