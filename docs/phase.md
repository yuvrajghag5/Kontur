# Project Phases

AI Vision — exam project. **Due Sunday 29 November 2026.**
An AI-assisted image annotation web application.

## The goal, in one paragraph

A user uploads photos into a browser-based tool and labels the objects in them
with boxes and polygons. Instead of tracing every outline by hand, they click on
an object and a segmentation model draws the outline, or they accept boxes a
detector has already proposed. Labels are saved and exported in standard formats
(COCO JSON, YOLO txt, PNG masks). The project must also **prove** the assistance
helps: how accurate the models are, and how much time and how many clicks they
save compared with labelling by hand.

## Direction (decided 17 Nov 2026)

- **Photos first.** The October satellite mode is archived intact in
  `archive/satellite/` (see its README). It may come back as a second image type
  if there is time after Phase 5.
- **Evidence is measured on a COCO val2017 subset**, which has exact ground-truth
  masks and boxes.
- The October satellite click log is kept as a record, but it is **not** the
  exam's evidence: its manual baseline is only 56 labels, and the masks it
  produced no longer exist (see `changes.md`, "Direction change").

## Status at a glance

| Phase | What it produces | State |
|---|---|---|
| 0. Setup | `.venv311` (Python 3.11), all packages in `requirements.txt`; seven docs + `GUIDE.md` | **done**; torch is the CPU build (everything runs on CPU) |
| 1. Manual annotation core | Upload, canvas, boxes + polygons, classes, edit/delete, undo, zoom/pan, save, interaction log | **done, run and used** (17 Nov; both studies on 25 Nov) |
| 2. Export | COCO JSON, YOLO txt, PNG masks, one zip | **done, verified** (17 Nov: COCO and YOLO boxes agree to 0.0004 px) |
| 3. AI assist: click-to-segment | One click (+ more clicks to refine) → object outline, via MobileSAM | **done, run and measured** (mIoU 0.57 after 1 click → 0.78 after 5) |
| 4. AI assist: auto-suggest | YOLO11n **or** YOLOE (selector) proposes boxes; accept → SAM turns the box into a polygon; plus the UI redesign | **done, run and measured** (AP 0.49 / 0.44) |
| 4b. Class picker + AI transparency | Choose classes first; coverage badges; YOLOE decoys; "ignored" line; rename | **done, run** (used in the balanced study, 25 Nov) |
| 4c. Model turn-taking | One lock for all model work; suggestions before encode | **done, confirmed working by Yuvraj** (25 Nov) |
| 4d. Projects + home page | Home → new project → classes → photos → label; one folder per project; old data kept in place | **done, run by Yuvraj** (25 Nov) |
| 4e. Kontur: name, look, folders, motion | New name; hero with looping demo; card mosaics; delete on every card; folder upload (picker + drop); marching-ants AI proposals; reduced motion respected | **done, run by Yuvraj** (25 Nov) |
| 4f. Export dialog | Choose formats: COCO, YOLO detection, YOLO segmentation, Pascal VOC, PNG masks, CSV, photos with labels drawn; include photos; only labelled photos | **done, run by Yuvraj** (25 Nov: "looks fine") |
| 5. **Evaluation (graded)** | Model quality on COCO; effort saved, manual vs assisted | **done** (`eval/01`, `01b`, `02`, `03`; pilot + balanced study). Results: `changes.md` Phase 5 §4, `eval/results/`. Re-run 03 with `RUN="pilot"` and `"balanced"` so saved outputs carry the final fixes |
| 5b. Own training: scratch vs pretrained | `training/train_yolo11n_coco.ipynb` trains YOLO11n from scratch (B) and fine-tuned (C) on all 80 COCO classes; `eval/04_scratch_vs_pretrained.ipynb` compares them with the pretrained A on all 5,000 COCO val2017 images | **prepared 27 Nov; data downloaded on the data lab (RTX A6000); training not started** |
| 5c. New-domain evaluation | `eval/05_new_domain_kvasir.ipynb`: SAM clicks + box, YOLOE zero-shot "polyp", YOLOE→SAM, on Kvasir-SEG (medical); side by side with COCO | **written 28 Nov, not yet run** |
| 6. Report and submission | Report, demo, source, citations | **in progress**: outline in `report/outline.md`, sections 1–5 drafted in `report/report.md` (due Sun 29 Nov) |
| 7. Satellite mode back in (optional) | Archived mode as a second image type | only if time allows |

Archived history: phases 1a–1e (satellite labeller, 22–26 Oct) are in
`changes.md` and `archive/satellite/`.

## The brief's requirements, mapped to phases

| Requirement | Phase |
|---|---|
| Annotate images: users can upload images and label them | 1 |
| AI assistance: at least one model actively helps, inside the app | 3, 4 |
| Usable output: annotations are saved and can be exported | 1 (save), 2 (export) |
| Evidence: model quality **and** effort saved vs manual | 5 (the log starts in 1) |
| Justify feature set, models, stack (problem solved + why this) | `design.md`, `tech.md` → report |
| Pretrained models/libraries allowed if cited | `README.md` credits, report |
| No forking or wrapping existing annotation tools | all: canvas, editing, storage and export written from scratch |

---

## Phase 1 — Manual annotation core

**Goal.** A tool that works with no AI at all. It is the manual baseline the AI is
measured against in Phase 5, so it must be a fair, usable tool, not a
deliberately clumsy one.

**Features.**
- Upload one or many images (drag-and-drop or file picker); list them; open one.
- **Box** tool (drag) and **polygon** tool (click points; Enter, or a click on the
  first point, closes it).
- A class list per project (add classes in the UI); number keys 1–9 pick a class.
- Select, recolour (change class) and delete annotations.
- Undo (Ctrl+Z).
- Zoom (wheel) and pan (drag with the right button, or Space + drag).
- Every change is saved to the server immediately.
- **The interaction log from day one:** every click, key, tool use and per-image
  time goes to `data/logs/events.jsonl`, tagged with the session's mode (manual or
  assisted). Phase 5 depends on it.

**Done when.** Upload an image, label it fully by hand, restart the server, and
the labels are still there and export correctly.

## Phase 2 — Export

COCO JSON (boxes + polygon segmentation), YOLO detection txt + `data.yaml`, and
PNG masks (class index per pixel), all in one zip.

**Done when.** `pycocotools` loads the exported JSON, and a YOLO txt line
re-projects onto the drawn box.

## Phase 3 — AI assist: click-to-segment

One left-click on an object → MobileSAM returns a mask → it is shown as a dashed
proposal polygon. More left-clicks add to it; right-clicks remove. Enter accepts it
with the current class; Esc discards it. A drawn box can also be the prompt.

**Speed.** The image encoder runs once when an image opens, and its embedding is
cached; each click then runs only the light decoder.

## Phase 4 — AI assist: auto-suggest

On demand (a button or key), YOLO11n proposes boxes for the 80 COCO classes, shown
dashed. Accept or reject each with one key. Accepting can also run SAM with the box
as prompt, giving a polygon. A confidence slider controls what is shown.

## Phase 5 — Evaluation (graded deliverable)

Two separate questions, measured separately, on a COCO val2017 subset (about 100
images, with exact masks and boxes).

**(a) How good are the models?** These are automated scripts that Yuvraj runs.
- **SAM, click-to-segment:** the standard interactive-segmentation protocol.
  - The first simulated click goes at the point inside the object farthest from
    its edge. Each next click goes at the centre of the largest error region:
    positive where the object is missed, negative where it spills over.
  - Report mean IoU after 1, 3 and 5 clicks, and NoC@85 / NoC@90: the clicks
    needed to reach 85% / 90% IoU.
  - Also report IoU when SAM is prompted with the ground-truth box.
- **YOLO, auto-suggest:** COCO mAP@0.5 and mAP@[.5:.95] with `pycocotools`, plus
  precision and recall at the confidence the UI uses.

**(b) How much effort does it save?** These are real labelling sessions in the app.
- Split the subset into two halves. Label half A in manual mode and half B in
  assisted mode. Ideally a second person labels the other way round, which
  cancels out learning effects.
- From the log, per object: seconds, clicks, and the IoU of the final annotation
  against ground truth. That way faster is never bought with worse.
- Supporting number: polygon vertices in the ground truth (≈ clicks to trace by
  hand) against NoC from (a).

**Done when.** Both tables exist, the protocol is written down, and the result is
reported honestly, including where the AI is slower or wrong.

## Phase 6 — Report and submission

Justify every feature, model and technology: what problem it solves and why this
choice. Use `changes.md` for the issues-and-fixes material, the Phase 5 tables as
results, and credits for every pretrained model and library.

## Open questions

1. Report length and format, and whether a live demo is expected: unknown.
2. Solo or team: assumed solo.
