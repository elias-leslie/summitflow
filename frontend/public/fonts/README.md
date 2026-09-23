# Bundled application fonts

These 11 WOFF2 files are byte-for-byte copies of the font assets already served
by SummitFlow's successful managed release `c337389e5f2b4ce28f8728079567570b`.
They were originally obtained by Next.js's Google Fonts loader. No font outlines,
names, subsets, or font metadata have been changed.

`manifest.json` records each file's SHA-256, size, family, weights and Unicode
coverage. `app/fonts.css` preserves all 41 original font-face declarations
(including three metric-adjusted Arial fallbacks), with only the asset URLs
changed to this directory. The three Latin font preloads remain in the layout.

This removes build-time Google Fonts requests and the failing Turbopack
Google-font query resolution path. It does not claim the entire dependency
installation or application is offline-independent.

## License sources

All three families use SIL Open Font License 1.1. `OFL.txt` contains the complete
license and the copyright notices for their respective families. Official Google
Fonts repository notices were fetched through `st web fetch --backend direct`
on 2026-09-23; each returned HTTP 200 with untruncated text:

- Outfit: https://raw.githubusercontent.com/google/fonts/main/ofl/outfit/OFL.txt
- Bricolage Grotesque: https://raw.githubusercontent.com/google/fonts/main/ofl/bricolagegrotesque/OFL.txt
- JetBrains Mono: https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/OFL.txt

Retain this directory's notices when distributing these assets. Updating fonts
is an explicit asset update, not a network step during a normal build.
