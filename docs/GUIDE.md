# How AI-assisted annotation works in Kontur

A user guide to the **AI outline** tool. It explains what the model does, how to
use it well, how fast it is, and what it cannot do.

## In one sentence

You point at an object, and a segmentation model draws its outline. You check it,
correct it with a few more clicks if needed, and save it with the class you choose.

## What the AI does, and what it does not

| It does | It does not |
|---|---|
| Find the **edges** of whatever you click: a cat, a cup, half a sofa, a shadow | Know **what** the object is. You pick the class. |
| Give an exact outline (a polygon) instead of a rough box | Save anything by itself. Nothing is saved until you save it. |
| Work on objects it has never seen in training ("segment anything") | Run in **manual** mode. Manual mode has no AI at all, so it is a fair baseline for the evaluation. |

The model is **MobileSAM**, a small, fast version of Meta's **Segment Anything**
(SAM). SAM was trained on SA-1B: 11 million images with 1.1 billion object
masks. That is why it can outline almost anything.

## What happens inside, step by step

```
open an image ──► 1. ENCODE (once per image)          the slow part
                     the image encoder turns the whole picture into a
                     compact "embedding" and keeps it in memory

click ─────────► 2. DECODE (every click)               the fast part
                     the prompt decoder combines the embedding with your
                     clicks (+ object / − not object) or your box and
                     predicts a mask: which pixels belong to the object

               ► 3. MASK → POLYGON
                     keep the largest piece, trace its edge,
                     simplify to about 1 pixel

               ► 4. PROPOSAL (dashed outline on screen)
                     save it (Enter, or click the next object) / correct it /
                     discard it (Esc)
```

**Why the split matters.** The encoder is the expensive step, and it runs once
per image. Every click after that reuses the stored embedding, so each correction
is cheap.

**Why one click can be ambiguous.** A click on a shirt could mean the shirt or
the whole person. For a single click, SAM gives three candidate masks and the
tool keeps the one SAM itself scores highest. If it picks the wrong one, add a
click (Shift+click) or take a part away (right-click).

## Using it

0. The app opens on **Projects**. Open a project's card, or start a **New
   project**: give it a name, choose its classes in the picker, then add photos.
1. Switch **Mode** to **assisted** (top right). The banner on the image shows
   "loading the AI model" the first time, then "reading this image".
2. Press **A**, or click **AI outline**.
3. Pick the class: **1–9 / 0** for the first ten, or **/** to find or add any
   class by name. You can also pick it *after* the outline appears and before
   saving; the open outline takes the new class.
4. **Click on the object.** A dashed outline appears.
5. Fix it if needed:
   - **Shift+click** a part it missed: adds to *this* object.
   - **Right-click** a part it wrongly took: removes it.
   - **Backspace** takes back your last click.
6. **Click the next object.** The previous outline is saved automatically. Or
   press **Enter** to save, or **Esc** to throw it away.
7. For small, thin or cluttered objects, **drag a box** around the object instead
   of clicking. A box is the clearest prompt SAM can get.

After saving, an AI outline is an ordinary polygon: you can drag its vertices in
Select mode (V), change its class, delete it, or undo (Ctrl+Z).

### Tips

- Click near the **middle** of the object, not on its edge.
- One plain click = one object. To build up one object from several clicks, hold
  **Shift**.
- If the outline covers two objects that touch, right-click on the one you did
  not mean.
- People, animals, vehicles and furniture work best. Glass, reflections, very thin
  things (cables, chair legs) and tiny objects are harder: use a box, or draw a
  polygon by hand.

## Suggestions: the AI finds objects for you

The AI outline needs you to point. **Suggestions** go one step further: a
detector looks at the whole photo and proposes boxes, already named with your
classes. They appear as dashed **yellow** boxes; yellow always means "the AI
proposes this".

1. In assisted mode, suggestions run when a photo opens (switch this off in the
   Suggestions panel), or press **S**.
2. **Click a suggestion** to accept it. SAM then outlines the object inside the
   box, so you get a polygon, not just a box. **Right-click** a suggestion to
   reject it.
3. **Shift+Enter** accepts every suggestion shown.
4. The **confidence slider** hides weak guesses. Moving it is instant: the
   detector already returned everything above 15%.
5. Suggestions you have already labelled disappear by themselves.

### Your classes decide what the AI looks for

- A new project starts by asking what you will label (the class picker).
  Suggestions only ever use those classes.
- Each class shows two small badges:
  - **11n**, lit, when YOLO11n can suggest it;
  - **E** for YOLOE, which can suggest any name.
- If YOLO11n knows your label under a slightly different spelling (other case,
  spacing, or a plural), you see its name next to yours.
- No label list is built into Kontur. The only names offered as shortcuts are the
  ones YOLO11n was trained on, read from its model file.
- If the detector sees something that is *not* one of your classes, it is not
  suggested, but the panel says so ("Ignored: dog ×2"). One click adds it as a
  class.
- When at least one of your labels is a name the fast detector knows, YOLOE is
  also given the other names it knows as "decoys", so an everyday object outside
  your labels gets its own name and is left out instead of being forced into your
  nearest label. When **all** your labels are new (a medical or product project),
  decoys are switched off: on such images they made YOLOE call real targets by
  everyday names and drop them (measured in notebook 05).
- **Best guesses.** For a label no detector was trained on, YOLOE's confidence is
  low even when it is right (below 5% for "polyp" in notebook 05, where its top box
  was a polyp 74% of the time). So for such labels Kontur shows its **3 best boxes
  per image**, dotted and marked "guess", regardless of the slider. **Accept all
  never accepts guesses**: check each one. Switch them off with "Best guesses for
  your own labels" in the Suggestions panel.

### Which detector?

| | YOLO11n | YOLOE |
|---|---|---|
| Suggests | Only the 80 COCO classes (person, car, chair, tv, ...), matched to your class names | **Any class name you add**: cupboard, lamp, mirror, ... |
| Speed | Faster | Slower |
| Accuracy | Better on common COCO objects | Good on clear names, more false alarms on vague ones |
| Best when | Your classes are everyday COCO objects | Your classes are your own |

If YOLO11n cannot suggest some of your classes, the panel lists them.

## How fast it is

Measured on this laptop, CPU only (notebook 02, models run one at a time):

| Step | When | Time |
|---|---|---|
| Downloads (SAM 40 MB, YOLO models, YOLOE's 600 MB text encoder) | very first start only | depends on the internet |
| Load the models | each server start, **in the background** | SAM 4 s, YOLO11n 2.5 s, YOLOE 6.7 s |
| Suggestions | when a photo opens | **0.06 s** (YOLO11n), **0.19 s** (YOLOE) |
| Encode the image for SAM | once per photo, after the suggestions | **0.83 s** (median) |
| Each click or box | every prompt | **0.07 s** (median) |

What changed along the way:

- **The 61 s first wait** in the first test came from the download, loading the
  model and the first encode, all at once. Since 17 Nov the models load when the
  server starts.
- **The models fought over the processor.** In the effort study (25 Nov) they still
  ran side by side, and suggestions took up to 5 s and the encode up to 10 s. Since
  25 Nov they **take turns**: suggestions first, then the encode. The time any
  request waited for its turn is logged as `wait_ms`.

**With the GPU** (RTX 3050), everything would be several times faster still. The
installed PyTorch is the CPU-only build; see `tech.md`.

## Reading the screen: what moves, and why

Anything the AI **proposes** is yellow and has a slowly **moving dashed edge**:
suggestion boxes, and an outline you have not saved yet. Once you accept it, it
becomes an ordinary label in its class colour and **stands still**. So a glance
tells you what is saved and what is only a proposal. (With your system's
"reduce motion" setting on, nothing moves; the yellow dashes still mark
proposals.)

## Exporting: label files, or photos with labels drawn

**Export** asks which formats you want. The training formats (COCO, YOLO, Pascal
VOC, PNG masks, CSV) keep the photo clean and store each label as numbers, which
is what a model learns from. **Photos with labels drawn** is for looking at your
work or sharing it, not for training.

## What is recorded, and why

Every AI step is logged in `data/logs/events.jsonl`:

- clicks with their label,
- each model answer with its time and SAM's own score,
- each save (`ai_accept`, with how many clicks it took and how long),
- each discard.

Together with manual-mode sessions, this is the raw data for the evaluation: how
many clicks and how many seconds per object, with and without the AI.

## Limits, said plainly

- **One piece per outline.** If SAM's mask has several separate pieces, only the
  largest is kept, because one click means one object.
- **Holes are ignored** (a doughnut becomes a disc). This matches COCO's polygon
  format.
- **SAM does not name things.** Names come from you, or from a detector's
  suggestion.
- **The encode runs on the CPU** unless a CUDA build of PyTorch is installed.

## Model credits

- **MobileSAM:** C. Zhang et al., *Faster Segment Anything: Towards Lightweight
  SAM for Mobile Applications*, 2023.
- **Segment Anything:** A. Kirillov et al., ICCV 2023.
- Loaded through the **Ultralytics** library (AGPL-3.0).
