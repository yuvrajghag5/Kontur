# Architecture

How the pieces fit: components, data flow, file layout, interfaces. For *why*, see
`design.md`; for the tools, see `tech.md`.

> **State, 25 Nov 2026.** All components below are **built, run and working**:
> the app (Phases 1–4f) and the evaluation notebooks (Phase 5). Phases 4d–4f
> (projects, the Kontur look, folder upload, the export dialog) were added after
> the effort study. The
> October satellite labeller is archived intact in `archive/satellite/`.

## Overview

```
 Browser (app/static)                          Python (app/, FastAPI)
 ┌──────────────────────────────┐  HTTP/JSON  ┌──────────────────────────────┐
 │ app.js                       │ ──────────▶ │ server.py   routes           │
 │  canvas: image + shapes      │ ◀────────── │ store.py    SQLite + files   │
 │  tools: box, polygon, select │             │ export.py   COCO/YOLO/masks  │
 │  zoom/pan view transform     │             │ events.py   JSONL log        │
 │  undo stack (per image)      │             │ models.py   SAM + YOLO(E)    │
 │  event queue → /api/events   │             └──────────────────────────────┘
 └──────────────────────────────┘                  │
                                                   ▼
                                    data/annotator.db, data/images/,
                                    data/logs/events.jsonl
```

## Components

| Component | File | Responsibility | State |
|---|---|---|---|
| Server | `app/server.py` | Routes; `--data`, `--port`, `--sam`; background model warm-up; opens one project at a time; `X-Project` guard | built |
| Projects | `app/projects.py` | Registry `<data>/projects.json`; create, rename, delete (move to `trash/`); card summaries; a pre-projects data folder registered as project "." | built |
| Store | `app/store.py` | Classes, images, annotations in SQLite; image files; geometry validation and clamping; EXIF rotation applied on upload; class rename | built |
| Export | `app/export.py` | One zip with the chosen formats: COCO JSON, YOLO detection dataset, YOLO segmentation dataset, Pascal VOC XML, PNG masks, CSV, preview JPEGs with labels drawn; optional photos; optional only-labelled | built, verified |
| Event log | `app/events.py` | Append-only JSONL, one event per line | built |
| UI | `app/static/index.html`, `app.css`, `app.js` | Home page (`#/`) with project cards and the new-project dialog; workspace (`#/p/<id>`): canvas, tools, panels, upload, undo, logging, class picker, suggestions panel, export dialog, folder upload (picker + recursive drop, batches of 12) | built |
| Models | `app/models.py` | `ClickSegmenter`: MobileSAM, one cached image embedding, click/box → mask → polygon. `Detector`: YOLO11n (COCO names mapped to the user's classes) or YOLOE-11s (the user's class names as text prompts). All warm up in the background at start; all model work takes turns through one lock (`INFERENCE_LOCK`). | built, measured |
| Evaluation | `eval/evallib.py` + `01_build_eval_set`, `02_model_quality`, `03_effort_study` notebooks | COCO val2017 subsets; simulated-click SAM evaluation, COCO mAP and P/R for both detectors, YOLO→SAM outline IoU; effort analysis from a study data folder's database and log; `01b` class-balanced study set | built, run |

## Projects

```
<data>/projects.json         registry: [{id, name, folder, created_at, last_opened}], open
<data>/projects/<id>/        one project: annotator.db, images/, logs/events.jsonl
<data>/trash/<id>-<time>/    a deleted project (moved, never erased; the pre-projects
                             project moves its annotator.db, images/ and events log)
<data>/logs/server.jsonl     model loading etc. while no project is open
```

A data folder from before projects (`annotator.db` directly in `<data>`) is
registered as a project with folder `.`, so old data keeps its layout. The two
effort-study folders (`eval/studies/data_study`, `data_study2`) have that same
layout and open the same way with `--data`.

**One project is open at a time.** `POST /api/projects/{id}/open` swaps the
server's `store` and `log` to that folder; the models stay loaded. While none is
open, project routes answer 409. Every browser call carries `X-Project`; a
middleware refuses calls naming a project that is no longer open, because image
ids restart at 1 in each project.

**Navigation.** `#/` = home page, `#/p/<id>` = workspace. New project: name →
class picker (opens because there are no classes) → file chooser → labelling.

## Data model

| Table | Fields |
|---|---|
| `classes` | id, name (unique), colour |
| `images` | id, file (stored name), name (upload name), width, height, added_at |
| `annotations` | id, image_id, class_id, kind (`box` / `polygon`), points (JSON, image pixels), source (`manual` / `sam` / `yolo` / `yolo+sam`), created_at, updated_at |

**Geometry.** Everything is in image pixels: floats, with the origin at the top-left
corner of the top-left pixel. A box is two corners `[[x1, y1], [x2, y2]]`; a polygon
is its vertices, unclosed. The store clamps points to the image and rejects shapes
under one pixel.

## The one coordinate mapping

The canvas draws the image at scale `V.s`, shifted by `(V.tx, V.ty)` CSS pixels.
`toImage(clientX, clientY)` in `app.js` is the only screen-to-image conversion, and
every tool calls it:

    image_x = (clientX − canvas.left − V.tx) / V.s

The canvas has no border or padding, so its bounding rectangle is exactly its
drawing area. The October tool had a 1px border offset from exactly this. Device
pixel ratio is applied only when drawing, never in the mapping.

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | The UI |
| GET / POST | `/api/projects` | List projects with card summaries and the open one; create one `{name}` |
| PUT / DELETE | `/api/projects/{id}` | Rename; delete (moves the folder to `trash/`) |
| POST | `/api/projects/{id}/open`, `/api/projects/close` | Open a project (returns its state); close it (home page) |
| GET | `/api/projects/{id}/thumb/{image_id}` | One of the project's photos, for the mosaic on its card |
| GET | `/api/state` | The open project, its classes and images, with annotation counts |
| POST / DELETE / PUT | `/api/classes`, `/api/classes/{id}` | Add a class; delete an unused class; rename |
| GET | `/api/classes/coverage` | Per class: the COCO name YOLO11n knows it as (or none); YOLOE always |
| GET | `/api/ai/catalogue` | The 80 COCO classes in groups, for the class picker |
| POST | `/api/images` | Upload one or more images (multipart `files`) |
| GET / DELETE | `/api/images/{id}/file`, `/api/images/{id}` | Image file; delete an image with its labels |
| GET | `/api/images/{id}/annotations` | Annotations of one image |
| POST / PUT / DELETE | `/api/annotations`, `/api/annotations/{id}` | Create; change class or points; delete |
| GET | `/api/ai/status` | Model name, device, last encode time |
| POST | `/api/ai/prepare` | Embed an image ahead of the first click |
| POST | `/api/ai/segment` | Clicks (+ labels) and/or a box → `{polygon, score, area, decode_ms, encode_ms}`; HTTP 503 if the model is unavailable |
| GET | `/api/ai/detectors` | The two detectors: label, weights, open-vocabulary or not, state, load time |
| POST | `/api/ai/detect` | `{image_id, model: yolo11n \| yoloe, conf}` → suggestions `{box, score, class_id, class_name}`, ms, unsupported classes |
| POST | `/api/events` | A batch of interaction events |
| GET | `/api/export/formats` | The export formats the dialog offers |
| GET | `/api/export?formats=coco,yolo_det&images=1&only_labelled=0` | The export zip with just those formats; no `formats` = all six |

## Interaction log

`data/logs/events.jsonl`, one object per line. Each line carries:

- `ts`: server time, seconds
- `t`: browser time, milliseconds
- `session`, `mode` (manual / assisted), `image`
- `event`, plus that event's fields

Events:

- `session_start`, `image_open`, `image_leave` (with `ms_open`)
- `click`: every mouse press on the canvas, with button, tool and image x/y
- `key`, `tool`, `class_pick`, `mode`
- `ann_create`: kind, class, number of points, source, ms since the image opened
- `ann_update` (move / reshape / reclass), `ann_delete`, `undo`, `draft_cancel`
- AI (Phase 3): `ai_ready`, `ai_click` (label 1/0), `ai_box`, `ai_result`,
  `ai_accept`, `ai_discard`
- Suggestions (Phase 4): `sug_run`, `sug_accept`, `sug_reject`,
  `sug_accept_all`, `sug_conf`, `sug_auto`, `det_change`
- Server events: `upload`, `delete_image`, `export`, `ai_load`, `ai_prepare`,
  `ai_segment`, `ai_detect`, `ai_error`

## Suggestion flow

1. A photo opens in assisted mode (or S is pressed) → `/api/ai/detect` with the
   selected detector at confidence 0.15.
2. The browser shows suggestions above the slider's confidence, hiding any that
   an existing same-class annotation already covers (IoU > 0.7).
3. Clicking one sends its box to `/api/ai/segment` → a polygon, saved with
   `source = yolo+sam` (or the box, with `source = yolo`, if SAM is unavailable).

## Click-to-segment flow

1. The image opens in assisted mode → `/api/ai/prepare` → the SAM image encoder
   runs once, and the embedding is cached until another image is prepared.
2. A click or box → `/api/ai/segment` with **all** prompts for this object so far
   → only the prompt decoder runs.
3. The mask becomes the largest piece's outline, simplified to about 1 px → shown
   as a dashed proposal.
4. Enter → `POST /api/annotations` with `kind = polygon`, `source = sam`. From
   then on it is an ordinary, editable annotation.

## File layout

```
AI annotator/                 (the app is called Kontur)
├── app/
│   ├── server.py  projects.py  store.py  export.py  events.py  models.py
│   └── static/  index.html  app.css  app.js
├── weights/                  mobile_sam.pt, yolo11n.pt, yoloe-11s-seg.pt, mobileclip_blt.ts (pretrained, as downloaded)
├── eval/                     evallib.py + notebooks 01, 01b, 02, 03, 04 (A vs B vs C)
│   ├── data/                 COCO annotations and the image subsets
│   ├── results/              tables and charts the notebooks write (04: scratch_vs_pretrained/)
│   └── studies/              data_study/ (pilot), data_study2/ (balanced): read by notebook 03; never delete
├── training/                 train_yolo11n_coco.ipynb (B from scratch, C fine-tuned, 80 classes; GPU; how to run: README);
│                             data/ (COCO, not in git), trained/ (our weights), results/ (evidence)
├── docs/                     GUIDE, phase, design, architecture, tech, changes
├── report/                   outline.md, report.md
├── data/                     created at run time: projects.json, projects/<id>/, trash/
├── archive/satellite/        October satellite labeller, intact, with its own README
├── .venv311/                 Python 3.11 environment
└── README.md  requirements.txt
```
