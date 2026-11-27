# Design

What is being built, for whom, and why. The *why* behind the decisions.
For the tools see `tech.md`; for how the pieces fit see `architecture.md`.

> **25 Nov 2026:** the photo annotator (named **Kontur**) is built and evaluated. Decisions 1–6 and 9–14 apply to the photo annotator. Decisions
> 7–8 belong to the archived satellite mode (`archive/satellite/`) and are kept as
> history.

## The problem

Labelling images for computer vision is slow, repetitive work. Drawing a careful
polygon around one object takes dozens of clicks; a dataset has thousands of
objects. Most of that effort goes on things a pretrained model can already
roughly see — the outline of a car, the position of a person.

## Who it is for

Someone building a small, custom dataset — a student, a researcher, a small
team — who needs boxes or masks on a few hundred to a few thousand images and
has a laptop-class GPU, not a cloud budget.

## The idea

**The human decides, the model draws.** The user's job shifts from tracing
outlines to pointing at objects and approving or correcting what the model
proposes. Every suggestion stays editable, so the model never has the final say.

## Constraints

| Constraint | Source | Consequence |
|---|---|---|
| **Must not fork or wrap existing annotation tools** (CVAT, Label Studio, VIA, LabelMe, Roboflow, etc.) | The brief | The canvas, shape editing, storage and export are written from scratch. This is a deliberate choice forced by the rules, not reinventing the wheel by accident. |
| Pretrained models and libraries allowed **if cited** | The brief | Models are used pretrained; every one is cited in README and report. |
| AI must be **integrated**, not a separate script | The brief | Models run behind the app's own API and respond to clicks live. |
| Must **prove** it helps | The brief | Interaction logging is built in from Phase 1; evaluation is its own phase. |
| 4 GB GPU (RTX 3050) | Hardware | Only small model variants. See `tech.md`. |
| Runs locally | Practical | No cloud account needed by the marker; no image leaves the machine. |

## Key decisions and trade-offs

### 1. Two kinds of assistance, not one

- **Click-to-segment** (promptable segmentation) helps with *any* object, even
  classes the model has never been trained on. It saves the most clicks on
  polygons.
- **Auto-suggest** (detection) saves the user from even pointing — but only for
  classes the detector knows.

Together they cover both cases: known common objects get proposed automatically;
anything else is one click away. Either alone leaves an obvious gap.

*Trade-off:* two models compete for memory and time. Both are small variants
(MobileSAM, YOLO11n) that run on a CPU.

### 2. A real manual mode, not a strawman

The effort-saved number is only meaningful if the manual baseline is a fair,
usable tool (shortcuts, undo, polygon editing). The comparison is the same tool
with AI on versus off — so the only difference measured is the AI.

### 3. Logging built in from the start

Time and clicks are recorded per image and per object from Phase 1. Evaluation
then reads from the log rather than from a stopwatch, which is more accurate and
repeatable.

*Trade-off:* a little extra work early; saves redoing the manual baseline later.

### 4. Suggestions are visibly different from accepted labels

Proposed shapes are drawn dashed and must be accepted. This prevents unchecked
model output silently entering the dataset — the main risk of AI-assisted
labelling is that people stop looking.

### 5. Standard export formats

COCO JSON, YOLO txt and PNG masks, so the output trains real models without
conversion. "Usable output" in the brief means usable by other tools.

### 6. Browser front end, Python back end

The models are Python; the annotation surface needs to be interactive and
visual. A browser canvas is the most direct way to draw and edit shapes, and a
Python API keeps the models where their libraries are.

### 7. Optional: satellite imagery (Phase 7, optional)

The same tool could label Sentinel-2 imagery for the Deep Learning course
project. Not part of the core design until the lecturer confirms it fits the
brief, and it must not delay the core phases.

### 8. The first assist is a measuring instrument, not a model

For satellite land cover, the selection was already good (one click caught
357,547 of 360,000 px on Arabia). What held the user up was deciding *which
class* a zone is. So the first AI assistance proposes a class from three standard
spectral indices, summarised over the whole year, and shows the numbers. It never
assigns, and says "borderline" or "mixed selection" rather than inventing
confidence. It reads only the image already on screen and is a fixed formula, so
labels made with it remain self-made: a ruler, not a labeller.

Every assignment logs whether the human agreed with the suggestion. Together with
the earlier manual-only log, that gives a manual-versus-assisted comparison
measured on real work.

### 9. Photos first, satellite archived (17 Nov 2026)

The brief asks for an *image* annotation platform where *computer vision models*
help, with uploads, standard exports and measurable evidence. Ordinary photos fit
all four directly. The October satellite tool did not:

- It had no upload and no standard export.
- Its assistance was a fixed index formula, not a model.
- Its evidence could not be scored: its only "manual" data was 56 early labels,
  and the masks were later deleted.

So the photo annotator comes first. The satellite tool is kept intact and may
return as a second image type.

### 10. Evidence on COCO, measured two separate ways

- **Model quality.** Measured automatically against exact ground truth, using the
  standard protocols:
  - for SAM: IoU after k simulated clicks, and the clicks needed to reach 85% and
    90% IoU;
  - for YOLO: COCO mAP.
- **Effort saved.** Measured on real labelling sessions in the same app, manual
  versus assisted mode. Time and clicks per object come from the log, and the
  quality of each final annotation is scored against COCO ground truth, so that
  "faster" is never bought with "worse".

The two measurements answer different questions, and neither stands in for the
other.

### 11. Projects, and a fixed order to start one (Phase 4d)

A real dataset is labelled over many sessions, and one person often has several.
So the app opens on a **home page of projects**, and a new project follows one
order: **name → classes → photos → labelling**.

- **Classes come before photos** on purpose: the detectors only ever suggest the
  project's classes (decision from Phase 4b), so the AI is set up before the
  first photo opens.
- **Each card shows progress** (photos labelled out of total), so the home page
  answers "where was I?".
- **Delete never erases**: a project moves to `trash/`, so a misclick costs nothing.

*Trade-off:* one project open at a time. That is fine for a single-user local tool.

### 12. A name and a look that say what the tool does (Phase 4e)

**Kontur** is German for *outline*, which is what the model draws. The headline
says the whole idea in three lines: *Point at it. The model traces it. You decide.*
The home page shows it as a looping demo (click → trace → save) rather than
explaining it in text.

### 13. Motion only where it carries meaning (Phase 4e)

The colour rule (yellow = the AI proposes, cobalt = you decided) is extended to
motion: **anything the AI proposes moves** (marching dashed edges on suggestions
and on an open outline), **saved labels stand still**. Unsaved model output can
therefore be told apart from accepted labels at a glance, the risk the pilot
study showed ("Accept all" let wrong outlines in). Other motion is short and
functional: cards enter, dialogs open, a drop zone appears. With the system
"reduce motion" setting on, all of it is off.

### 14. Export: the user picks the formats (Phase 4f)

Different tools read different formats, so the export asks rather than dumping
everything. Each format says what it holds and what it is for, and the dialog
warns before a choice drops something (outline formats skip boxes; YOLO without
photos cannot train).

**Labels are exported as separate files, not drawn on the photos.** A model
trains on the clean photo plus the label as numbers. Boxes burned into the
pixels would teach it the coloured rectangles and could never be edited. Drawn-on
photos are still offered, marked "for viewing, not training".

## What is deliberately out of scope

- Multi-user accounts, permissions, review workflows.
- Video annotation and object tracking.
- Training or fine-tuning models inside the app (possible later stretch goal:
  active learning).
- Cloud deployment.
