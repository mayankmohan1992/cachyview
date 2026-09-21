# CachyView — Additional Features Brainstorm

Sources researched: KDE bug tracker (annotation persistence), Hacker News
threads on Stirling PDF / in-browser PDF editors, Ask Ubuntu, gThumb/Linux
mailing-list threads, r/linux image-viewer threads. Below are real, recurring
pain points, mapped to whether CachyView can address them today.

Legend: ✅ already done · 🔜 in progress (the 3 agreed QOL items) · ❌ not done

> **Status update:** Most Tier-1 items have since landed — persistent
> annotations, flatten, true redaction, signature stamp, page compare,
> insert/append pages, full outline CRUD, auto-scroll presentation, recent/
> pinned files, archive flat view/search/drag-out, async archive listing,
> persisted image edit history, levels/curves, red-eye removal, lossless JPEG
> rotate, batch queue, in-place organiser, session restore, command palette
> and KDE theming. Also added: PDF→DOCX, PDF/A, AppStream metadata and a
> `--set-default` command. Still open: PKCS#12 (cryptographic) signing,
> in-place page-text editing, background removal, duplicate finder and
> screenshot capture. See `docs/PLAN.md` §6 for the authoritative status.

## A. PDF — biggest gap is a real editor, not a toolbox

1. **Annotations that persist in the file** — highlight, underline, sticky
   notes, freehand. KDE bug #151614 is 18 years old and still open: Okular
   stores annotations *separately* and they vanish when you email the PDF.
   (We already render pages; adding a real annotation layer that writes into
   the PDF via pikepdf + a QGraphics overlay is the single highest-value miss.)
   Effort: high.

2. **Flatten** — bake annotations/forms into the page so they can't be edited
   or removed. Explicitly requested in the Stirling PDF HN thread ("missing:
   redact, flatten, callout comments"). Effort: medium.

3. **True redaction** — black bar that *removes* the underlying text, not a
   cosmetic rectangle. Also from that thread. Effort: medium-high.

4. **Fill & sign forms** — type into AcroForm fields, draw/insert an image
   signature, then flatten. "Can't fill and save forms" is a top Linux complaint.
   Effort: high (AcroForms), or medium (just signature-stamp + flatten).

5. **Digital signature (PKCS#12)** — cryptographically sign so the doc is
   tamper-evident. Commenters note open tooling here is weak but legally
   important (eIDAS). pikepdf/qpdf support it. Effort: high.

6. **Page comparison / "compare two PDFs"** — pixel-diff two versions and
   highlight changed regions. Effort: medium.

7. **Add/append pages from other PDFs or images** — we can merge whole files
   but not "insert page 3 of B after page 2 of A" or "stamp an image page".
   Effort: medium.

8. **Auto-scroll / presentation mode** — hands-free reading, timed advance.
   Tiny effort, often requested for long docs.

9. **Bookmarks/outline editing** — currently we only *show* the outline;
   creating/editing/deleting PDF bookmarks is missing. Effort: medium.

10. **"Send by email" / share** — hand the file to the default mail client.
    Trivial Effort: low.

11. **Recent files + pinned files** — re-open last session; surprisingly
    absent from most Linux viewers. Effort: low.

## B. Archives — the friction is fine-grained access

12. 🔜 **Drag-out to Dolphin** (agreed).
13. **Preview-on-hover / quick-look** — hover a file in the tree, see a
    thumbnail or first page without a click. Effort: low-medium.
14. **Search inside archives** — find a file by name across a big zip without
    expanding. We list; we don't filter-by-typing-across-folders well yet.
    Effort: low (we already have a filter box; extend to recursive).
15. **"Open containing folder" after extract** — jump to the result in Dolphin.
    Trivial. Effort: low.
16. **Create archive from a selection** — right-click files in Dolphin →
    "Compress with CachyView" using our 7z backend. Our CLI can already do it;
    just needs a service menu. Effort: low.
17. **Test/repair archive** — verify integrity, repair with 7z/rar. Effort: low.
18. **Inline hex/structure view for suspicious archives** — security-minded
    users want to inspect before extracting. (Fits our sandbox ethos.) Effort: med.

## C. Images — "Preview.app but on Linux"

19. **Non-destructive edit history persisted to disk** — re-open a file and
    see the adjustment stack; revert any step. We have an in-memory undo stack
    but it dies on close. Effort: medium.
20. **Side-by-side compare** — pick two images, zoom/pan in sync. Requested
    repeatedly for Linux viewers. Effort: medium.
21. **Batch rename / caption** — rename in-place from the viewer. Effort: low.
22. **Find duplicates / similar** — by perceptual hash. Effort: medium-high.
23. **Lossless rotate & re-save (JPEG)** — rotate without re-encoding to avoid
    generation loss. Pillow can do lossless JPEG transforms. Effort: low-medium.
24. **Format conversion batch** — HEIC/WebP/AVIF ⇄ common formats in bulk.
    (libvips already covers the formats.) Effort: low (reuses batch queue).
25. **Screenshot / quick-capture** — grab a region to a new tab. Effort: med.
26. **Color picker / ruler / magnifier** — measure pixels, grab a hex from the
    image. Tiny but loved in Preview. Effort: low.
27. **Slideshow with transitions + background music? (skip music)** — Effort: low.

## D. Cross-cutting QOL

28. 🔜 **Batch processing queue** (agreed).
29. 🔜 **Organiser in-place overwrite + Save As** (agreed).
30. **Tabs / session restore** — reopen last N files on launch. Effort: low.
31. **Command palette (Ctrl+K)** — fuzzy-run any tool/action. Big speed win,
    cheap to build on top of our tool dispatch. Effort: low-medium.
32. **Dark/light + accent theming that follows KDE** — we're Qt; should honour
    the KDE colour scheme automatically. Effort: low.
33. **Keyboard-first navigation** — j/k paging, ? for shortcuts overlay. Effort: low.
34. **OCR language picker + keep-original toggle** — we OCR but force English
    and replace the file. Let users pick language and keep a text layer only.
    Effort: low.
35. **"Open with" other app** — send the current file to GIMP/Krita/Dolphin.
    Effort: low.

## E. My recommended next slice (after the 3 agreed QOL items)

Tier 1 (high value, low/med effort, fills real gaps):
  - 1 real annotations (the #1 Linux PDF complaint, 18-yr-old bug)
  - 2 flatten
  - 8 auto-scroll / 11 recent files / 33 shortcuts overlay (cheap wins)
  - 23 lossless JPEG rotate
  - 26 color picker / ruler / magnifier
  - 30 session restore, 32 KDE theming, 35 open-with

Tier 2 (medium effort, strong differentiators):
  - 3 true redaction, 4 signature-stamp+flatten, 7 insert/append pages,
    9 outline editing, 20 compare view, 19 persisted edit history,
    28 batch queue (already agreed)

Tier 3 (heavy, optional):
  - 5 digital signing, 6 PDF diff, 22 duplicate finder, 25 capture

Note: items 12/28/29 are the three already agreed and should land first.
