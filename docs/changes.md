# Build Log

What was built in each phase, what went wrong, and how it was fixed.

This file is written as the work happens, not afterwards. It feeds the written
report directly — the "issues faced" sections are the interesting part of the
report, not something to hide.

---

# Phase 0 — Setup

*22 October 2026 — decisions made, environment not yet created*

## 1. Initial build

No code yet. The brief was read and the starting decisions recorded:

- **What to build:** a browser-based annotation tool with two kinds of AI help —
  click-to-segment and auto-suggested boxes — plus export and built-in
  measurement of effort. See `design.md`.
- **Stack:** Python 3.11, FastAPI back end, plain JavaScript canvas front end,
  SQLite. See `tech.md`.
- **Seven project documents** created before any code, so decisions and problems
  are recorded as they happen.

## 2. Issues faced

**(a) The brief rules out the obvious shortcut.**
Mature open-source annotation tools (CVAT, Label Studio) already have SAM
integrations. The brief forbids forking or wrapping them, so the canvas, shape
editing, storage and export all have to be written from scratch.

**(b) The machine's default Python cannot use the GPU.**
Default is Python 3.14; PyTorch has no CUDA build for it. Known from earlier
projects on this machine — it would otherwise surface only in Phase 3, when the
first model is loaded.

**(c) 4 GB of GPU memory.**
The RTX 3050 rules out the large segmentation models, and two models (segmenter
and detector) have to share the card.

**(d) No C++ build tools on Windows.**
Packages that compile native code during install (and Node packages using
node-gyp) fail on this machine.

**(e) The evaluation requirement depends on data that must be collected from the start.**
"Show how much effort the assistance saves" needs measurements of manual
labelling. If timing is only added at the end, the manual baseline has to be
redone.

## 3. How it was solved

**(a)** Accepted as a design constraint and stated explicitly in `design.md`.
The project builds its own canvas and uses pretrained *models* (allowed if cited),
not pretrained *tools*.

**(b)** Use `py -3.11 -m venv .venv`. Check of the constraint imposed by the
*last* phase (model inference) before building the *first* one.

**(c)** Choose small variants: SAM 2 tiny (MobileSAM as fallback) and YOLO
nano/small. The segmenter's image encoder runs once per image and its embedding
is cached, so per-click cost stays low.

**(d)** Prefer packages with Windows wheels; plain JavaScript front end with no
npm build step.

**(e)** Interaction logging (clicks, keys, time per image) becomes part of
Phase 1, and evaluation gets its own phase (Phase 5).

---

# Phase 1a — Labelling script for ECHOSCAPE (core, crude interface)

*22 October 2026 — built and checked on real data; not yet used by a human*

## 1. Initial build

The Deep Learning project (ECHOSCAPE, due 8 Nov) needs land-cover labels this
week, three weeks before this project is due (29 Nov). Rather than write a
throwaway labeller there and start from zero here, the reusable part was built
now, with a deliberately disposable interface on top:

- `core.py` — no interface. Loads a GeoTIFF, region-grows from a click, assigns
  classes to a uint8 mask, saves it on the source grid, logs every interaction.
- `label.py` — a matplotlib window (click, keys 0–6, `+`/`-` tolerance, `v` view,
  `n`/`p` month, `s` save, `q` quit). To be replaced by the browser canvas.

**Region growing:**
1. Six spectral bands, each scaled by its 2–98 percentile range and smoothed 5×5.
2. The reference spectrum is the median of a 5×5 window around the click.
3. Pixels within an RMS-distance tolerance become candidates; a 3×3 opening cuts
   one-pixel bridges.
4. The connected component containing the click is kept, with holes filled.

It takes about 0.04 s per click and 0.13 s per month for feature preparation.

**Logging:** every click, tolerance change, assignment and save goes to
`logs/clicks.jsonl`, with a timestamp, the time since the previous event, the
region size and the pixels changed. This is the manual baseline for Phase 5,
collected from the first real image.

## 2. Issues faced

**(a) The silent failure: a mask on a slightly different grid.** A one-pixel
shift would make every label describe the wrong ground. Nothing would crash, and
the Deep Learning model would just come out worse, blamed on the model.

**(b) The right tolerance is not obvious.** On the Kenya scene, with 12 random
seeds, the median region size jumped from about 30 px at tolerance 0.06 to about
150,000 px at 0.22. At 0.16 with heavy smoothing, regions leaked across different
land covers.

**(c) matplotlib's built-in keyboard shortcuts clash with labelling keys.** `s`
saves the figure, `q` closes the window, `p` and `o` are pan and zoom, and so on.

**(d) The headless test crashed on click.** With no GUI backend there is no
toolbar, so `toolbar.mode` raised an error.

## 3. How it was solved

**(a)** The mask is written with the source file's own rasterio profile. It is
written to a temporary file first, reopened, and must have identical CRS,
transform, width, height and pixel content before it replaces the previous save.
`python core.py <tif> <outdir>` runs the same round trip as a self-test, with
marker pixels in opposite corners to catch flips. It passed on the real Kenya
tile.

**(b)** Rendered six combinations of smoothing and tolerance over the false-colour
image and compared them by eye. 5×5 smoothing at tolerance 0.12 gave coherent
zones without crossing obvious land-cover boundaries, so that is the default.
Tolerance stays adjustable live with `+`/`-`, and every change is logged, since
how often a user corrects the tool is itself evaluation data.

**(c)** Cleared every `keymap.*` entry. Zoom and pan stay available through the
toolbar buttons, and clicks are ignored while zoom or pan is active.

**(d)** The click handler now checks that a toolbar exists before reading its
mode. Afterwards the whole loop was driven on a scratch copy of the data: click,
assign, `+`, assign, change view, change month, quit. The saved mask reloaded
with the expected class counts.

## Phase 1a, first real use — 24 October 2026

**(e) The first user could not work out what to do after clicking.**
Yuvraj opened Mannheim, clicked zones, and got stuck. The click log shows it
plainly:

- **16 clicks, 0 class assignments, 1 save.**
- The yellow selection is only a preview until a number key is pressed, but
  nothing on screen said so.
- The class names appeared nowhere; the only cue was a long one-line title.

The log measured a usability failure before anyone described it, which is
exactly what it is for.

**(f) Month parsing broke on region names containing an underscore.**
The title took the month as `stem.split('_')[1]`. For `nile_delta` and
`egypt_desert` that returns "delta" and "desert". The same mistake on the Deep
Learning side made two regions look empty when all 12 months were on disk.

**How it was solved** (edited by the Deep Learning session at Yuvraj's request,
while he was mid-labelling; reviewed here):

- **(e)** The window became two panels: the image, plus a legend panel.
  - The legend shows the six classes with colour, key and name, **and what each
    looks like in the false-colour view** ("deep dark red" = trees). Knowing
    what to look *for* was the part that unblocked him.
  - It shows the share of the image already in each class.
  - A large "% labelled" figure has a progress bar and a marker at 40% saying
    "40% is plenty".
  - The title adds "<- press 1-6" while a selection is pending.
- **(f)** The month now comes from a `YYYY-MM` regex match, not a position.
  **Lesson:** match the shape of the thing you want; never count separators.

**For the report:** the first-run log (many clicks, no assignments) is a
concrete example of interface discoverability. It is the before-picture for any
UI improvement measured in Phase 5. The web app should show class names and
"what to do next" on screen from the start.

**(g) The user had the wrong idea of which image the model learns from.**
After labelling for a while, Yuvraj asked for "the radar image I label, plus a
colour one beside it". He believed the red-and-cyan false-colour picture was
radar. It is Sentinel-2 optical. He had never seen the Sentinel-1 radar the
model actually trains on.

**Solved** (Deep Learning session, at his request; reviewed here): the window
became **three panels: optical (clickable) | radar (view only) | legend.**

- The radar panel shows that month's Sentinel-1 as a false-colour picture of VV,
  VH and VV−VH in decibels. It is cached per month and is for display only.
- **The label mask and the pending selection are drawn on both panels.** Clicking
  a forest on the optical image immediately shows what that ground looks like to
  the model.
- The panel titles say "CLICK HERE — Sentinel-2 optical" and "VIEW ONLY —
  Sentinel-1 radar".
- Clicking the radar now shows a warning instead of silently doing nothing.
  Silence was what let the misunderstanding persist.

**Lesson for the web app:** when a tool shows one image but the labels serve
another, put both on screen. Otherwise the user builds the wrong mental model of
what they are doing, and nothing tells them.

**Known gap, minor:** the radar panel assumes the Sentinel-1 file is on the same
grid as the optical and doesn't check it. That's safe for the Deep Learning data,
which was built aligned and verified. The browser version should assert it with
`core.grid_of` like the optical months do.

## Phase 1b — Browser version, forced by hardware (24 October 2026)

**Issue (h): the matplotlib window froze on a two-monitor setup.**
Yuvraj's monitors use different DPI scaling. Dragging the window between them made
it stutter and freeze, because matplotlib's Tk backend on Windows doesn't handle
per-monitor DPI changes. Two real fixes were tried first and neither touched the
cause:

- shrinking the window from 1850 to 1190 px;
- cutting the redraw from 0.92 s to 0.34 s by building the legend once instead of
  rebuilding 45 text objects per frame.

**Solved by moving to the browser** (built by the Deep Learning session, reviewed
here). Browsers handle per-monitor DPI properly, so the problem disappears instead
of being worked around.

- `server.py` (FastAPI) is transport only. Every decision still happens in the
  unchanged `core.py`. A `Region` object keeps each area's images, features and
  mask in memory.
- `static/index.html` is plain JavaScript with no build step. It has three panes:
  clickable optical, view-only radar, and a legend.
- **The mask lives in Python, never in the browser.** A click goes up and a PNG
  comes back, so there is one copy of the truth and saving is unchanged.
- It was checked on real Mannheim data: a 53,583 px region assigned class 3
  produced a GeoTIFF with identical CRS, transform, size and bounds.

**For the report:** the web front end was not chosen on paper. It became
necessary because of a hardware constraint discovered in real use. It is also the
foundation the AI Vision app needed anyway.

**Click-log hygiene.** Not every session in `logs/clicks.jsonl` is real labelling:

- The sessions with only a `start` event (17:28–18:00) are almost certainly
  automated render tests of `label.py`.
- Session `ab9432dd` (18:05–18:07) is the browser test, including the 53,583 px
  assignment whose label file was deleted afterwards.
- The real manual sessions are `f65c813f` (17:19), `0cf61028` (17:52) and
  `bb5ae444` (18:01).

Phase 5 must filter by session. **From now on, tests should log to a separate
file** (`label.py --log …`; `server.py` needs the same option).

**Found in review** (status as of Phase 1c):

- **(1) is fixed:** clicks use `floor` now, and the server rejects out-of-range
  pixels.
- **(2) is still open.**
- **(3) is partly covered:** each click logs the tolerance it used, but changing
  the tolerance on its own still isn't logged.

1. **Clicks at the right or bottom edge can crash a request.**
   `Math.round(x / scale)` can return 600 on a 600-px image, which is out of
   range in `grow_region`. Fix: use `Math.floor` and clamp to `width − 1`.
2. **`+` / `-` no longer regrow the current selection.** The matplotlib version
   did; now the new tolerance only applies to the next click.
3. **Tolerance changes are not logged** in the browser version, so evaluation
   loses a signal it had before.

## Phase 1c — multi-zone selection, zoom, class suggestion (24 October 2026)

Requested by Yuvraj while labelling real regions (Arabia, Amazon), relayed by the
ECHOSCAPE session.

### 1. Initial build

- **Multi-zone selection.** A plain click replaces the selection, as before.
  Shift+click adds another zone, Esc drops the selection, and one key press labels
  all the zones together.
  - The server keeps a list of zones and joins them only at assignment.
  - The log keeps them apart: the `assign` event carries `zones` and `zone_px`, so
    several clicks never look like one.
- **Zoom and pan.** Mouse wheel zooms at the cursor, a drag pans, `z`/`x` zoom in
  and out, `f` fits to the window.
  - Each pane holds the image at native size under a single CSS transform, and
    both panes share it.
  - Clicks are mapped back by inverting that transform exactly, using `floor`,
    never `round`.
- **Class suggestion** (`core.annual_indices`, `core.suggest_class`). When a zone
  is selected, the legend shows a proposed class plus the numbers behind it.
  - It uses NDVI, NDWI and NDBI from the region's Sentinel-2 images.
  - Each index is summarised per pixel over the **whole year**, then the median is
    taken over the selection.
  - **It never assigns.** The human still presses the key.
- **Logging for the evaluation.**
  - Every event is now tagged `mode: "regiongrow+suggest-v1"`.
  - Each click logs the suggestion. Each assign logs `suggested`, `suggested_alt`,
    `confidence`, `matched` and `matched_alt`.
  - **Assisted mode begins with the first `regiongrow+suggest-v1` event**, i.e.
    when the server is restarted on this code. Earlier events
    (`manual-regiongrow`) are the manual control group and were not modified.
- **Test isolation.** `server.py --port --data --log` lets tests run against a
  copy of the data with their own log. Every test below used port 8001, a scratch
  copy of Mannheim and a scratch log.
- The server rejects out-of-range pixel coordinates with HTTP 400 rather than
  clamping them, so a wrong mapping fails loudly instead of quietly labelling the
  image edge.

### 2. Issues faced

**(a) The silent-failure risk in zoom.** Once the image is scaled and panned, a
wrong screen-to-pixel mapping grows every region around the wrong pixel. Nothing
crashes, and the picture still looks plausible.

**(b) The first mapping was off by the holder's 1px border.** The image is
positioned from the holder's padding edge, but the code measured from its outer
edge. Found by the automated cross-check below. In the earlier version this
shifted every click by up to one screen pixel.

**(c) A CSS class collision.** The zoom container's class `.view` also matched the
radar pane's title (`h2.view`), so that title was absolutely positioned on top of
the optical pane's title.

**(d) A key pressed straight after a click could be lost.** If `3` or Esc arrived
while the click's request was still in flight, the server had no selection yet.
The key did nothing, or the selection reappeared after Esc. Found because the test
harness sends keys quickly; a fast labeller would hit it too.

**(e) A max − min seasonal amplitude made rainforest look like cropland.** Amazon
forest he labelled as trees scored amplitude 0.3–0.48, and 10 of 15 zones were
suggested as cropland. Haze and cloud the mask missed pull NDVI down in some
months, and the minimum takes the worst month.

**(f) Deciduous forest also swings.** The forest east of Mannheim (amplitude 0.34)
was called cropland even with the trimmed range. Its yearly low point, though, is
still NDVI 0.47.

**(g) The indices cannot separate built-up from bare desert.** Open desert in
Arabia and Egypt has NDBI 0.08–0.16. The Arabia zones he hand-labelled built-up
have 0.06–0.15.

**(h) A "green city" rule would wreck the steppe.** I tried "built-up if NDBI > 0
and not seasonal" in the vegetated band. It would have called **91% of Mongolia**
built-up.

**(i) Steppe looked like trees.** Mongolian grassland (yearly peak about 0.35, not
seasonal) fell through to trees.

### 3. How it was solved

**(a, b)** Mapping verified two ways.

1. **Automated.** At six zoom/pan states (fit, 3×, 12× off-centre, 12× panned,
   about 40×, minimum zoom), 5,000 random screen points each were mapped by
   `toPixel` and, independently, from the browser's own layout of the transformed
   image. Before the border fix, a hidden-pane run disagreed at every point. After
   it: 0 of 30,000 mismatches, with the largest continuous offset 6×10⁻⁶ px.
2. **Real mouse clicks on known pixels.** Results:

   | View | Target | Server received |
   |---|---|---|
   | 6×, lake centred by eye | Lake, rows 420–436, cols 113–145, centroid (427, 129) | (427, 130); grew 302 px against the lake's 300 |
   | 20×, panned off-centre | Pixel centre (421, 118) | (421, 118) |
   | 3×, panned to the top-left | (56, 93) | (56, 93) |
   | Fit | Lake centroid | (428, 129). At fit one image pixel is about half a screenshot pixel, so ±1 is the targeting limit. |

   A drag pans and does not count as a click.

**(c)** Renamed the container class to `.zview`.

**(d)** Number keys and Esc wait for the in-flight click (`settled()`). Tested by
firing a click and the key with no delay: the assignment landed on the right
selection, and Esc stayed cleared.

**(e)** Amplitude is now a trimmed range: the 85th minus the 15th percentile of
monthly NDVI. The yearly max stays a plain max, because cloud only pulls NDVI down.
The Amazon forest median fell from 0.31 to 0.13, while Iowa farmland stayed high
(0.59).

**(f)** Cropland now needs a big swing **and** a low point below 0.35. Farmland
mostly bottoms out below 0.3 (Iowa 75th percentile 0.23, Punjab 0.25, Pampas
0.30); forests stay around 0.4–0.55.

**(g)** Below NDVI max 0.15 the suggestion is always **"6 bare or 2 built-up,
borderline"**. Bare comes first because desert covers far more of the study area
than cities. Texture decides, so the eye decides.

**(h)** No firm rule. Built-up is offered only as the **runner-up** for grass or
trees when NDBI > 0 and the amplitude is low.

**(i)** Steady green is called trees only if the yearly peak is at least 0.5;
below that it is grass.

**Measured against his own hand labels** (33 zones of 50 px or more, in Amazon,
Arabia and Mannheim):

- The suggestion's first choice matched his class in **17** zones.
- Its second choice matched in **9** more.
- **7** were misses, all in Amazon:
  - 6 zones he labelled built-up have yearly NDVI peaks of 0.3–0.76, several
    flagged "mixed selection". One of them is 88,836 px.
  - 1 zone of 55 px labelled water has a yearly NDVI peak of 0.73.

These disagreements are worth a second look by him; the suggester can't say who is
right. A region-wide sanity check from a 6×6 grid of seeds gave the expected
dominant answers: Iowa and Punjab cropland, Oregon and Finland trees, Mongolia
grass, Arabia "bare or built-up".

**Known limitations, for the report:**

- European small-field farmland at 50 m often reads as "trees / cropland,
  borderline", because mixed pixels keep the low point green.
- Egypt's Nile valley, cropped twice a year and rarely bare, reads as "trees /
  cropland".
- Built-up versus bare is never decided by the indices.

**Why this does not compromise "label it yourself".** It reads only the Sentinel-2
images he is already looking at. It is a fixed formula, not a trained model. He
confirms every zone. It is a measuring instrument, like a ruler.

## Phase 1d — hover readout, go-to pixel, undo (26 October 2026)

Requested after real labelling (Amazon, Arabia, Cairo, Delhi, Egypt desert),
relayed by the ECHOSCAPE session.

### 1. Initial build

- **Hover readout** in the bottom-left corner of the optical pane. It shows
  row/col under the cursor as it moves, over either pane. Once the pointer rests
  on a pixel for 120 ms it adds that pixel's current class and its annual index
  values (`GET /api/probe/{region}/{row}/{col}`).
- **Go to row, col.** A text box in the legend accepts "210, 71" or "(210, 71)".
  It centres that pixel at 6× zoom or more and flashes a ring on both panes. This
  lets analysis output ("your biggest mislabelled zone is at (210, 71)") be found
  on screen instead of by eye.
- **Undo** on Ctrl+Z, 20 levels deep (`POST /api/undo/{region}`).
  - Each assign stores a full snapshot of the mask before it, 360 KB each.
  - One undo reverses one class key, **including every zone that key labelled**.
  - The history lives in server memory, so restarting the server starts a fresh
    one.
- **Undo is logged as its own event,** recording what it reversed: class, zones,
  pixels, the suggestion at the time and when it was assigned. It also records
  `restored_px` and `levels_left`. Undos per assignment are an error-rate measure
  for Phase 5, comparing manual and assisted mode.
- `0` is now described as "erase to unlabelled". Before, it was labelled "undo",
  which it never was.

### 2. Issues faced

**(a) A second mapping would invite disagreement.** If the hover readout or go-to
computed screen positions its own way, it could disagree with where clicks land.

**(b) Ctrl+Z would have zoomed in.** Plain `z` is zoom-in, and the key handler
looked at the letter, not the modifier.

**(c) Typing coordinates fired labelling shortcuts.** Typing "2" in the go-to box
would have been taken as "assign class 2".

**(d) Undo had to stay grid-safe.** Undo rewrites the label file, so writing it any
other way than the normal save would risk breaking the grid guarantee.

**(e) Partial failure.** A failed write must not leave the mask in memory
different from the file.

**(f) The test tool's coordinates were inconsistent.** Its screenshot was scaled
about 1.26× while its pointer mapped 1.92× across and 1.43× down. A first hover
"on the marker" reported (436, 156) instead of (427, 129).

### 3. How it was solved

**(a)** One function, `toPixel(clientX, clientY, pane)`, serves clicks, hover and
go-to. The go-to marker is drawn *inside* the zoom container in image units, so
the same CSS transform places it.

**(b)** The Ctrl/Cmd+Z check comes first; any other Ctrl/Alt combination is left to
the browser.

**(c)** The key handler ignores events from text inputs. Enter in the go-to box
runs it and hands focus back.

**(d)** Undo writes through `core.save_mask`, with its round-trip check of CRS,
transform, size and content.

**(e)** The restored mask replaces the live one only after that save has
succeeded.

**(f)** Diagnosed before believing it: the browser logged the pointer at page
position (486, 499), and inverting the transform by hand for that point gives
(436.6, 156.6). The readout was right; the tool's frame was off. With the
pointer aimed in the tool's own frame, it landed at page position (319, 443),
the marker's computed centre.

**Verified** on the scratch copy of Mannheim, port 8001, with a scratch log:

- **Go-to.** Typing "(427, 129)", the lake centroid, and pressing Enter put the
  ring in the middle of the lake on both panes.
- **Hover.** A real hover on the ring read **row 427, col 129**, unlabelled,
  NDWI 0.35, NDVI max 0.02, which is water. Hovering the same spot on the radar
  pane read the same.
- **Undo scenario:**
  1. Label the lake water.
  2. Label two zones together as cropland.
  3. Overwrite the lake with grass by mistake.

  Real **Ctrl+Z** brought the lake back to **water**, restored rather than
  erased, and did not zoom. A second Ctrl+Z took back **both cropland zones
  together** (`zones: 2`, 30,108 px). The file on disk, reloaded through the grid
  check, then held only the lake as water.
- Undoing past the start of history returns `ok: false`. Probing a pixel outside
  the image returns HTTP 400.

Still open: `+`/`-` doesn't regrow the current selection.

## Phase 1e — month picker, snow warning, fine mode (26 October 2026)

### 1. Initial build

- **Month picker** in the legend: a dropdown listing every month as
  `YYYY-MM  NDVI 0.80  bright 0.025  100% clear`, with markers.
  - Markers are **clearest** (most cloud-free, the default on open),
    **greenest** (highest median NDVI, shown when it is at least 0.3) and
    **SNOW?**.
  - Changing month by picker or `n`/`p` still drops the pending selection,
    because it was grown on the other month's pixels. A toast now says so.
- **Snow flag** (`month_summaries` in `server.py`): median NDVI below 0.15 *and*
  median visible brightness more than 2.5× the region's greenest month. When a
  flagged month is on screen, a red warning reads "probably SNOW this month —
  pale cyan here is not a city".
- **Built-up legend text** changed from "cyan, pale, white" to "cyan / grey,
  street-grid texture (snow looks similar!)".
- **Fine mode** (`d`): no smoothing and a seed from the clicked pixel alone, for
  2–3 px features such as river channels. Logged as `fine` on every click. The
  default stays the same.

### 2. Issues faced

**(a) A real mislabel caused partly by the tool.** Yuvraj labelled 41,167 px of
Finland built-up. The biggest zone (30,630 px) is snow on boreal forest:

| Month | NDVI | Brightness |
|---|---|---|
| January | 0.02 | 0.268 |
| July | 0.71 | 0.046 |
| December | −0.01 | 0.214 |

He had stepped to a winter month with `n`/`p` and lost track of it. The legend's
own description of built-up, "cyan, pale, white", described snow exactly.

**(b) Clearest is not always the most useful month.** Iowa's clearest month is
September (NDVI 0.50, fields senescing); its greenest is August (0.85, full
canopy). Oregon: clearest April, greenest January.

**(c) Thin channels could not be labelled correctly.** Measured on water pixels
whose 5×5 neighbourhood is mostly land (Delhi, Cairo), with the default settings
(5×5 smoothing, 5×5 seed window):

- grown regions were only **6% (Delhi) / 8% (Cairo) water**, because the smoothing
  and the seed window both mix the channel with its banks;
- unsmoothed with a 1-px seed: **75% / 86% water**;
- but some clicks then grow almost nothing (6 and 9 of 60 seeds), and big zones
  need the smoothing.

Delhi's clearest month has only **31** water pixels by NDWI at all, so most of
its river is mixed pixels at 50 m. That is consistent with the ECHOSCAPE session
measuring only 18% overlap between his Delhi water labels and real water.

### 3. How it was solved

**(a)** The month is now visible and choosable, with NDVI, brightness and
clear-share beside it, and snow is flagged before anything is labelled. Checked
on all regions with snow: the flag fires on exactly the winter months (Finland
Jan, Dec; Iowa Jan, Feb; Oregon Dec; Mongolia Jan, Dec) and never on Arabia,
which is bright all year.

**(b)** Both markers are shown and the human chooses. The default on open stays
"clearest".

**(c)** Fine mode as an opt-in, not a new default. In the browser on a copy of
Cairo, a click on a channel pixel at (6, 420) grew **96,595 px** in normal mode,
the whole surrounding area, against **20 px**, 85% of it water, in fine mode.

**Verified** on scratch copies of Finland and Cairo, port 8001, with a scratch log:

- Picking January with a 93,357 px selection pending switched the image, cleared
  the selection on screen and on the server (logged `clear`), showed the toast and
  showed the snow warning.
- `n` then moved to February, and the picker followed.

Also noted on 24 Oct: a `.venv311` now exists in this folder, with Python 3.11,
torch 2.14.1, torchvision, FastAPI, rasterio, scipy and matplotlib. That is the
Phase 0 environment for the web app.

---

# Direction change — photo annotator first (17 November 2026)

## 1. What changed

The Deep Learning project was submitted, so this project now gets the attention.
The brief was compared against what existed, and Yuvraj decided:

- **Build the photo annotator first.** It covers upload, boxes and polygons,
  pretrained computer-vision models, standard export, and evidence on COCO.
- **Keep the satellite mode as an archive.** It moved intact to
  `archive/satellite/`, with its own README and its click log. It may return as a
  second image type if there is time.
- **Measure the evidence on a COCO val2017 subset.**

## 2. Issues faced

**(a) The October tool met the brief only partly.**

| Requirement | Status in October |
|---|---|
| Labelling | Worked, but only on the Deep Learning project's satellite files, read from a fixed folder |
| Upload | None |
| Standard export | None, only GeoTIFF masks |
| Assistance | A fixed index formula (NDVI / NDWI / NDBI). A marker could fairly say that is not a computer vision model. |

**(b) The October log cannot serve as evidence.** It holds 1,604 assignments and 24
undos (24–29 Oct), but:

- Only **56** assignments were made without the suggestion, in the first hours,
  with an earlier version of the tool. That is not a fair manual baseline.
- The suggestion matched the final class in 527 assignments (34%), was the
  runner-up in 332, and missed in 689.
- The hand-labelled masks were removed from ECHOSCAPE on 6 Nov as inaccurate, so
  none of these assignments can be scored against ground truth.

## 3. How it was solved

- The evidence will be measured where ground truth exists: COCO val2017.
- Model quality is measured automatically (Phase 5a); effort is measured in
  controlled manual versus assisted sessions in the new app (Phase 5b).
- The October log stays in the archive as a record of real use, including which
  features real labelling demanded: multi-zone selection, undo, go-to,
  snow-aware month choice and fine mode.

What carries over into the photo app as *ideas*, not code:

- one screen-to-image mapping, used by every tool;
- a canvas with no border or padding, because the October tool had a 1px offset
  from that;
- the interaction log from the first session;
- undo that reverses one user action;
- logging assisted mode separately.

---

# Phase 1 (photo) — Manual annotation core, with Phase 2 export

*17 November 2026: code written, **not yet run**. Yuvraj runs it.*

## 1. Initial build

**Back end** (`app/`):

- `server.py`: FastAPI routes; `--data` and `--port` so tests use a scratch folder.
- `store.py`: SQLite (classes, images, annotations) plus image files.
  - Geometry is validated, clamped to the image, and must be at least one pixel.
  - EXIF rotation is applied once on upload.
- `export.py`: one zip with COCO JSON, YOLO detection and segmentation labels,
  PNG masks and the images, under the same name in every format.
- `events.py`: an append-only JSONL interaction log.

**Front end** (`app/static/`): plain JavaScript on one canvas.

- Box, polygon and select tools. Shapes can be moved, and box corners and polygon
  vertices dragged.
- Classes on keys 1–9; new classes can be added.
- Undo per image; zoom at the cursor; pan with right-drag or Space+drag.
- Image list, upload by button or drag-and-drop, delete.
- Every interaction is logged, tagged manual or assisted.

## 2. Issues faced

Found by reading the code back before handing it over (nothing has been run):

**(a) Re-classing the wrong shape.** A newly drawn shape became the selection,
and number keys re-class the selection. So pressing "2" to pick the class for the
*next* object silently changed the object just drawn.

**(b) Box corner drag jumped.** The "opposite corner" was recomputed from the box
on every mouse move. Once the dragged corner crossed the opposite one, the box
flipped and the drag jumped.

**(c) Shapes were lost when no class was picked.** Starting a shape with no class
selected only failed at save time, after the drawing was done, and the drawing was
thrown away.

**(d) Image format after rotation.** `ImageOps.exif_transpose` returns a new image
without a `format`, so the JPEG-vs-PNG decision read the format too late.

## 3. How it was solved

**(a)** Number keys re-class only in the Select tool. In the drawing tools they
choose the class for the next shape, and new shapes are no longer auto-selected.

**(b)** The opposite corner is fixed when the drag starts (`anchor`).

**(c)** The drawing tools refuse to start without a class, and say why.

**(d)** The format is read before the rotation is applied.

---

# Phase 3 — AI assist: click-to-segment

*17 November 2026: code written, **not yet run**. Yuvraj runs it.*

## 1. Initial build

**Model:** MobileSAM, loaded through Ultralytics (`app/models.py`, class
`ClickSegmenter`).

- **Encode once per image.** When an image opens in assisted mode, the browser
  calls `/api/ai/prepare`. The image encoder runs once and its embedding is
  cached for that image.
- **Decode per prompt.** Each click or box calls `/api/ai/segment`, which runs
  only the prompt decoder on the cached embedding.
- **Prompts:**
  - All clicks on one proposal go to SAM together, as one object
    (shape `(1, k, 2)`).
  - Left-click means "object" (label 1); right-click means "not object" (label 0).
  - A drag gives a box prompt. Clicks after a box refine it.
- **One click asks for three masks.** A single click is ambiguous (the shirt, or
  the whole person?), so it requests SAM's three candidate masks and keeps the
  best-scored, as the SAM paper recommends. With more prompts, it asks for one.
- **Mask to polygon** (`mask_to_polygon`):
  1. Keep only the largest connected piece; ignore holes, as COCO polygons do.
  2. Simplify with Douglas-Peucker to about 1 px, or 0.2% of the perimeter.
  3. Shift vertices +0.5 px to pixel centres.
- **UI:** the **AI outline** tool (`A`) exists only in **assisted** mode. Manual
  mode disables it completely, so manual sessions stay an honest baseline.
  - The proposal is drawn dashed, with green/red click markers and the box in
    yellow.
  - Enter accepts it as a polygon with `source = "sam"`. Esc discards it.
    Backspace takes back the last prompt.
  - An accepted polygon is an ordinary annotation: editable in Select, undoable.
- **Logging:**
  - Browser: `ai_ready` (encode time), `ai_click`, `ai_box`, `ai_result`
    (round-trip ms, SAM score, vertices), `ai_accept` (prompts used, ms from the
    first prompt), `ai_discard`.
  - Server: `ai_prepare`, `ai_segment`, `ai_error`.
- **Model failures don't break the manual tool.** If the model won't load
  (no weights, no internet for the first download, a torch error), the AI routes
  answer HTTP 503 with the reason, and the manual tools keep working. The model
  is imported only on first use.
- `--sam sam2.1_t.pt` switches to SAM 2.1-tiny, for a comparison in Phase 5.

## 2. Issues faced

Found while reading the installed Ultralytics source (8.4.187) before writing the
wrapper:

**(a) Low-scoring masks vanish silently.** Ultralytics' SAM `postprocess` drops
every mask whose predicted score is at or below `conf`, which defaults to 0.25. A
low-confidence click would return *nothing*, which looks like a bug rather than
"the model is unsure".

**(b) Prompt shape decides what SAM thinks the clicks mean.** Points shaped
`(k, 2)` are read as *k separate objects*, one click each. Only `(1, k, 2)` means
k clicks on *one* object. With the wrong shape, a negative click would become its
own "object" instead of correcting the first.

## 3. How it was solved

**(a)** `conf=0.0`, so SAM's answer always comes back, with its own score shown
in the status bar and the log.

**(b)** Clicks are always sent nested as one object (`[[...clicks...]]`, labels
`[[...]]`). Confirmed against `_prepare_prompts` in the installed source.

## First real use — 17 November 2026

Yuvraj uploaded the 17 practice images, labelled two of them by hand, tried the AI
outline, and exported. Feedback and log, read back afterwards:

### 2. Issues faced

**(c) "It takes too long": 61 s before anything appeared.**

- The log's single `ai_prepare` took **61,184 ms** on the CPU.
- That one wait paid for the 40 MB weight download (`mobile_sam.pt`, saved at
  14:53), the model build, torch's first-run setup *and* the real image encode,
  all while he waited.
- Once ready, each click took **0.27–0.53 s** (5 `ai_segment` events).

The slow part was getting started, not answering clicks.

**(d) Five plain clicks on five different objects became one object.**

- The clicks landed at x = 126, 265, 793, 517, 30.
- Every click was added to the same proposal, so SAM was asked for one object
  covering all five spots. The masks grew to 270–290k px, nearly the whole
  1080×810 image.
- He gave up and switched to manual mode after about 70 s. The answers, which
  arrived only after the 61 s encode, were thrown away.

The tool's rule ("every click refines one object") did not match how a user
naturally clicks: one object per click.

**(e) "Should be able to add as many classes as the user wants."**

- Adding already worked: he had 12 classes.
- But only the first nine had keys, and the add box only added. With 12 or more
  classes there was no quick way to reach the rest.

**(f) Export check.**

- All 21 annotations were exported, and every one was a manual box.
- COCO and YOLO agree for every box, to within 0.0004 px.
- Drawn back onto the images, every box sits on the intended object.
- All masks are empty, which is correct: boxes have no outline. Masks fill only
  from polygons and AI outlines.
- **One near-duplicate:** the bus image has 5 "person" boxes for 4 people. The
  bearded man has two almost identical boxes.

### 3. How it was solved

**(c)** The model loads **in the background when the server starts** (`warm_up`):
it loads the weights and encodes a blank 64×64 image once. Opening an image now
costs only the real encode.

- The terminal prints the load time. The log records `ai_load` (load time)
  separately from `ai_prepare` (encode time), so the two can be reported apart.
- A banner on the image says what the AI is doing ("loading the AI model",
  "reading this image", "outlining").
- **Not yet measured:** the encode time on its own. It appears in the log on the
  next run.
- The CUDA question is open; see `tech.md`.

**(d)** New click rules:

- A **plain click or a drag = a new object.** The previous outline, if finished,
  is saved automatically.
- **Shift+click** adds to the current object; **right-click** removes from it.
- New objects start strictly one after another, so quick clicks during a slow
  answer cannot lose an object.
- The open outline remembers its class; a number key pressed while it is open
  re-classes it.
- `ai_accept` now records `how` (`enter` or `auto`). `ai_click` records `add`.

**(e)** Any number of classes, reachable by keyboard:

- **1–9 and 0** pick the first ten.
- **/** focuses a **find-or-add** box: typing filters the class list; Enter picks
  the exact or only match, or adds the typed name as a new class.

**(f)** A **duplicate warning**. When a new annotation's bounding box overlaps one
of the same class by IoU > 0.85, a warning says so; Ctrl+Z removes it. It is not
blocked, because touching objects can legitimately overlap that much. The log
records `duplicate_of`.

`GUIDE.md` was added: how the AI-assisted annotation works, for the user and the
report.

---

# Phase 4 — AI assist: auto-suggest, two detectors, and the UI redesign

*17 November 2026: code written, **not yet run**. Yuvraj runs it.*

## 1. Initial build

**Two detectors, chosen in the UI** (`app/models.py`, class `Detector`). Both
load through Ultralytics, so the evaluation can compare them on the same images.

| | YOLO11n (`yolo11n.pt`) | YOLOE-11s (`yoloe-11s-seg.pt`) |
|---|---|---|
| Classes | The 80 COCO classes only | Whatever class names the user has (open vocabulary) |
| How the user's classes are used | Mapped to COCO names: exact match ignoring case, or a short synonym list (table → dining table, sofa → couch, phone → cell phone, ...). Classes with no COCO match are reported as "cannot suggest". | Passed as text prompts with `set_classes`. Text embeddings are recomputed only when the class list changes. |
| Trade-off | Fast; more accurate on COCO's own classes | Covers custom classes; slower; more false alarms on vague names |

- **Detect once, filter instantly.** Each run uses a confidence floor of 0.15. The
  slider filters what is shown (default 35%), so moving it is instant.
- **No double labels.** A suggestion is hidden if an annotation of the same class
  already overlaps it by IoU > 0.7, so accepting or re-running never doubles a
  label.
- **Accepting runs SAM.** Accepting a suggestion sends its box to SAM, which turns
  it into an outline (`source = "yolo+sam"`). If SAM is unavailable, the box is
  saved instead (`source = "yolo"`).
- **Interaction.** It works in the AI outline tool:
  - click a suggestion to accept it; right-click to reject it;
  - **S** suggests, **Shift+Enter** accepts all;
  - the panel lists suggestions with Accept and × buttons;
  - "Suggest when a photo opens" is on by default.
- **Background warm-up.** At server start, SAM loads first, then both detectors,
  in the background. The terminal prints each load time.
- **Routes:** `GET /api/ai/detectors` (list and state), `POST /api/ai/detect`.
- **Logging:**
  - Browser: `sug_run` (model, why, how many found / shown, ms, unsupported
    classes), `sug_accept` (how: click / list / all; outlined or box),
    `sug_reject`, `sug_accept_all`, `sug_conf`, `sug_auto`, `det_change`.
  - Server: `ai_detect`.

**UI redesign: a "light table" workbench.** It was designed with the
frontend-design skill:

- **The concept.** A photographer's light table. Dark slate chrome recedes; the
  photo lies on a lit, neutral grey light box with a faint dot grid. It casts a
  soft shadow and has registration marks at its corners. The brand mark is the
  same registration corner.
- **One rule for colour.** Anything the AI proposes — suggestions, the outline in
  progress, the AI tool and the Suggestions panel — is drawn in china-marker
  yellow (`#f4c21b`). Human actions (active tool, focus, Export) are cobalt.
  Model output can never be mistaken for a saved label.
- **Type.** IBM Plex Sans Condensed for labels and controls, IBM Plex Sans for
  text, IBM Plex Mono for data (coordinates, scores, counts).
- **Controls.**
  - Tools and the Manual / Assisted mode are segmented controls with their keys
    shown.
  - The image list has thumbnails, like frames on a contact sheet, plus label
    counts and a drop card.
  - The right side has cards: Classes, Suggestions, Annotations, and a
    collapsible key list.
  - The empty stage invites dropping photos.
- **Quality floor.** Visible keyboard focus; reduced motion respected; below
  980 px wide the image strip hides so the photo stays usable.

## 2. Issues faced

**(a) A slip in the previous fix.** When the model warm-up was added, the code that
seeds the starter classes ended up inside the background warm-up instead of
`configure`. On a fresh project the first page load could have shown no classes,
until SAM finished loading. Found while adding the detectors.

**(b) YOLO11n cannot see most of the user's own classes.** It covers 6 of his 12
(person, car, dog, cat, TV, chair) directly. Table maps only through a synonym
(dining table). Cupboard, lamp, mirror, vase and bed have no COCO
counterpart, or a different name. Silently suggesting nothing for them would look
like a broken model.

## 3. How it was solved

**(a)** Seeding is back in `configure`, before any request is served.

**(b)** The detector reports which classes it cannot suggest, and the panel says
so ("this detector cannot suggest: Cupboard, Lamp, ..."). That is also the
practical argument for YOLOE, and the comparison the evaluation can show.

---

# Phase 4b — Class picker and AI transparency (25 November 2026)

*Code written, **not yet run**. Yuvraj runs it.*

## 1. Initial build

Prompted by a question Yuvraj raised: *the user cannot see which classes the AI
knows, and the AI sometimes suggests things the user never asked for.* The design
combines his idea (choose classes first, add more while labelling) with mine
(make the AI's reach visible, and stop it guessing).

- **A class picker opens on a new project**, or from "Edit classes".
  - The 80 classes YOLO11n knows are shown as chips in COCO's ten groups.
    Quick sets: Vehicles, Indoor, Animals, All 80.
  - Any other name can be typed in.
  - Each chosen class can be renamed or removed.
- **No starter classes.** A new project starts empty.
- **Coverage badges** on every class, in the picker and the Classes panel:
  - `11n` lit = YOLO11n can suggest it. When it uses its own name for it, the
    class shows "table = dining table".
  - `E` = YOLOE can suggest it (always: it reads names).
  - Tooltips explain each badge.
- **Decoy names for YOLOE.** The COCO names the user has *not* chosen are added as
  extra prompts. Any detection whose best name is a decoy is dropped from the
  suggestions. Non-maximum suppression runs class-agnostic, so one object gets
  one name.
- **An "ignored" line** in the Suggestions panel: *"Ignored, not in your classes:
  dog ×2, cat"*, with "+ dog" buttons that add the class.
- **Mapped names on suggestions**, in the tag and the list: `table (dining table)
  82%`.
- **Adding, removing or renaming a class mid-way** refreshes the badges. In
  assisted mode it re-runs suggestions on the photo on screen, so a new class is
  looked for at once.
- **Server:** `GET /api/classes/coverage`, `GET /api/ai/catalogue`,
  `PUT /api/classes/{id}` (rename).
  - `/api/ai/detect` now also returns `ignored` and, per suggestion,
    `matched_as`.
  - `models.py` gains `COCO_GROUPS`, `coco_match`, `yoloe_decoys` and
    `coverage`.
- **Logging:** `class_add` (with where it came from: picker, quick set, typed,
  find-or-add box, ignored line), `class_delete`, `class_rename`, `picker_open`
  and `picker_close`, `picker_set`. Server: `ai_detect` gains `n_ignored`.

## 2. Issues faced

**(a) Surprise suggestions came from the starter classes.** Every new project was
seeded with person, car, dog and cat. The AI then rightly suggested dogs to a user
labelling only cars and chairs. The filter worked; the class list was not the
user's.

**(b) YOLOE's forced choice.** Given only "car, bike, table, chair", YOLOE has no
word for a dog. It can return the dog as "chair" with a middling score: a wrong
suggestion with a believable name. YOLO11n never had this problem, because it
always knew its own 80 classes and the app simply did not show the unwanted ones.

**(c) The AI's reach was invisible.** The panel only said which classes a
detector *could not* suggest, after a run. Nothing showed what it *could* do
before labelling started.

**(d) The evaluation must not change.** The Phase 5 notebook asks YOLOE for all
80 COCO names. Decoys must not alter that measurement.

## 3. How it was solved

**(a)** No seeding. The picker opens on an empty project, so the user's first
act is to decide the label set.

**(b)** Decoys. With "dog" available as a prompt, the dog is named a dog and then
dropped (and reported in the ignored line). Class-agnostic NMS stops the same box
coming back under two names.

**(c)** Coverage badges, the "= COCO name" notes, the grouped catalogue and the
ignored line. The AI's vocabulary and its choices are visible before and during
labelling.

**(d)** Decoys are only the COCO names the user has *not* chosen. Asked for all
80, there are none, and agnostic NMS stays off, so the notebook measures exactly
the same detector as before.

---

# Phase 4c — Model turn-taking (25 November 2026)

Found in the balanced effort study and fixed straight after it: SAM's encode and
YOLOE's detection ran side by side and slowed each other down. One lock now
serialises all model work. The full account (measurements, fix, why the study
numbers stay as measured) is in **Phase 5, §4 Results**, where it was found.
Confirmed working by Yuvraj on 25 Nov.

---

# Phase 4d — Projects and a home page (25 November 2026)

*Written and run by Yuvraj on 25 Nov. Built after the study, so the study
measured the single-project app.*

## 1. Initial build

Yuvraj's request: the app should flow like a product, **home page → new project
→ choose classes → labelling**, instead of opening straight onto one fixed set of
photos.

- **Home page (`#/`).** One card per project: thumbnail, name, "photos labelled
  / photos" with a progress bar, label count, its classes as coloured chips,
  when it was last opened, Rename and Delete. A dashed "New project" card leads
  the grid; **N** also starts one.
- **New project, in three steps.** (1) A name dialog. (2) The existing class
  picker opens by itself, because the project has no classes; its button reads
  "Next: add photos". (3) That click opens the file chooser. Then labelling.
- **Workspace (`#/p/<id>`).** The header shows `Projects › <name>`; both
  "Projects" and the logo lead home. Each view has its own address, so the
  browser's Back button works.
- **Storage: one folder per project.** `app/projects.py` keeps a registry,
  `<data>/projects.json`. A project is `<data>/projects/<id>/` with exactly the
  old layout (`annotator.db`, `images/`, `logs/events.jsonl`), so `Store` and
  `EventLog` did not change.
- **Old data is kept where it is.** A data folder from before projects
  (`annotator.db` directly inside it) is registered as "My first project" with
  folder `.`. The evaluation notebooks read `data_study/` and `data_study2/`
  directly, so they are unaffected. That project can be renamed, not deleted.
- **Delete = move to `<data>/trash/<id>-<time>/`**, after a confirm that says how
  many photos and labels it holds. Nothing is erased.
- **Server.** One project is open at a time. Opening swaps the store and the log;
  the models stay loaded. Routes: `GET/POST /api/projects`,
  `PUT/DELETE /api/projects/{id}`, `POST /api/projects/{id}/open`,
  `POST /api/projects/close`, `GET /api/projects/{id}/thumb`. `/api/state` now
  also returns the project. The export zip is named after the project.
- **Logging.** `project_open`, `project_leave` (browser); `project_open`,
  `project_create`, `project_delete` (server). Model loading while no project is
  open goes to `<data>/logs/server.jsonl`.

## 2. Issues faced

Found while designing it, before writing code:

**(a) Image ids restart at 1 in every project.** Three consequences:
- The browser cache could show project A's photo 3 when project B's photo 3 is
  opened, since the URL `/api/images/3/file` is the same.
- A slow AI answer (an accepted suggestion being outlined) arriving after the
  user switched projects could be saved into the new project's photo 3.
- SAM's cached image embedding could be reused for the wrong photo.

**(b) Events in flight.** Events queued in the browser when the user leaves a
project would be sent after the switch and land in the next project's log.

**(c) The server reopens the last project at start**, for the detectors'
warm-up, but the browser now starts on the home page.

## 3. How it was solved

**(a)**
- Image URLs carry the project (`?p=<id>`), so the cache keys differ.
- Every browser call sends an `X-Project` header. A server middleware refuses
  (409) any call naming a project that is no longer open. Nothing can be saved
  into the wrong project, and a second tab on another project gets a clear
  message instead of silently writing.
- SAM's cache was already keyed by the image's file path
  (`projects/1/images/3.jpg` vs `projects/2/images/3.jpg`), so it was safe as it
  was. Checked in `models.py`.

**(b)** Leaving a project logs `image_leave` and `project_leave`, then **waits for
the event queue to flush** before the server switches.

**(c)** The home page tells the server to close the project, so nothing done on
the home page is logged into a project.

**Limit:** one project open at a time (single-user local tool).

---

# Phase 4e — Kontur: name, look, folders, motion (25 November 2026)

*Written and run by Yuvraj on 25 Nov.*

## 1. Initial build

Yuvraj's five requests: a more attractive UI, a delete option on every project
card, upload of photos **and folders**, a better name, and animations.

- **The name: Kontur.** German for *outline*, which is what the tool does: the
  model traces the outline, you decide. Short and easy to say in English and
  German. Used in the header wordmark, page titles, the export and the server.
- **Look.** The light-table identity stays (slate chrome, lit grey table, yellow =
  AI proposes, cobalt = you decide). Added a condensed display face,
  **Big Shoulders Display**, used only for the wordmark, headings and project
  names.
  - **Home hero.** The headline "Point at it. The model traces it. You decide.",
    with "the model traces it" in yellow on a marching dashed underline.
  - **The signature: a looping demo** next to the headline, on a 6 s loop. A
    photo of a mug on the light table: a cobalt click lands, a yellow outline
    traces the mug, it becomes marching ants, then fills cobalt with a
    "mug · saved" tag. A caption lights up *click → trace → save* in step. It
    shows what the app does without a word of explanation.
  - **Project cards.** A contact-sheet mosaic of up to 4 of the project's photos,
    the name in the display face, labelled-photo progress bar, class chips, an
    "all labelled" badge, and "Open →" on hover.
- **Delete on every card.** A trash button (and a rename button) on every card's
  photo, including the pre-projects project. That one moves its database,
  photos and log out of the data folder into `trash/`, and the confirm says so.
- **Photos and folders.**
  - The header has **Add photos** and **Add folder** (folder picker, subfolders
    included); the image strip has the same two buttons.
  - **Drag and drop** takes photos, folders, or both: folders are walked
    recursively.
  - Only photos are kept (by type or extension: jpg, png, webp, bmp, gif, tif);
    other files are counted and reported as skipped.
  - Uploads go in **batches of 12** with a progress bar ("Adding photos 36 / 120"),
    so a big folder doesn't become one huge request.
  - A photo from a folder keeps its folder path as its name (`trip/day1/a.jpg`);
    the export already makes names filesystem-safe.
- **Animations**, each tied to meaning rather than decoration:
  - The hero demo, and the hero lines rising in sequence on load.
  - Cards enter in a short stagger; progress bars fill; on hover a card lifts and
    gets the AI's **marching-ants** outline; a deleted card shrinks away.
  - **On the canvas, everything the AI proposes now marches**: suggestion boxes
    and the open SAM outline have a slowly moving dashed edge, so "not saved yet"
    reads at a glance. Accepted labels stay still.
  - A full-window drop zone with a marching border while dragging files in;
    dialogs pop in; views fade in when switching.
  - **Reduced motion respected:** with the system setting on, every animation is
    off and the demo shows its final frame.

## 2. Issues faced

**(a) Animations can freeze hover effects.** A CSS entrance animation with
`fill-mode: both` keeps its end state (`transform: none`) above normal rules, so
the card's hover lift would never show.

**(b) Dropped folders.** `dataTransfer.files` lists a dropped folder as a single
empty "file". Reading a directory entry returns at most about 100 entries per
call.

**(c) The canvas has no animation loop.** It redraws only on events, so dashed
edges could not move.

**(d) Folder pickers return everything**, including `.txt`, `.json` and system
files such as `Thumbs.db`.

## 3. How it was solved

**(a)** The card entrance uses `fill-mode: backwards`: it holds the start state
during its delay, then lets go.

**(b)** Drops are read through `webkitGetAsEntry()`. Folders are walked
recursively, calling `readEntries()` until it returns nothing.

**(c)** A small `requestAnimationFrame` loop redraws at about 25 frames a second,
**only** while a suggestion or an open outline is on screen, the tab is
visible, nothing is being dragged, and reduced motion is off. Otherwise it costs
nothing.

**(d)** Files are filtered by image type or extension before upload, and the
toast says how many were skipped.

---

# Phase 4f — Export: choose the formats (25 November 2026)

*Written and run by Yuvraj on 25 Nov ("looks fine").*

## 1. Initial build

Yuvraj's request: when exporting, let the user choose the format.

- **The Export button opens a dialog** with six format tiles. Each says what it
  holds and what it is for:

  | Format | Holds | For |
  |---|---|---|
  | COCO JSON | boxes and outlines | Detectron2, MMDetection, pycocotools |
  | YOLO detection | boxes | training Ultralytics YOLO detectors |
  | YOLO segmentation | outlines only | training YOLO segmentation models |
  | Pascal VOC XML | boxes | TensorFlow Object Detection, older detectors |
  | PNG masks | outlines only | semantic segmentation (U-Net, DeepLab) |
  | CSV table | boxes and outlines | spreadsheets, quick analysis |

- **Two options:** include the photos (default on), and export only photos that
  have labels.
- The dialog shows how many photos and labels will go out, and warns before the
  download when a choice will drop something: YOLO without photos cannot train,
  and outline formats skip boxes. The download button names the format when only
  one is ticked.
- **The choice is remembered** in the browser for the next export (localStorage,
  with a fallback when storage is blocked).
- **Server:** `GET /api/export?formats=...&images=...&only_labelled=...`;
  `GET /api/export/formats`. No `formats` still means every format. The zip is
  named `<project>_<format>.zip`, or `<project>_export.zip` for several. Its
  `README.txt` lists only what is inside, with the photo and label counts. The
  `export` log event records the formats and options.
- **New formats:** Pascal VOC (one XML per photo, whole-pixel 1-based boxes, as
  VOC defines them) and CSV (one row per label, with the box and the outline
  points).

## 2. Issues faced

**(a) The old YOLO segmentation labels could not be trained on directly.** They
were in `yolo/labels-seg/` next to the detection labels. Ultralytics finds a
photo's labels by replacing `images/` with `labels/` in its path, so it would
always have read the detection boxes.

**(b) Outline formats and box labels.** A box has no outline, so YOLO
segmentation and the PNG masks cannot hold it. Leaving it out silently looks
like lost data.

## 3. How it was solved

**(a)** Each YOLO format is now its own complete dataset (`yolo-detect/` and
`yolo-segment/`, each with `images/`, `labels/` and `data.yaml`), so either one
can be passed straight to Ultralytics training.

**(b)** The dialog warns before the download, and the zip's `README.txt` says
how many box labels were left out of `yolo-segment/`.

**(c) Later the same day: "why not the images with the boxes?"** Yuvraj asked why
the export gives label files rather than photos with boxes on them. The answer,
for the report: a model trains on the **clean** photo plus the label as numbers.
Boxes burned into the pixels would teach it "objects have coloured rectangles",
remove the numbers it is scored against, and can never be edited again. Drawn-on
photos are still useful for people, so a **7th tile was added: "Photos with
labels drawn"** (`preview/*.jpg`). It draws each label in its class colour
(outlines lightly filled, boxes as rectangles) with a name tag, sized to the
photo, using Pillow's built-in scalable font so nothing depends on Windows
fonts. It spans the dialog's full width with a dashed edge and reads "For
viewing, not training". If it is the only tile ticked, a note suggests adding a
label format. It also gives ready-made figures for the report.

---

# Phase 5 — Evaluation

*25 November 2026: notebooks written, **not yet run**. Yuvraj runs them.*

## 1. Initial build

`eval/evallib.py` holds all the logic. Three notebooks call it:

- **`01_build_eval_set.ipynb`** builds the test sets.
  - It downloads COCO's official val2017 annotations once and keeps
    `instances_val2017.json`.
  - With a fixed seed (2026), it picks two disjoint sets:
    - **100 images** for the automatic model evaluation;
    - **20 images** for the timed study, split into halves A and B with
      balanced object counts. Each image has 1–6 objects of the study classes
      (person, car, bicycle, dog, chair) that are at least 32×32 px, and no
      crowd regions.
  - It downloads only those images and copies the study halves to
    `eval/data/effort/A|B`.
- **`02_model_quality.ipynb`** runs the app's own model code (`app/models.py`):
  - **(A) SAM:** the standard simulated-click protocol from interactive
    segmentation research (RITM, SimpleClick).
    - Click 1 goes at the point deepest inside the object; each next click at
      the deepest point of the largest error, positive or negative.
    - Five clicks per object, up to 300 objects. Records IoU after each click,
      NoC@85 and NoC@90, and the IoU from a ground-truth box prompt, by size.
  - **(B) YOLO11n and YOLOE:**
    - both asked for the 80 COCO names (zero-shot for YOLOE);
    - official COCO box mAP with pycocotools;
    - precision / recall / F1 at the UI's 35%, plus a precision–recall curve
      across the slider;
    - time per image.
  - **(C) YOLO → SAM:** the outline IoU when a correct suggestion is accepted.
  - **(D) Supporting number:** vertices in COCO outlines vs SAM clicks.
- **`03_effort_study.ipynb`** analyses a timed session in which the same person
  labels half A in **manual** mode (polygon tool) and half B in **assisted** mode,
  on a separate data folder (`--data data_study`). From the interaction log and
  the database, per mode:
  - seconds and clicks per correctly found object;
  - found %, mean IoU of the found outlines;
  - wrong labels, undos, AI accepts and rejects.

## 2. Issues faced

**(a) Train/test leakage.** YOLO11n is trained on COCO *train*2017. Measuring it
on images it saw in training would flatter it.

**(b) Practice images.** The 15 images in `data/test_image` are COCO val images
Yuvraj has already labelled. Timing them again would measure memory, not the
tool.

**(c) The models would download again.** Jupyter runs a notebook from its own
folder (`eval/`). Ultralytics looks for weights, and YOLOE's 600 MB text encoder,
in the current folder, so it would download all of them a second time.

**(d) Idle time.** A raw stopwatch counts breaks. "Seconds per object" would then
measure coffee, not labelling.

**(e) Pans counted as work.** A right-press is a pan in most tools, but means
"remove from outline" in the AI tool. Counting every press would inflate the
manual clicks.

**(f) The order effect.** The same person labels both halves, getting faster with
practice.

## 3. How it was solved

**(a)** Only **val**2017 is used, COCO's held-out set.

**(b)** The 15 practice ids are excluded from both subsets (`PRACTICE_IDS`).

**(c)** `E.setup()` switches to the project folder before any model loads.

**(d)** Gaps between logged events are capped at 30 s (`IDLE_CAP_MS`).

**(e)** Effort clicks are left presses, plus right presses **only in the AI
tool** (`is_effort_click`).

**(g) First run of notebook 01 (25 Nov): the zip download was blocked.**
`HTTP Error 403: Forbidden: body content-type denied` on the annotations zip, while
the same URL answered `200 OK` from another machine. The wording is a local network
filter (antivirus web shield or proxy) refusing a `.zip` to Python; the `.jpg`
images were not blocked. Fix: download the zip in a browser into `eval/data/`. The
notebook uses an existing file as it is. `download()` now explains this and names
the exact path, instead of showing a raw traceback.

**(h) First study run (25 Nov): assisted mode showed 0 clicks.** Every assisted
label came from the **Accept all** button, clicked 9 times. The click count only saw
presses on the photo, not on panel buttons. Panel actions in manual mode (class and
tool picks) were missed too. Fix: `panel_actions()` counts panel clicks: class or
tool picks, Accept all, list accept/reject, the Suggest button, detector or
confidence changes. It skips actions already counted as a key press. Notebook 03
now reports **all actions per found object** and **seconds per required object**.

**(f)** Manual runs **first**, so practice helps the manual run, and any measured
saving is an underestimate.

## 4. Results (25 November 2026)

**Model quality** (notebook 02, 100 held-out images):

- **SAM, 300 objects.**
  - Mean IoU by clicks:

    | Clicks | 1 | 2 | 3 | 4 | 5 | box |
    |---|---|---|---|---|---|---|
    | Mean IoU | 0.569 | 0.654 | 0.728 | 0.758 | 0.775 | 0.779 |

  - NoC@85 = 3.45; 52% of objects reach 85% within 5 clicks. NoC@90 = 4.09 (34%).
  - By size, 5 clicks: large 0.83, medium 0.78, small 0.71.
  - Image encode: median 0.83 s. Each click: 0.07 s.
- **Detectors:**

  | | AP | AP50 | Precision @ 35% | Recall @ 35% | False alarms / image | s / image |
  |---|---|---|---|---|---|---|
  | YOLO11n | 0.488 | 0.643 | 0.775 | 0.486 | 0.97 | 0.06 |
  | YOLOE (zero-shot) | 0.441 | 0.607 | 0.702 | 0.448 | 1.31 | 0.19 |

  YOLO11n's 0.488 is above its published full-COCO AP of 0.395. That is the
  variance of a 100-image sample, not a better model.
- **YOLO → SAM:** a correct suggestion's outline scores IoU 0.786 (YOLO11n) or
  0.780 (YOLOE); 71% of them score ≥ 0.75.

**Effort** (notebook 03; one person, 10 + 10 images, manual first):

| | Manual (A) | Assisted (B) |
|---|---|---|
| Objects required | 30 | 26 |
| Found (IoU ≥ 0.5) | 23 (77%) | 17 (65%) |
| Seconds per found object | 24.4 | **8.4** (2.9× faster) |
| Photo clicks per found object | 41.1 | 0 |
| Accept-all presses | none | 9 (about 0.5 per found object) |
| Mean IoU of found objects | 0.765 | **0.784** |
| Wrong labels | 1 | 2 |

**What the effort numbers say:**

- **Faster, same quality.** Assisted labelling was about 3× faster per object, and
  far fewer clicks, with outlines no worse.
- **But fewer objects were found.**
  - Every assisted label was an accepted suggestion. No AI-outline clicks were made
    for objects the detector missed, so assisted coverage is capped by the
    detector's recall (≈ 0.49 at 35%, from notebook 02).
  - On `coco_000000074200` the only required person (≈ 4,100 px) was never
    suggested, and nothing was labelled in 45 s.
- **Accepting without looking let errors through.** On `coco_000000423123` two
  accepted "person" outlines were wrong. One was SAM outlining the person's
  **backpack** from the person's box (IoU 0.58 with the backpack); the other covered
  a quarter of a person (IoU 0.25). Both went in through **Accept all**, with no
  check.
- **Design implication.** This is automation bias, and it is a finding of the
  study. The assisted workflow should push the user to look for missed objects
  (the AI outline tool covers them) and to check each accepted outline. Possible
  changes: accept one by one; flag low-SAM-score outlines; show "N objects
  suggested, check for more".
- **The class mix was unbalanced** (found by Yuvraj after the run). The images had
  been drawn at random among those with *any* study class, and COCO is dominated
  by people:

  | | person | chair | car | bicycle | dog |
  |---|---|---|---|---|---|
  | A (manual) | 21 | 8 | 1 | 0 | 0 |
  | B (assisted) | 20 | 0 | 4 | 2 | 0 |

  Dog was never tested. The hard class (chair, outline IoU 0.62) was only in the
  manual half, which pulled manual's average IoU down. **Within the one shared
  class, person, the modes were equal:**

  | Person only | Found | Outline IoU |
  |---|---|---|
  | Manual | 17 / 21 (81%) | 0.816 |
  | Assisted | 14 / 20 (70%) | 0.807 |

  So the overall "assisted IoU slightly higher" (0.784 vs 0.765) was a class-mix
  artefact. The supportable claim is **equal outline quality**. This run is
  therefore treated as a **pilot**.
- **The fix: a class-balanced rerun.**
  - `choose_balanced()` and notebook `01b` pick **4 images per class** (person,
    car, bicycle, dog, chair). In each, that class is clearly visible (≥ 64×64 px);
    there are at most 5 objects to label, and at most 2 people when the image was
    picked for another class.
  - Per class, images are dealt A, B, B, A by workload, so both halves get the same
    classes and similar work.
  - Pilot, model-evaluation and practice images are excluded. A feasibility count
    found enough candidates for every class (the scarcest, bicycle, has 47).
  - Notebook 03 has a `RUN` switch (`pilot` / `balanced`) and a new
    **class-by-class** table.
- **Balanced study, run 25 Nov.** Two more measurement issues were found and fixed:
  1. **Grouping.** On two assisted images, one missed object was drawn by hand in
     Manual mode (22 and 27 polygon clicks), which flipped those images' majority
     mode to "manual". Hand-fixing what the AI missed is part of the assisted
     workflow. Notebook 03 now groups by **study condition** (half A = manual,
     half B = assisted) and keeps `logged_mode` for reference.
  2. **Revisit time.** An image's events skip the time spent on other images, but
     the gap from *leaving* an image to *coming back* was counted, capped at 30 s.
     Several assisted images were revisited, so their time was inflated.
     `image_effort` no longer counts a gap that starts with `image_leave`. Both
     studies were recomputed.
- **Results after both fixes** (grouped by condition):

  | | Pilot: manual | Pilot: assisted | Balanced: manual | Balanced: assisted |
  |---|---|---|---|---|
  | Objects required | 30 | 26 | 21 | 20 |
  | Found | 77% | 65% | 71% | **80%** |
  | Seconds per found object | 24.4 | 6.8 | 21.3 | **10.0** |
  | Seconds per required object | 18.7 | 4.4 | 15.2 | **8.0** |
  | Actions per found object | 41.4 | 0.5 | 40.4 | **3.9** |
  | Outline IoU | 0.765 | 0.784 | 0.824 | 0.784 |
  | Wrong labels | 1 | 2 | 4 | 6 |

  Speed-up per found object: **3.6× in the pilot, 2.1× in the balanced study.**

  Class by class (balanced), outline IoU manual vs assisted:

  | bicycle | car | chair | dog | person |
  |---|---|---|---|---|
  | 0.85 vs 0.87 | 0.86 vs 0.84 | 0.82 vs 0.69 | 0.91 vs 0.89 | 0.76 vs 0.66 |

  Assisted outlines were as good on bicycle, car and dog, and worse on chair and
  person: thin, cluttered or occluded objects, which SAM outlines less exactly from
  a box.
- **The AI was slow during the study.** YOLOE took 0.3–5.3 s per image and SAM's
  encode 0.9–10 s; in notebook 02, measured alone, they took 0.19 s and 0.83 s. The
  first suggestions arrived after 14.8 s. Likely cause: on image open, the app starts
  SAM's encode and YOLOE's detection at the same time, in two threads, and both use
  all CPU cores, so they slow each other down. The waiting is included in the
  assisted time, as a user would experience it.
- **Fixed after the study (25 Nov), not re-measured in it.**
  - `app/models.py` now has **one shared lock for all model work**
    (`INFERENCE_LOCK`, used through `_Turn`). SAM's encode and decode and both
    detectors take turns instead of fighting over the CPU cores.
  - On opening a photo, or switching to assisted mode, the browser asks for
    **suggestions first**; SAM's encode queues behind them.
  - The time each request waited for its turn is logged (`wait_ms` on
    `ai_prepare`, `ai_segment`, `ai_detect`).
  - Expected: suggestions in about 0.2 s plus whatever is already running, and the
    encode about 0.8 s after that, matching notebook 02's one-at-a-time figures.
  - The study numbers above were measured **before** this fix and stay as they
    are. The report should present the fix as a consequence of the study.
- **Limits.**
  - One participant and 20 images.
  - The halves are different images, so difficulty differs (30 vs 26 required
    objects).
  - Manual went first: the learning effect favours manual.
  - Report these as a small pilot study, not a general result. A second person doing the swap (A assisted, B manual)
would cancel image difficulty too; the protocol in notebook 03 says so.

---

# Phase 5b — Training our own YOLO11n: from scratch vs pretrained (27 November 2026)

*Prepared 27 Nov, **not yet run**. Runs on the university data lab (GPU), after the
repository is on GitHub.*

## 1. Initial build

Yuvraj's request: train a model ourselves, to show both a pretrained model and one
we built and trained. Options discussed: our own CNN detector (rejected: too much
untestable new code for two days, and a weak result) and our own CNN class
suggester (offered). **Chosen: the same YOLO11n architecture, from random weights,
compared with the pretrained one.**

- **New folder `training/`** (not in `eval/`, at his request): `train_yolo11n_coco5.ipynb`,
  `README.md`, `requirements.txt`, and `data/`, `results/`, `trained/`.
- **The experiment, three ways, same architecture:**
  A = pretrained YOLO11n (Kontur's, evaluated only); **B = from scratch**
  (`YOLO("yolo11n.yaml")`, `pretrained=False`: every weight random);
  C = fine-tuned from the pretrained weights. B and C get the same data, epochs
  (100), image size, seed (2026) and settings; no early stopping.
- **Data, downloaded by the notebook:** the COCO annotations zip, then only the
  needed images, in parallel, skipping what is already there. Five classes
  (person, car, bicycle, dog, chair). Train: a class-balanced 20k-image subset
  of train2017 (rarest class first). **Three splits:** train, val (1,000 other
  train2017 images, for picking the best epoch) and test (every val2017 image
  with the classes). The test split is used only for the final A/B/C comparison.
- **One evaluation for all three:** pycocotools COCO AP on the test split,
  restricted to the five classes (model A's other 75 classes are dropped), with
  the standard mAP settings (conf 0.001, 300 boxes); plus per-class AP, time per
  image and parameter count.
- **Evidence written to `training/results/`:** environment (GPU, versions,
  settings, training hours), dataset (image ids per split, object counts),
  metrics per model, `comparison.csv`, `ap_per_class.png`,
  `learning_curves.png`, each run's Ultralytics `results.csv`/`results.png`/
  confusion matrix/`args.yaml`. Our weights go to `training/trained/` (~5 MB each).
- **Resumable:** `RESUME = True` continues an interrupted run from `last.pt`.
- **`.gitignore` at the root**, ready for the GitHub repository. Out:
  `report/` (his name and matriculation number), `.venv311/`, the pretrained
  weights (re-downloaded; `mobileclip_blt.ts` is over GitHub's 100 MB limit),
  `data/`, `eval/data/`, `training/data|runs|pretrained/`. In: code, docs,
  notebooks, `eval/results/`, `eval/studies/` (5.4 MB, the study evidence),
  `training/results/` and `training/trained/`.

## 2. Issues faced

**(a) Final scores on the epoch-picking set would flatter B and C.** Ultralytics
picks `best.pt` by its validation set; reporting on the same set would favour
the trained models over A.

**(b) A `.gitignore` pattern that hid our own results.** An unanchored `yolo*.pt`
also matched `training/trained/yolo11n_*.pt`, and `data/` also matched
`training/data/`.

**(c) A name clash in the notebook draft:** the training function and the set of
training image ids were both called `train`.

## 3. How it was solved

**(a)** Three splits: val (from train2017) only for epoch selection, test
(val2017) only for the comparison.

**(b)** Patterns anchored to the root (`/weights/*.pt`, `/*.pt`, `/data/`) and
checked in a throwaway git repository: every path lands on the intended side.

**(c)** Renamed to `train_ids` / `val_ids` / `test_ids`. All 13 code cells
compile; nothing was run.

**(d) Later on 27 Nov, at Yuvraj's request:** model creation and evaluation are
now **two notebooks**, and all evaluation lives in `eval/`:
- `training/train_yolo11n_coco5.ipynb` (20 cells): data download, splits, labels,
  training B and C. Writes `training/results/dataset.json`, which records every
  split's image ids.
- `eval/04_scratch_vs_pretrained.ipynb` (10 cells): reads that file, evaluates
  A, B and C on the test split, writes `eval/results/scratch_vs_pretrained/`.
- **Model A and C's starting point are now Kontur's own `weights/yolo11n.pt`**
  (the exact file the app uses; downloaded there if missing), not a separate
  copy in `training/pretrained/`.
- The raw detection files of notebook 04 (about 800k boxes per model) are kept
  out of git, since they could exceed GitHub's 100 MB limit; metrics, table and
  charts are committed.
- **The repository will be public** (Yuvraj submits its link to the professor).
  His decision: keep his first name in the docs; `report/` stays out of git.
- Both notebooks' code cells compile; nothing was run.
- **One README, one requirements file** (Yuvraj: no duplicates). The training
  instructions, the A/B/C table, the splits and the output table moved into the
  root `README.md` ("Training our own YOLO11n"); `training/README.md` and
  `training/requirements.txt` were removed. The root `requirements.txt` already
  held every package the training needs, and now says so. COCO is now credited
  in the README.
- **Switched to all 80 COCO classes** (27 Nov, Yuvraj: "A can detect all 80
  classes, B and C only 5: that doesn't sound fair"). Training on all of
  train2017 now fits on the data lab GPU (one RTX A6000, 48 GB). He ran the 5-class
  version's data steps first (21k images downloaded) and pushed the notebook;
  it was pulled and rewritten (renamed `train_yolo11n_coco.ipynb`):
  - **Classes:** all 80, read from the annotations, in COCO's order (= YOLO's 0–79).
  - **Splits:** val = 1,000 random train2017 images **chosen first**; train = every
    other train2017 image with an object (~116k); test = **all 5,000 val2017
    images**, the official benchmark. A should therefore score close to
    Ultralytics' published 0.395 AP: a free sanity check of the evaluation.
  - **Folders kept in sync with the splits:** already-downloaded images are moved
    to their new split's folder, strays deleted, labels and YOLO label caches
    rebuilt. The 21k images from the 5-class run are reused.
  - **Fair settings:** fixed `BATCH = 64` for both (AutoBatch could pick
    different sizes), `EPOCHS = 50` (fits one GPU before Sunday), no early stop.
  - **B and C run in parallel** on the one GPU, as background processes
    (`subprocess`, own session, log per run), so a closed browser tab does not
    stop them. A *Status* cell (epochs, hours left, best val mAP) and a *Finish*
    cell (copies best weights and curves into `trained/` and `results/`).
  - **Quick check** cell: one epoch of B and C on 1% of the data before the long run.
  - eval/04: 80 classes, all 5,000 test images, a per-class CSV, an 80-class chart,
    a B-vs-A scatter per class, and the 0.395 sanity line.

  Issues found while writing it (nothing run yet):
  - **(e) The 5-class val split had no bicycles** (`bicycle: 0, dog: 4` in his run):
    val was drawn *after* the balanced train selection had used up the rare
    classes. Fixed by choosing val first.
  - **(f) Stale images would leak between splits:** YOLO trains on every file in
    `images/train`, so an image from the old split left there would be trained
    on even if it is now in val. Fixed by syncing each folder to its split.
  - **(g) Two runs racing on shared files:** the AMP self-check model and YOLO's
    label caches are written by whichever run starts first. Fixed: C starts only
    once B has built the caches; caches left by the quick check (built for 1% of
    the data) are deleted before launch.
  - **(h) Restart-safety:** after a kernel restart, Status and Finish work after
    re-running only the first cells; `environment.json` keeps its original start
    time. An evaluation edge case (a model with no detections) no longer crashes.

- **First launch on the data lab failed (27 Nov): `/dev/shm` is 64 MB.** The data
  steps ran cleanly (train 116,266 images, val 1,000, test 5,000; all 80 classes in
  every split; machine: RTX A6000, 20 CPU cores). The quick check then failed with
  hundreds of `unable to allocate shared memory(shm) ... No space left on device`.
  Cause: PyTorch's data-loading workers hand each batch to the training process
  through shared memory; one batch of 64 images at 640 px is ~78 MB, and the
  container (Docker default) has 64 MB. Fix, with Yuvraj: `WORKERS = 0` (the
  training process loads images itself; no shared memory) and, to fit the
  deadline without workers, **`TRAIN_FRACTION = 30_000`**: Ultralytics' `fraction`
  takes exactly 30,000 train images (the first in file-name order, i.e. COCO id
  order), the same for B and C; val and test stay complete; no data step re-run,
  nothing deleted (checked in the installed Ultralytics: `fraction` applies to
  the train split only and accepts an image count). B and C still run in
  parallel: with 0 workers each run loads on one CPU core, and there are 20.
  The report states that B and C were trained on a 30k-image subset and why.
- **Training started on the data lab (27 Nov evening).** The quick check passed;
  B and C launched in parallel. Measured: about **5 min per epoch** for each run
  (30k images, 0 workers), so about **4 h** for 50 epochs. After epoch 1: val
  mAP50-95 B 0.0003, C 0.288. Yolo's progress bars were invisible in the
  notebook: the runs are background processes writing to `runs/<tag>.log`, and
  the data lab's Jupyter lacks `ipywidgets`. Added a **"Watch live" cell** after
  Status: the status table plus each run's newest progress line, refreshed
  every 30 s; stopping it does not stop training. (When inserting it, the
  `
`/`
` in one line were turned into real line breaks by shell escaping;
  caught by the compile check and rebuilt from raw strings.)
- **Back to training inside the notebook (27 Nov, Yuvraj).** The background
  processes were hard to follow: no progress bar in the notebook, Status/Watch
  cells to re-run, and a kernel restart did *not* stop them (by design), which
  was confusing. He stopped both runs. Now:
  - no `subprocess`, no `PARALLEL`, no Launch/Status/Watch cells;
  - **Train B** and **Train C** cells train in the notebook, one after the
    other. Ultralytics draws its own progress bar (no `ipywidgets` needed), so
    the live bar shows under the cell;
  - **automatic resume**: a run with `last.pt` and fewer than `EPOCHS` epochs
    continues from its last epoch (its original settings come from the
    checkpoint); a finished run is skipped; `FRESH_START = True` starts over.
    This replaces `RESUME`, so a forgotten flag can never restart a run from
    zero and lose hours;
  - each run copies its best weights and curves into `trained/` and `results/`
    when it ends (no separate Finish step); a *Summary* cell prints both.
  - Cost: B and C now run one after the other, about 4 h each instead of about
    4 h together.

- **GitHub repository** `github.com/yuvrajghag5/Kontur` (public; its link goes to
  the professor). GitHub had created it with an MIT licence. Kontur imports
  Ultralytics, which is AGPL-3.0, so at Yuvraj's choice the licence was switched to
  **AGPL-3.0** (official text from gnu.org) and the README says so.
  `archive/satellite/` is left out of the repository (his choice; it belongs to the
  Deep Learning course) but kept locally. First push: one commit on top of
  GitHub's "Initial commit".

---

# Phase 6 — Report and submission

## 1. Initial build

- **25 Nov:** all project docs and `eval/results/` re-read; a report outline
  proposed (10 sections + references) and saved as `report_outline.md`.
- **25 Nov, later:** after Phases 4d–4f, all seven docs updated (README, phase,
  design decisions 11–14, tech, architecture, GUIDE, changes) and the outline
  revised to cover projects, the Kontur look and the export dialog. Shown to
  Yuvraj for approval before any writing.
- **25 Nov, later:** `report/report.md` drafted: title block, sections 1–5
  (introduction, Kontur at a glance, features 3.1–3.9, model choices, tech
  stack) and references [1]–[14] with software licences. About 5,000 words,
  roughly 9–10 pages, over the 8 budgeted for these sections. **Sections 6–10
  and the abstract are on hold** at Yuvraj's request while he settles the
  evaluation. Open items in the draft: three screenshots (marked
  **[FIGURE: …]**), his surname on the title page, one baseline number to check
  against the notebook 03 re-run, and the references to check against each
  paper's own page.
- **27 Nov: code-base cleanup before the evaluation write-up.** An audit (unused
  imports, never-called functions, orphan element ids, unused CSS) found the code
  already tidy. Changed:
  - removed `Store.class_by_name` (never called) and an unused `import time` in
    `eval/evallib.py` (no change to what the notebooks compute);
  - **fixed project numbers being reused**: after deleting every project the next
    new one got number 1 again, so an old `#/p/1` link would open a different
    project. A `next_id` counter in `projects.json` now only goes up (it also
    checks `trash/` and `projects/` for older registries);
  - CSS: merged rules split between the original and the Kontur sections
    (`.brand .mark`, `.dropcard`, `.emptybox`, `#toast`); removed the stage
    outline while dragging (the full-window drop zone replaced it) and the
    pointer cursor on the side drop card, which is no longer clickable;
  - naming: Kontur in `requirements.txt` and the `app.js` header;
    `pandas==3.1.1` and `ipykernel==7.4.0` pinned like the rest;
  - removed the `__pycache__` folders; moved `report_outline.md` to
    `report/outline.md`;
  - docs: phase numbers aligned (changes.md now matches phase.md: 6 = report,
    7 = optional satellite mode); a short Phase 4c entry; the file tree in
    `architecture.md` shows `report/`, the study folders and the weights;
  - **model weights provenance**: a table in `tech.md` (file, size, SHA-256,
    source; "used as downloaded, never retrained", no `runs/` folder exists), a
    line in the README credits, and a paragraph in report §4. Prompted by
    Yuvraj asking why `.pt` files are in the folder if the models are pretrained.
  - Not touched on purpose: the weights stay in the project root (Ultralytics
    looks for them in the folder it runs from; moving them would re-download
    600 MB), `data/trash/` (his practice data), `archive/satellite/`, model and
    evaluation logic.
- **27 Nov, later: the folder reorganised** (Yuvraj: "all the weights in one
  folder, all the docs in one folder"). The root now holds only `README.md`,
  `requirements.txt` and folders:
  - `weights/`: the four weight files, moved unchanged (fingerprints re-checked).
    The day's earlier worry (Ultralytics looks in the folder it runs from) was
    solved in code rather than avoided: `models.py` has `WEIGHTS_DIR` and
    `weight_path()`, and passes Ultralytics the full path, so a missing file
    downloads straight into `weights/`. YOLOE's text encoder needed one more
    step: Ultralytics looks it up by bare name (`mobileclip_blt.ts`) in the
    working folder, and builds it afresh on every `set_classes`. The app now
    builds it once from `weights/` (`MobileCLIPTS(device, weight=...)`) and
    hands it over (`model.model.clip_model`, then
    `get_text_pe(..., cache_clip_model=True)` and `set_classes(names, embeddings)`).
    Same encoder and same embeddings, so the measured results still hold, and a
    class change no longer reloads 600 MB.
  - `docs/`: GUIDE, phase, design, architecture, tech, changes. README links and
    the folder table updated.
  - `eval/studies/`: the two effort-study folders (`data_study`, `data_study2`),
    moved unchanged. Notebook 03's `STUDY` path and the `--data` hints in
    notebooks 01b/03 and `evallib.py` point there.
  - `evallib.py`: SAM now loads through the app's default (`weights/`) instead
    of a root path.
  - Checked without running the app: a read-only script confirmed every weight
    file named in `models.py` is in `weights/`, none is left in the root, all
    four notebooks are valid, both study folders are complete, and doc links
    resolve; all Python and the JS pass syntax checks. **Not yet run by Yuvraj.**

## 2. Issues faced

**(a) The saved effort CSVs are older than the final measurement fixes.**
`effort_per_image*.csv`, `effort_per_class_balanced.csv` and the effort PNGs were
written at 14:29 / 14:56; `evallib.py` (the revisit-gap fix) changed at 14:57. So
the files still hold the pre-fix numbers, e.g. balanced assisted ≈ 19 s per found
object in the CSV against 10.0 s in Phase 5 §4. The report must not quote the CSVs
until notebook 03 is re-run.

**(b) "Balanced" is balanced by images, not by objects.** Required objects per
class still differ between halves (person 8 manual vs 4 assisted; chair 4 vs 6).
A limit to state in the report.

**(c) Phase numbering differs** between this file (6 = geospatial, 7 = report)
and `phase.md` (6 = report, 7 = satellite).

## 3. How it was solved

- (a) Yuvraj re-runs notebook 03 with `RUN = "pilot"` and `RUN = "balanced"`
  before any effort number goes into the report.

---

# Phase 7 — Satellite mode back in (optional, not started)

The archived satellite labeller (`archive/satellite/`) may return as a second
image type only if time allows after the report. Nothing built.
