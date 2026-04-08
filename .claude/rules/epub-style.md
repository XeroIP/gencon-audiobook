---
globs: src/**/epub*.py
---

# EPUB Style Rules

## CSS — theme safety (critical)
The epub MUST fully support reader/device themes (dark mode, sepia, custom fonts, large text,
high contrast, accessibility modes). This is achieved by deferring ALL visual styling to the reader.

**Zero declarations allowed for:**
- `color` (including `currentColor` in color properties)
- `background-color`
- `font-family`
- Absolute font sizes: `px`, `pt`, `cm`, `mm`, `in`, `pc`

**Only allowed:**
- Structural layout: `margin`, `padding`, `text-align`, `line-height` in `em` or `%`
- Image sizing: `max-width`, `width`, `height` in `em` or `%`
- `display`, `float`, `clear` for layout
- `border` without color (e.g., `border: 1px solid` without a color value uses currentColor implicitly — avoid; use margin/padding for visual separation instead)

If a test checks for CSS compliance, it must assert the absence of `color`, `background-color`,
`font-family`, `px`-sized text, and `pt`-sized text in the stylesheet.

## Images
- JPEG only for all photos and the conference cover image
- No PNG for photos — PNG transparency looks wrong on dark backgrounds
- No WebP — older EPUB readers don't support it
- Speaker photos: resize to max 300px wide before embedding
- All images embedded in the EPUB (no external image URLs)

## EPUB structure
- EPUB 3.0, reflowable layout only (no fixed layout)
- Required files: `mimetype`, `META-INF/container.xml`, `content.opf`, `nav.xhtml`, stylesheet, chapter XHTML files
- `mimetype` must be the first file in the ZIP and stored uncompressed
- All XHTML must be valid XML (self-closing tags, quoted attributes, etc.)

## Content structure
- Cover page: conference cover image (JPEG)
- Copyright page: first page after cover — Intellectual Reserve, Inc. notice
- TOC: nested by session (Session heading -> Talk entries)
- Per-talk chapter: speaker photo, speaker name byline, talk title as heading, full transcript
- Transcript HTML: sanitized — strip `<script>`, `<style>`, external `src`/`href` attributes

## Validation
- Output must pass `epubcheck` with zero errors (warnings acceptable)
- No external URL references in content (images, stylesheets, scripts)
