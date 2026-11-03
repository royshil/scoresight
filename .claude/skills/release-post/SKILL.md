---
name: release-post
description: Make the square (1080x1080) social image and the post texts for a new ScoreSight release: the YouTube community post (also LinkedIn, X) and the OBS forum resource update (title, message with download links per OS). Use when the user asks for a release photo, social image, announcement picture or post for a version (e.g. "we released 0.4.4, I need the photo for social").
---

# Release post: the square image and its text

Every release gets the same 1080x1080 picture, drawn by `brand/release_post.py` with the brand module: the logo, **NEW RELEASE**, the version in large amber, a one-line tagline, four items (a bold title and a muted line under it) and the footer (*Free and open source · Windows · macOS · Linux* and *github.com/royshil/scoresight*). Only the version, the tagline and the four items change. Don't redesign it: the posts should look like a series.

The published ones are on the Posts tab of Roy's YouTube channel, https://www.youtube.com/@royshilk/posts (0.4.2 was the first in this style). To look at one, fetch that page and take the post's `yt3.ggpht.com/...` image URL with `=s1080` at the end.

## Steps

1. **Read what the release changed.** `gh release view X.Y.Z` (the body is the CHANGELOG section), or `## [X.Y.Z]` in `CHANGELOG.md` if it isn't published yet.
2. **Write the copy.** The tagline is the release in a few words, in the voice of the release notes' first lines. The four items are the headline features first, then the fixes users asked for. Two fixes can share one item (*Steadier clocks, Mac fixes*).
   - Title: short, about 30 characters at most, a plain name for the feature or fix (*Phone camera*, *Soccer clocks past 59:59*).
   - Line: one concrete sentence on what it does for the user, about 60 characters at most, with real values where they help (*Time formats now take 60:00, 90:00 and 120:00*).
   - Avoid jargon and marketing words. The script exits with *Too long for the picture* naming the line to shorten.
3. **Render** (any venv of the app, from the repo root):
   ```sh
   .venv/Scripts/python.exe brand/release_post.py --version X.Y.Z \
     --tagline "..." \
     --item "Title 1" "Line 1" --item "Title 2" "Line 2" \
     --item "Title 3" "Line 3" --item "Title 4" "Line 4" \
     -o <scratchpad>/scoresight-X.Y.Z-post.png
   ```
   `--version` defaults to `src/version.py`, which may be behind the release on the current branch, so pass it.
4. **Look at the PNG** (Read it) before handing it over: nothing clipped, nothing overlapping the footer.
5. **Deliver.** Copy it to `C:\Users\roysh\Downloads\scoresight-X.Y.Z-post.png` and give the full path, then the two texts below, ready to paste.

Don't commit the PNG. Release images aren't kept in the repo.

## YouTube (and LinkedIn, X) post text

In the style of the 0.4.2 post: *"ScoreSight 0.4.2 brings a lot of requested features and improvements from the community - grab it now! https://github.com/royshil/scoresight/releases/tag/0.4.2"*. One or two sentences naming the headline features, then the release link.

## OBS forum update

ScoreSight's resource on the OBS forum: https://obsproject.com/forum/resources/scoresight-free-open-source-ocr-tool-for-gaming-and-scoreboards.1884/. Roy posts each release there with **Post update** (the resource's updates are at `.../updates`). Its form asks for:

- **Version string:** `X.Y.Z` (no `v`).
- **Update title:** `vX.Y.Z: <the release in a few words>`, like the past ones: *v0.4.2: Community improvements and fixes - better than ever!*, *v0.3.2 - A new OCR engine, live overlays, and many more broadcast products.*
- **Update message:** the square image (attached, file named `scoresight-X.Y.Z-announce.png`), one sentence on the release, then the downloads, one direct link per OS. The forum autolinks plain URLs, so give plain text:

```
ScoreSight X.Y.Z: <one sentence: the headline features and the fixes>.

Downloads:
Windows (installer): https://github.com/royshil/scoresight/releases/download/X.Y.Z/scoresight-X.Y.Z-windows-x64-setup.exe
Windows (portable zip): https://github.com/royshil/scoresight/releases/download/X.Y.Z/scoresight-X.Y.Z-windows-x64-portable.zip
macOS (Apple Silicon): https://github.com/royshil/scoresight/releases/download/X.Y.Z/scoresight-X.Y.Z-macos-arm64.dmg
macOS (Intel): https://github.com/royshil/scoresight/releases/download/X.Y.Z/scoresight-X.Y.Z-macos-x64.dmg
Linux (x86_64): https://github.com/royshil/scoresight/releases/download/X.Y.Z/scoresight-X.Y.Z-linux-x64.tar.gz

What's new: https://github.com/royshil/scoresight/releases/tag/X.Y.Z
Already on 0.4.1 or newer on Windows (installed)? Help > Check for updates offers Update now.
```

Take the file names from the release's assets (`gh release view X.Y.Z --json assets -q '.assets[].name'`), since a platform can be added or dropped, and check each link answers 200 (`curl -sIL -o /dev/null -w '%{http_code}' <url>`) before handing them over. A draft release's links don't work yet: say so.

## Past copy, for tone

**0.4.2**: *Your requests, shipped.*
- When blank: clear the value / Penalty timers clear in vMix, OBS and overlays when they go out
- Ask before closing / One wrong click no longer stops the broadcast
- Clocks with tenths after a colon / New format Time mm:ss or ss:d reads 59:8 as 59.8 s
- Steadier clocks, Mac fixes / A running clock no longer freezes; Auto layout downloads on a Mac

**0.4.3**: *Your phone is the camera.*
- Phone camera / Scan a QR code: your phone streams to ScoreSight, no app
- Smooth preview / Up to 20 frames a second: a running clock moves like video
- Soccer clocks past 59:59 / Time formats now take 60:00, 90:00 and 120:00
- Clocks that drop their colon / 236 is put back as 2:36 from the last good reading

If the design ever has to change (a new footer, a different number of items), change `brand/release_post.py` and keep it drawn from `scoresight_brand.py`.
