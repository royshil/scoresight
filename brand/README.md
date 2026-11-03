# ScoreSight brand

**The mark** is an amber seven-segment "S", which also reads as a scoreboard's 5. It sits inside the blue corner brackets of a viewfinder: the box that ScoreSight draws around the digits it reads. Both are on a dark rounded tile.

**The wordmark** is "Score" in white (ink on light backgrounds) and "Sight" in blue, set in Barlow Semi Condensed Bold.

| | |
|---|---|
| Ink (backgrounds) | `#0B1220`, `#15213A`, `#1E2C4A` |
| Amber (the digit, accents) | `#FFB020`, highlight `#FFD27A` |
| Blue (the brackets, "Sight") | `#3DA5FF` |
| White / muted text | `#F5F7FA` / `#9AA7BD` |
| Fonts | [Barlow](https://github.com/jpt/barlow) and Barlow Semi Condensed (SIL Open Font License, `fonts/OFL.txt`) |

Everything is drawn by `scoresight_brand.py` (QPainter), so every file comes from the same geometry. `python brand/make_assets.py` (any venv with the app's requirements) writes these files:

| File | Use |
|---|---|
| `icons/scoresight.ico` | The Windows app, its installer and the window icon, 16–256 px. The smallest sizes are drawn bolder, not shrunk. |
| `icons/scoresight-macos.png` | The macOS app icon, on Apple's grid (an 824 px tile in 1024 px). PyInstaller makes the `.icns` from it. |
| `icons/splash.png` | The Windows build's splash screen. The loading messages go under the logo; see `text_pos` in `scoresight.spec`. |
| `docs/logo.png`, `docs/logo-dark.png` | The logo with the wordmark, for the documentation site and the README, on light and on dark backgrounds |
| `docs/favicon.ico` | The documentation site's icon |
| `brand/social-preview.png` | The repository's social preview, uploaded in GitHub under Settings > General > Social preview |
| `brand/logo/` | The masters: the mark and the lockups as SVG, and the mark as PNG from 16 to 1024 px |

When you change the logo, change `scoresight_brand.py` and run `make_assets.py` again. The tutorial videos (`tutorials/`) use the same module.

**Release posts.** `python brand/release_post.py --version X.Y.Z --tagline "..." --item "Title" "Line"` (four `--item`) `-o post.png` draws a release's square (1080×1080) image for social media in the same style every time: the logo, NEW RELEASE, the version, a tagline and four items. The project skill `.claude/skills/release-post/` explains how to write the copy. The images aren't kept in the repository.
