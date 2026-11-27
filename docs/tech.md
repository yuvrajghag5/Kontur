# Technology Choices

Every choice has a reason. The brief requires each to be justified in the report:
what problem it solves for the user, and why this model or approach. So the reason
is written down next to the choice.

> **Status, 25 Nov 2026.** Every choice below is in use in the built, working
> app or in the evaluation.

## Summary

| Layer | Choice | Phase | State |
|---|---|---|---|
| Language | Python 3.11 (`.venv311`) | all | in code |
| Web back end | FastAPI + Uvicorn | 1 | in code |
| Front end | Plain HTML + JavaScript + Canvas 2D, no framework, no build step | 1 | in code |
| Storage | SQLite (Python standard library) + image files on disk | 1 | in code |
| Image handling | Pillow (EXIF rotation, masks) | 1–2 | in code |
| Export formats | COCO JSON, YOLO detection + segmentation datasets, Pascal VOC XML, PNG masks, CSV, preview JPEGs; the user picks | 2, 4f | in code |
| Projects | One folder per project + a JSON registry | 4d | in code |
| Model library | Ultralytics (for both models below) | 3–4 | in code (P3) |
| Click-to-segment | **MobileSAM** (SAM 2.1-tiny via `--sam`) | 3 | in use; encode 0.83 s, click 0.07 s (CPU) |
| Auto-suggest | **YOLO11n** (COCO, 80 classes) **and YOLOE-11s** (open vocabulary), chosen in the UI | 4 | in use; 0.06 s / 0.19 s per image (CPU) |
| UI type | IBM Plex Sans / Sans Condensed / Mono; Big Shoulders Display for the name and headings (4e); Google Fonts, falling back to system fonts | 4, 4e | in code |
| Runtime | PyTorch 2.14.1, probably the CPU build | 3–4 | installed |
| Evaluation | pycocotools, numpy, matplotlib | 5 | installed |

---

## Python 3.11, not 3.14

The machine's default Python is 3.14, for which PyTorch has no CUDA build. 3.11 has
the widest library support. This was found on several earlier projects on this
machine.

## FastAPI

The models are Python, so the server is Python.

- Typed request models reject bad input before it reaches the store.
- `/docs` lets the AI routes be tried without the UI.
- Multipart upload comes built in.

*Not Streamlit or Gradio:* their widgets decide the interaction, and annotation *is*
the interaction, so a custom drawing canvas fights them. *Not Flask:* it would
work, but FastAPI's validation saves code.

## Plain JavaScript + Canvas 2D

The annotation surface is the product and has to be written for this project; the
brief forbids wrapping annotation tools.

- A single canvas, with one view transform, gives full control over drawing,
  hit-testing and zoom.
- There is exactly one screen-to-image mapping, which the October tool showed
  matters.
- No framework and no build step. Node native builds fail on this machine (no
  Visual Studio build tools).

## SQLite

One file, no server, part of Python. Enough for a single-user local tool, and easy
to query during evaluation. It holds three tables: classes, images, annotations.

## Pillow

Uploads are decoded once, EXIF orientation is applied, and the corrected image is
stored. A phone photo then has the same orientation in the browser, in the stored
coordinates and in the export. Pillow also rasterises polygons into the PNG masks.

## Export: the user picks the formats

"Usable output" means usable by other tools without conversion. Different tools
want different formats, so the user ticks the ones they need (Phase 4f):

- **COCO JSON** is the standard for detection and instance segmentation. It is
  loadable by `pycocotools`, which Phase 5 also uses.
- **YOLO detection** and **YOLO segmentation** are each a complete Ultralytics
  dataset (`images/`, `labels/`, `data.yaml`). They are separate because
  Ultralytics finds labels by swapping `images/` for `labels/`; one shared folder
  would always serve the boxes.
- **Pascal VOC XML** serves older detectors and TensorFlow Object Detection.
- **PNG masks** suit semantic segmentation.
- **CSV** suits spreadsheets and quick analysis.
- **Photos with labels drawn** are for people (checking, sharing, report
  figures), never for training: a model needs the clean photo plus the label
  as numbers.

Every image keeps one export name across all formats.

## Projects: one folder each, not a project column

Each project is its own folder with the old layout (`annotator.db`, `images/`,
`logs/`), listed in `projects.json`. *Not* a `project_id` column in every
table: that would have changed the store, every query and the evaluation
notebooks three days before the deadline. With folders, `Store` and `EventLog`
did not change, old data and the study folders keep working as they are, and
deleting a project is one folder move to `trash/`.

## Big Shoulders Display (4e)

A tall, condensed display face, used only for the name *Kontur*, headings and
project names. It gives the app a recognisable voice while the working UI stays
in IBM Plex. Open Font License, from Google Fonts.

## Ultralytics as the model library

Both planned models load through one library: `SAM("mobile_sam.pt")` and
`YOLO("yolo11n.pt")`. Weights download on first use, and it is already installed.
Its SAM predictor computes the image embedding once (`set_image`) and then answers
each click from the cache. That is exactly the "encode once, decode per click"
pattern click-to-segment needs.

Ultralytics is a **model library**, not an annotation tool, so using it is within
the rules (pretrained models and libraries are allowed if cited). It is
AGPL-licensed, which is fine for coursework, and is cited.

**Confirmed with the examiner.** The course rule allows libraries and local
pretrained models, but not finished tools that are only configured. Ultralytics
also ships an auto-annotation function (`auto_annotate`), which this project does
not use, so its status was asked about explicitly. Prof. Binh Vu replied by email
(25 Nov 2026): **"Ultralytics is allowed."**

## Model weights: used as downloaded, never retrained

All models are used **pretrained, exactly as published**. Ultralytics downloaded
each weights file the first time it was needed (17 Nov 2026, first server
starts); on 27 Nov they were moved, unchanged, into `weights/`. The app now
gives Ultralytics the full path to each file, so a missing file is downloaded
straight into `weights/`. YOLOE's text encoder is handed to YOLOE by the app
too: Ultralytics would otherwise look for it by bare name in the folder the
server runs from (and reload all 600 MB on every class change). **No model was trained or
fine-tuned in this project:** Ultralytics writes every training run to a
`runs/` folder, and there is none. The fingerprints below let anyone check the
files are the official ones.

| File | Model | Size | SHA-256 (first 16) | Source |
|---|---|---|---|---|
| `mobile_sam.pt` | MobileSAM | 40.7 MB | `6dbb90523a35330f` | Ultralytics assets release |
| `yolo11n.pt` | YOLO11n, COCO | 5.6 MB | `0ebbc80d4a7680d1` | Ultralytics assets release |
| `yoloe-11s-seg.pt` | YOLOE-11s | 27.8 MB | `8e439445c87338b7` | Ultralytics assets release |
| `mobileclip_blt.ts` | MobileCLIP text encoder (for YOLOE) | 600 MB | not recorded | Ultralytics assets release |

*Why not retrain YOLO11n on COCO?* Ultralytics already trained it on COCO
train2017 (118k images). Retraining would at best reproduce it, would likely
score lower with a short CPU run, and would muddy the evaluation, which measures
the official model on COCO val2017 images it never saw. Fine-tuning on a user's
own Kontur exports is the meaningful kind of training; it is future work.

## MobileSAM for click-to-segment (Phase 3)

**Problem it solves:** a polygon is the most click-expensive annotation. A
promptable segmentation model turns one click, or a box, into a full outline, and
works on any object, not just trained classes.

**Why MobileSAM:** it keeps SAM's prompt decoder but replaces the heavy ViT-H image
encoder with a small distilled one (TinyViT, about 5M parameters). The torch build
installed appears to be CPU-only, and on a CPU the encoder is the slow part, run
once per image.

*Alternative:* SAM 2.1-tiny, which is newer and more accurate but heavier. Switching
is one line, and Phase 5 can compare the two if time allows.

## YOLO11n for auto-suggest (Phase 4)

**Problem it solves:** for common objects, the user should not even have to point.

**Why:** it is pretrained on COCO's 80 classes, which is also the evaluation
dataset. That makes its quality measurable directly with COCO mAP. The nano size
runs on CPU in well under a second per image.

## YOLOE-11s alongside it (Phase 4, added 17 Nov 2026)

**Problem it solves:** an annotation tool exists to label classes that a
pretrained model does not know. YOLO11n can never suggest "cupboard", "lamp" or
"mirror". Yuvraj's own first project had 12 classes, and YOLO11n covers 6 of
them.

**Why YOLOE:**

- It is open-vocabulary: the user's class names are turned into text embeddings
  (with a MobileCLIP text encoder), and the detector looks for matching regions,
  with no retraining.
- It is trained on far broader data than COCO (Objects365 and grounding
  datasets).
- It ships with Ultralytics, the same library and API as YOLO11n.

**Trade-off:**

- It is slower and larger.
- It is less accurate than YOLO11n on COCO's own classes.
- It gives more false alarms for vague names.

**Why both, behind a selector:** the user picks speed or coverage. The evaluation
can measure both on the same COCO images: YOLOE prompted with the 80 COCO names
is a zero-shot test.

*Not used:* YOLO-World (the same idea, older) and Grounding DINO (much heavier,
too slow on a CPU).

## Hardware

RTX 3050 laptop GPU with 4 GB. The installed torch appears to be the CPU build: its
version string carries no `+cu` tag. To check, run:

    .venv311\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"

If it prints `False`, a CUDA build can be installed later. The small models are
chosen so that CPU is enough either way.

## Deliberately not used

| Not using | Why |
|---|---|
| CVAT, Label Studio, VIA, LabelMe, Roboflow Annotate, etc. | **Forbidden by the brief.** Forking or wrapping existing annotation tools is not allowed. |
| Canvas/drawing frameworks (Konva, Fabric.js) | Not needed for boxes and polygons. Fewer layers between the mouse and the pixel mapping. |
| SAM ViT-H / ViT-L, SAM 2 large | Too slow on CPU and too big for 4 GB alongside a detector. |
| React / Vue + npm build | Build toolchain overhead; Node native builds fail on this machine. |
| Streamlit / Gradio | Their widgets make a custom polygon-editing canvas awkward. |
| Cloud APIs for inference | Need accounts and send images off the machine. |
| The October satellite index rule as "the model" | A fixed formula, not a computer vision model. It is archived with the satellite mode. |
