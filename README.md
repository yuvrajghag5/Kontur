# Kontur — AI-assisted photo labelling

AI Vision course, exam project ("AI annotator"). **Due 29 November 2026.**
*Kontur* is German for *outline*: the model traces it, you decide.

A web application for labelling photos with boxes and polygons, where computer
vision models do most of the drawing and the human checks and corrects. Labels are
saved as you work, organised in projects, and export in the formats you choose:
COCO JSON, YOLO detection, YOLO segmentation, Pascal VOC, PNG masks, CSV, or
photos with the labels drawn on.

> **Status (25 Nov 2026):**
> - **Built, run and working:** manual labelling, AI outline (MobileSAM), suggestions
>   (YOLO11n / YOLOE selector), the class picker, export, and the evaluation.
> - **Added after the study (25 Nov), run by Yuvraj:** projects and a home page
>   (home → new project → classes → photos → label), the Kontur name and look
>   with animations, folder upload, and an export dialog with seven formats.
> - **Next:** the report (due Sun 29 Nov). Re-run notebook 03 (`RUN = "pilot"`
>   and `"balanced"`) first: the saved effort CSVs predate the last fix.
> - The October satellite labeller is archived intact in `archive/satellite/`.
>
> **Headline results:**
> - **Models** (100 COCO val images): SAM mIoU 0.57 after 1 click → 0.78 after 5;
>   YOLO11n AP 0.49, YOLOE AP 0.44.
> - **Effort, balanced study:** assisted labelling **2.1× faster per object** with
>   **~90% fewer actions** (3.9 vs 40.4) and more objects found (80% vs 71%), at
>   slightly lower outline IoU (0.78 vs 0.82).
> - **Effort, pilot:** 3.6× faster.
> - Details are in `docs/changes.md`, Phase 5 §4.

## Run it

Use the project's own Python 3.11 environment (`pip install -r requirements.txt`):

```bash
.venv311\Scripts\python.exe -m app.server
```

Then open http://127.0.0.1:8000. Run the command from this folder: it has to be
able to find the `app` package.

The app opens on the **Projects** home page. Data lives in `data/`, created on
first run:

- `projects.json`: the list of projects
- `projects/<id>/`: one project: `annotator.db` (classes, images, annotations),
  `images/`, and `logs/events.jsonl` (the interaction log)
- `trash/`: deleted projects, moved here, never erased
- Data from before projects (`annotator.db` directly in `data/`) shows up as
  "My first project" and stays where it is.
- The effort studies are kept separately in `eval/studies/data_study/` (pilot)
  and `eval/studies/data_study2/` (balanced). Notebook 03 reads them; never
  delete them.

For tests, point the server at a scratch folder so real labels and the log stay
clean:

```bash
.venv311\Scripts\python.exe -m app.server --data C:\temp\annotator-test --port 8001
```

## Using it

- **Projects:** the home page lists every project with its progress. **New
  project** (or N): name it → choose its classes → add photos → label.
  "Projects" at the top left goes back. Every card has rename and delete
  buttons; delete moves the project to `data/trash/`, never erases it.
- **Add photos:** **Add photos** or **Add folder** (every photo in it,
  subfolders too), or drop photos and folders anywhere on the page. Other files
  are skipped and counted.
- **Box (B):** drag a rectangle. **Polygon (P):** click points; Enter, a
  double-click or a click on the first point closes it. **Select (V):** click a
  shape, then drag it, or drag its corner/vertex handles.
- **Classes:** pick one with keys 1–9 or a click; add new ones in the right-hand
  panel. In Select mode, a number key re-classes the selected shape.
- **Fix mistakes:** Ctrl+Z undoes, up to every change made on the image. Backspace
  removes the last polygon point while drawing, or deletes the selected shape. Esc
  cancels.
- **Navigate:** wheel to zoom at the cursor; right-drag or Space+drag to pan; F to
  fit; ← / → for the previous / next image.
- **Mode:** *manual* or *assisted*, recorded with every logged event. Manual
  mode has no AI at all; assisted adds the AI tools.
- **AI outline (A, assisted mode only):**
  - Click an object: MobileSAM proposes its outline, dashed.
  - Clicking the next object saves the previous outline.
  - **Shift+click** adds a missed part; **right-click** removes a part.
  - Dragging a box outlines the object inside it.
  - **Enter** saves, **Esc** discards, **Backspace** takes back a click.

  The full guide is in [docs/GUIDE.md](docs/GUIDE.md). The model loads in the
  background when the server starts. If `weights/mobile_sam.pt` (about 40 MB) is
  missing, the first start downloads it there. To try SAM 2.1-tiny instead, run
  `-m app.server --sam sam2.1_t.pt`.
- **Suggestions (assisted mode):** a detector proposes boxes named with your
  classes, drawn dashed in yellow.
  - Choose the detector in the Suggestions panel: **YOLO11n** (80 COCO classes,
    fast) or **YOLOE** (any class name you add, slower).
  - Click a suggestion to accept it: SAM outlines it. Right-click a suggestion
    to reject it.
  - **S** suggests again; **Shift+Enter** accepts all of them.
  - The slider sets the lowest confidence shown.
  - If missing, the first start downloads `yolo11n.pt`, `yoloe-11s-seg.pt` and YOLOE's text
    encoder.
- **Choosing classes:** a new project opens the **class picker** (step 2 of a
  new project).
  - Tick any of the 80 common objects (both detectors can suggest these), or type
    your own names (YOLOE only).
  - Badges show which detector covers each class: `11n` and `E`.
  - Reopen the picker with **Edit classes**. Double-click a class to rename it.
  - The AI only ever suggests your classes. Objects it sees outside them are
    listed as "ignored", with a button to add them.
- **Classes:** as many as you like. **1–9, 0** pick the first ten. **/** finds or
  adds any class by name. A near-duplicate annotation of the same class triggers
  a warning.
- **Export:** the Export button opens a dialog. Tick the formats you need,
  and you get one zip with just those:
  - **COCO JSON** `coco/annotations.json`: boxes and outlines
  - **YOLO detection** `yolo-detect/` (images, labels, data.yaml): boxes
  - **YOLO segmentation** `yolo-segment/` (images, labels, data.yaml): outlines
  - **Pascal VOC XML** `voc/Annotations/`: boxes
  - **PNG masks** `masks/`: outlines, pixel value = class index
  - **CSV table** `labels.csv`: one row per label
  - **Photos with labels drawn** `preview/*.jpg`: each label in its class
    colour with a name tag, for checking and sharing. Not for training: a
    model needs the clean photo plus the label file.

  Options: include the photos (on by default; the YOLO datasets need them), and
  only photos that have labels. `classes.txt` and a `README.txt` describing the
  zip are always included. The dialog remembers your last choice.

## Evaluation (Phase 5)

The notebooks are in `eval/` and run inside **VS Code**: open a `.ipynb` file,
choose **Select Kernel → `.venv311`** at the top right, then Run All. They need
`pandas` and `ipykernel`, both in `requirements.txt`.

1. `01_build_eval_set.ipynb`: COCO val2017 subsets (downloads 241 MB of
   annotations once).
2. `02_model_quality.ipynb`: SAM, YOLO11n and YOLOE quality. Automatic, about
   15 min on CPU.
3. `01b_build_balanced_study.ipynb`: the class-balanced study set (4 images per
   class, split evenly), used for the main effort study. The first, random study
   is kept as the pilot.
4. `03_effort_study.ipynb`: the timed manual vs assisted session. The protocol is
   at the top. Set `RUN = "balanced"` or `"pilot"`.
5. `04_scratch_vs_pretrained.ipynb`: compares the pretrained YOLO11n with the two
   we trained ourselves (next section). Run the training notebook first.

Results are written to `eval/results/`.

## Training our own YOLO11n (Phase 5b, on a GPU)

Kontur suggests objects with YOLO11n **pretrained** on COCO by Ultralytics: the
file `weights/yolo11n.pt`. To measure what those pretrained weights are worth,
`training/train_yolo11n_coco5.ipynb` trains the **same network ourselves**, and
`eval/04_scratch_vs_pretrained.ipynb` compares the three:

| | Model | Starts from | Trained by |
|---|---|---|---|
| A | YOLO11n, the one Kontur uses | `weights/yolo11n.pt` as downloaded | Ultralytics (evaluated only) |
| B | YOLO11n **from scratch** | **random weights** (`yolo11n.yaml`) | us |
| C | YOLO11n fine-tuned | a copy of `weights/yolo11n.pt` | us, same data and epochs as B |

Five classes (person, car, bicycle, dog, chair: the effort-study classes). Train
and val come from COCO train2017, the test from COCO val2017, so no model is
compared on images it was trained or tuned on:

| Split | From | Used for |
|---|---|---|
| train | class-balanced 20k images of COCO train2017 | training B and C |
| val | 1,000 other train2017 images | picking the best epoch |
| test | every COCO val2017 image with the classes | only the comparison in `eval/04` |

**On the data lab:**

1. Clone the repository and run `pip install -r requirements.txt` (this same file).
   Then check the GPU is visible:
   `python -c "import torch; print(torch.cuda.is_available())"` must print `True`.
2. Open `training/train_yolo11n_coco5.ipynb`. In **Settings**, `DATA_DIR` is where
   COCO is downloaded (default `training/data/`; or set the environment variable
   `KONTUR_DATA` so both notebooks find it). Run All: it downloads the COCO
   annotations (241 MB) and only the images it needs (about 3–4 GB), writes the
   YOLO labels, then trains B and C (about 2–4 h each on a modern GPU). If the
   session stops, set `RESUME = True` and run the training cell again; downloads
   skip what is already there.
3. Open `eval/04_scratch_vs_pretrained.ipynb` and Run All.

**What it writes:**

| Folder | Holds | In git |
|---|---|---|
| `training/data/` | COCO annotations, images, YOLO labels, `coco5.yaml` | no (large, re-downloadable) |
| `training/runs/` | Ultralytics' full training logs and checkpoints | no |
| `training/trained/` | **our** weights: `yolo11n_B_scratch_coco5.pt`, `yolo11n_C_finetune_coco5.pt` (~5 MB each) | **yes** |
| `training/results/` | GPU, versions, settings and hours (`environment.json`); the image ids of every split (`dataset.json`); each run's curves, confusion matrix and settings | **yes** |
| `eval/results/scratch_vs_pretrained/` | metrics per model, `comparison.csv`, `ap_per_class.png`, `learning_curves.png` | **yes** (raw detections: no) |

## Folder layout

| Folder / file | Holds |
|---|---|
| `app/` | The app: Python server (`server.py`, `models.py`, …) and the browser UI (`static/`) |
| `weights/` | The four pretrained weight files (MobileSAM, YOLO11n, YOLOE-11s, YOLOE's text encoder) |
| `eval/` | All evaluation: notebooks 01–03 and `evallib.py`, plus 04 (pretrained vs from scratch vs fine-tuned); `data/` (COCO subsets), `results/`, `studies/` (the two effort studies) |
| `training/` | Model creation: `train_yolo11n_coco5.ipynb` trains YOLO11n from scratch and fine-tuned (run on a GPU); `trained/` holds our weights, `results/` the training evidence. See "Training our own YOLO11n" above |
| `docs/` | Project documents, below |
| `report/` | The exam report (`report.md`) and its outline |
| `data/` | Created at run time: your projects (`projects.json`, `projects/<id>/`, `trash/`) |
| `archive/satellite/` | The October satellite labeller, kept intact |
| `requirements.txt` | Python dependencies |

## Documents (`docs/`)

| File | Holds |
|---|---|
| `GUIDE.md` | How the AI assistance works, for users |
| `phase.md` | Phases, what "done" means, status table |
| `design.md` | What is built, for whom, and why: the key decisions |
| `architecture.md` | How the pieces fit: components, data flow, files, API |
| `tech.md` | Every technology choice with its reason, what was not used, the model weights |
| `changes.md` | Build log: what was built, what broke, how it was fixed |

## Credits

Libraries in use: FastAPI, Uvicorn, Pillow, Pydantic, OpenCV, PyTorch, and
Ultralytics (AGPL-3.0) for model loading.

Pretrained models, **used as downloaded** in the app (the files in `weights/` are
Ultralytics' official downloads from 17 Nov 2026; fingerprints in `docs/tech.md`,
"Model weights"). Separately, `training/` trains our own YOLO11n models from
scratch and fine-tuned; those are in `training/trained/`, not in `weights/`:

- **MobileSAM:** C. Zhang et al., *Faster Segment Anything: Towards Lightweight
  SAM for Mobile Applications*, arXiv:2306.14289, 2023.
- **Segment Anything** (the model MobileSAM distils): A. Kirillov et al., ICCV
  2023.
- **SAM 2** (optional): N. Ravi et al., *SAM 2: Segment Anything in Images and
  Videos*, arXiv:2408.00714, 2024.

- **YOLO11:** G. Jocher and J. Qiu, Ultralytics YOLO11, 2024 (software).
- **YOLOE:** A. Wang et al., *YOLOE: Real-Time Seeing Anything*,
  arXiv:2503.07465, 2025.

Dataset: **COCO 2017** (evaluation and training): T.-Y. Lin et al., *Microsoft
COCO: Common Objects in Context*, ECCV 2014.

## Licence

Kontur is released under the **GNU AGPL-3.0** (see `LICENSE`), the same licence as
Ultralytics, which it uses to load and train its models.

UI typefaces: IBM Plex Sans, Sans Condensed and Mono, and Big Shoulders Display
(SIL Open Font License),
loaded from Google Fonts. Without internet the page falls back to system fonts. No
existing annotation tool is used or wrapped: the canvas, editing, storage and
export are written for this project.
