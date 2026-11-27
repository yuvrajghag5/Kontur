"""Evaluation code shared by the three notebooks in eval/.

Phase 5 answers two separate questions on COCO val2017, the standard held-out
set that has exact ground-truth outlines and boxes:

(a) How good are the models?   -> notebook 02, fully automatic
    - SAM click-to-segment: IoU after k simulated clicks, clicks needed (NoC)
    - YOLO11n and YOLOE suggestions: COCO mAP, precision/recall at the UI default
    - YOLO -> SAM pipeline: outline quality of an accepted correct suggestion
(b) How much effort does the AI save?   -> notebook 03, from real sessions
    - seconds and clicks per object, manual vs assisted, and the quality of the
      final labels against ground truth

The models are run through the app's OWN code (app/models.py), so the numbers
describe exactly what a user of the app gets.
"""

from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import urllib.request
import zipfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent          # the project folder
EVAL = ROOT / "eval"
DATA = EVAL / "data"
ANN_ZIP_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
IMG_URL = "http://images.cocodataset.org/val2017/{:012d}.jpg"
VAL_JSON = DATA / "instances_val2017.json"

SEED = 2026
N_MODEL_IMAGES = 100        # images for the automatic model evaluation
N_EFFORT_IMAGES = 20        # images for the timed study: 10 manual + 10 assisted
# The timed study asks for these classes only, objects at least 32x32 px
# ("medium" and "large" in COCO's own size terms), so a session stays doable.
EFFORT_CLASSES = ["person", "car", "bicycle", "dog", "chair"]
MIN_EFFORT_AREA = 32 * 32
# Images already used for practice in the app (data/test_image), never evaluated on.
PRACTICE_IDS = {39769, 397133, 139, 785, 632, 1000, 252219, 87038, 174482, 37777,
                458054, 6818, 480985, 331352, 2587}


def setup():
    """Run from the project folder, whatever folder Jupyter started in.

    The models are loaded by file name, and Ultralytics looks in the current
    folder first. The weights and YOLOE's 600 MB text encoder already sit in the
    project folder; started from eval/, it would download them all again."""
    os.chdir(ROOT)
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    DATA.mkdir(parents=True, exist_ok=True)


# ============================================================== data (notebook 01)

def download(url: str, dest: Path, what: str = "") -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"downloading {what or url} ...")
    try:
        urllib.request.urlretrieve(url, tmp)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        # Seen on 25 Nov: "HTTP Error 403: Forbidden: body content-type denied" for the
        # .zip, while the server itself answered 200. That wording comes from a local
        # network filter (antivirus web shield / proxy) blocking Python, not from COCO.
        raise RuntimeError(
            f"Could not download {url}\n  ({type(e).__name__}: {e})\n"
            f"Download it in your browser instead and save it as:\n  {dest}\n"
            f"then run this cell again; the file will be used as it is.") from None
    tmp.replace(dest)
    return dest


def get_val_annotations() -> Path:
    """COCO's official val2017 annotations. Only distributed inside the 241 MB
    train+val zip, so: download once, keep just instances_val2017.json."""
    if VAL_JSON.exists():
        return VAL_JSON
    z = download(ANN_ZIP_URL, DATA / "annotations_trainval2017.zip", "COCO annotations (241 MB, once)")
    with zipfile.ZipFile(z) as zf:
        with zf.open("annotations/instances_val2017.json") as src, VAL_JSON.open("wb") as dst:
            dst.write(src.read())
    return VAL_JSON


def load_coco():
    from pycocotools.coco import COCO
    return COCO(str(get_val_annotations()))


def choose_subsets(coco) -> dict:
    """Pick the two disjoint image sets, reproducibly (fixed seed)."""
    rng = random.Random(SEED)
    target_ids = {c["id"] for c in coco.loadCats(coco.getCatIds(catNms=EFFORT_CLASSES))}

    def targets(img_id):
        anns = coco.loadAnns(coco.getAnnIds(imgIds=img_id, iscrowd=None))
        good = [a for a in anns if a["category_id"] in target_ids and not a["iscrowd"]
                and a["area"] >= MIN_EFFORT_AREA]
        crowd = [a for a in anns if a["category_id"] in target_ids and a["iscrowd"]]
        return good, crowd

    all_ids = sorted(i for i in coco.getImgIds() if i not in PRACTICE_IDS)
    rng.shuffle(all_ids)

    # Effort study: 1-6 target objects, no crowd regions of target classes, so
    # every image is a fair, finishable task.
    effort = []
    for i in all_ids:
        good, crowd = targets(i)
        if 1 <= len(good) <= 6 and not crowd:
            effort.append((i, len(good)))
        if len(effort) == N_EFFORT_IMAGES:
            break
    # Balance the two halves by object count: sort, then deal alternately.
    effort.sort(key=lambda t: -t[1])
    half_a = [i for k, (i, _) in enumerate(effort) if k % 2 == 0]
    half_b = [i for k, (i, _) in enumerate(effort) if k % 2 == 1]

    used = {i for i, _ in effort}
    model = [i for i in all_ids if i not in used and coco.getAnnIds(imgIds=i, iscrowd=False)][:N_MODEL_IMAGES]
    out = {"seed": SEED, "model": model, "effort_a": half_a, "effort_b": half_b,
           "effort_classes": EFFORT_CLASSES, "min_effort_area": MIN_EFFORT_AREA}
    (DATA / "subsets.json").write_text(json.dumps(out, indent=1))
    return out


def load_subsets() -> dict:
    return json.loads((DATA / "subsets.json").read_text())


# ---- the class-balanced study (rerun of the effort study, 25 Nov)
#
# The first study picked images at random among those with any study class. COCO
# is dominated by people, so the halves came out as A: 21 person, 8 chair, 1 car
# and B: 20 person, 4 car, 2 bicycle - no dog at all, and chairs (hard, thin,
# occluded) only in the manual half. The rerun picks images PER CLASS instead.

PER_CLASS = 4               # images per class: 2 go to A, 2 to B
MIN_MAIN_AREA = 64 * 64     # the class the image was picked for is clearly visible
MAX_REQUIRED = 5            # objects to label per image, keeps a session doable
MAX_OTHER_PERSONS = 2       # an image picked for dog/car/... is not mostly people


def choose_balanced(coco, exclude: set[int]) -> dict:
    """PER_CLASS images for each study class, split evenly between A and B.

    An image counts for a class when it has a non-crowd object of that class of
    at least 64x64 px. Images must have 1..MAX_REQUIRED required objects (any
    study class, >= 32x32), no crowd regions of study classes, and - when picked
    for a non-person class - at most MAX_OTHER_PERSONS people. Within each class
    the images are sorted by how many objects they need and dealt A, B, B, A,
    so both halves get the same classes AND similar amounts of work."""
    rng = random.Random(SEED + 1)
    cat = {c["name"]: c["id"] for c in coco.loadCats(coco.getCatIds(catNms=EFFORT_CLASSES))}
    ids = sorted(i for i in coco.getImgIds() if i not in exclude and i not in PRACTICE_IDS)
    rng.shuffle(ids)
    used: set[int] = set()
    half_a, half_b, per_class = [], [], {}
    for cls in EFFORT_CLASSES:
        picked = []
        for i in ids:
            if i in used:
                continue
            anns = coco.loadAnns(coco.getAnnIds(imgIds=i, catIds=list(cat.values())))
            if any(a["iscrowd"] for a in anns):
                continue
            req = [a for a in anns if a["area"] >= MIN_EFFORT_AREA]
            main = [a for a in req if a["category_id"] == cat[cls] and a["area"] >= MIN_MAIN_AREA]
            persons = sum(a["category_id"] == cat["person"] for a in req)
            if not main or not 1 <= len(req) <= MAX_REQUIRED:
                continue
            if cls != "person" and persons > MAX_OTHER_PERSONS:
                continue
            picked.append((i, len(req)))
            used.add(i)
            if len(picked) == PER_CLASS:
                break
        picked.sort(key=lambda t: -t[1])
        for k, (i, _) in enumerate(picked):
            (half_a if k % 4 in (0, 3) else half_b).append(i)
        per_class[cls] = [i for i, _ in picked]
    out = {"seed": SEED + 1, "effort_a": half_a, "effort_b": half_b, "picked_for": per_class,
           "effort_classes": EFFORT_CLASSES, "min_effort_area": MIN_EFFORT_AREA}
    (DATA / "subsets_balanced.json").write_text(json.dumps(out, indent=1))
    return out


def load_balanced() -> dict:
    return json.loads((DATA / "subsets_balanced.json").read_text())


def class_counts(coco, img_ids, classes=EFFORT_CLASSES, min_area: int = MIN_EFFORT_AREA) -> dict:
    """Required objects per class over a set of images (for checking balance)."""
    cat = {c["id"]: c["name"] for c in coco.loadCats(coco.getCatIds(catNms=classes))}
    out = {c: 0 for c in classes}
    for i in img_ids:
        for a in coco.loadAnns(coco.getAnnIds(imgIds=i, catIds=list(cat), iscrowd=False)):
            if a["area"] >= min_area:
                out[cat[a["category_id"]]] += 1
    return out


def image_path(img_id: int) -> Path:
    return download(IMG_URL.format(img_id), DATA / "images" / f"coco_{img_id:012d}.jpg")


def copy_effort_images(subsets: dict, folder_name: str = "effort") -> dict:
    """Put the study images in two folders, A and B, ready to upload."""
    import shutil
    out = {}
    for half in ("a", "b"):
        folder = DATA / folder_name / half.upper()
        folder.mkdir(parents=True, exist_ok=True)
        for i in subsets[f"effort_{half}"]:
            shutil.copy(image_path(i), folder / f"coco_{i:012d}.jpg")
        out[half.upper()] = folder
    return out


def coco_id_from_name(name: str) -> int | None:
    """'coco_000000123456.jpg' (as uploaded to the app) -> 123456."""
    m = re.search(r"(\d{6,12})", name)
    return int(m.group(1)) if m else None


# ============================================================== geometry helpers

def gt_mask(coco, ann) -> np.ndarray:
    return coco.annToMask(ann).astype(bool)


def polygon_to_mask(poly, h: int, w: int) -> np.ndarray:
    """Rasterise a polygon in the app's continuous pixel coordinates (vertex at
    a pixel centre = index + 0.5)."""
    m = np.zeros((h, w), np.uint8)
    if poly:
        pts = np.round(np.asarray(poly, np.float64) - 0.5).astype(np.int32)
        cv2.fillPoly(m, [pts], 1)
    return m.astype(bool)


def box_to_mask(box, h: int, w: int) -> np.ndarray:
    (x1, y1), (x2, y2) = box
    m = np.zeros((h, w), bool)
    m[int(round(y1)):int(round(y2)), int(round(x1)):int(round(x2))] = True
    return m


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def box_iou(a, b) -> float:
    """Boxes as [[x1, y1], [x2, y2]]."""
    (ax1, ay1), (ax2, ay2) = a
    (bx1, by1), (bx2, by2) = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def coco_box(ann):
    x, y, w, h = ann["bbox"]
    return [[x, y], [x + w, y + h]]


def size_bin(area: float) -> str:
    """COCO's own size classes."""
    return "small" if area < 32 ** 2 else "medium" if area < 96 ** 2 else "large"


# ============================================================== SAM click simulation (notebook 02)

def _deepest_point(region: np.ndarray):
    """The point inside a region farthest from its edge. Padding makes the
    image border count as an edge, as a person would also avoid it."""
    padded = np.pad(region.astype(np.uint8), 1)
    dt = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
    y, x = np.unravel_index(int(np.argmax(dt)), dt.shape)
    return float(dt[y, x]), [float(x) + 0.5, float(y) + 0.5]


def simulate_clicks(seg, path: Path, gt: np.ndarray, max_clicks: int = 5):
    """The standard interactive-segmentation protocol (as in RITM / SimpleClick):
    click 1 at the deepest point of the object; each further click at the
    deepest point of the largest error - positive if the model missed object
    there, negative if it spilled onto background. IoU is recorded after every
    click. Uses the app's ClickSegmenter, i.e. its polygon output."""
    h, w = gt.shape
    points, labels, ious, ms = [], [], [], []
    pred = np.zeros_like(gt)
    for _ in range(max_clicks):
        missed, spilled = gt & ~pred, pred & ~gt
        d_miss, p_miss = _deepest_point(missed) if missed.any() else (0.0, None)
        d_spill, p_spill = _deepest_point(spilled) if spilled.any() else (0.0, None)
        if p_miss is None and p_spill is None:
            ious.append(ious[-1] if ious else 1.0)
            continue
        if d_miss >= d_spill:
            points.append(p_miss); labels.append(1)
        else:
            points.append(p_spill); labels.append(0)
        r = seg.segment(path, points=points, labels=labels)
        ms.append(r["decode_ms"])
        pred = polygon_to_mask(r["polygon"], h, w)
        ious.append(mask_iou(pred, gt))
    return ious, ms


def noc(ious: list[float], target: float, max_clicks: int) -> tuple[int, bool]:
    """Number of clicks to reach `target` IoU; max_clicks (and False) if never."""
    for k, v in enumerate(ious, 1):
        if v >= target:
            return k, True
    return max_clicks, False


def eval_sam(coco, img_ids, max_instances: int = 300, max_clicks: int = 5,
             min_area: int = 16 * 16, weights: str | None = None, progress=True) -> list[dict]:
    """One row per object: IoU after each click, NoC@85/90, IoU from a box prompt."""
    from app.models import ClickSegmenter
    seg = ClickSegmenter(weights) if weights else ClickSegmenter()   # default: weights/mobile_sam.pt
    rng = random.Random(SEED)
    insts = [a for a in coco.loadAnns(coco.getAnnIds(imgIds=img_ids, iscrowd=False)) if a["area"] >= min_area]
    rng.shuffle(insts)
    insts = sorted(insts[:max_instances], key=lambda a: a["image_id"])   # group by image: encode once
    rows, encode_ms = [], {}
    it = insts
    if progress:
        from tqdm.auto import tqdm
        it = tqdm(insts, desc="SAM objects")
    for a in it:
        path = image_path(a["image_id"])
        if a["image_id"] not in encode_ms:
            encode_ms[a["image_id"]] = seg.prepare(path)["encode_ms"]
        gt = gt_mask(coco, a)
        ious, ms = simulate_clicks(seg, path, gt, max_clicks)
        rb = seg.segment(path, box=coco_box(a))
        box_iou_ = mask_iou(polygon_to_mask(rb["polygon"], *gt.shape), gt)
        n85, ok85 = noc(ious, 0.85, max_clicks)
        n90, ok90 = noc(ious, 0.90, max_clicks)
        rows.append({
            "ann_id": a["id"], "image_id": a["image_id"],
            "class": coco.loadCats(a["category_id"])[0]["name"],
            "area": a["area"], "size": size_bin(a["area"]),
            **{f"iou@{k}": ious[k - 1] for k in range(1, max_clicks + 1)},
            "noc85": n85, "reached85": ok85, "noc90": n90, "reached90": ok90,
            "iou_box": box_iou_, "decode_ms_mean": float(np.mean(ms)) if ms else None,
            "gt_vertices": sum(len(p) // 2 for p in a["segmentation"]) if isinstance(a["segmentation"], list) else None,
        })
    for r in rows:
        r["encode_ms"] = encode_ms[r["image_id"]]
    return rows


# ============================================================== detectors (notebook 02)

def run_detector(det, key: str, coco, img_ids, conf: float = 0.01, progress=True):
    """Run one detector on every image, prompted / mapped with the 80 COCO
    class names. Returns COCO-format detections and per-image times."""
    cats = coco.loadCats(coco.getCatIds())
    names = [c["name"] for c in cats]
    name_to_id = {c["name"]: c["id"] for c in cats}
    dets, ms = [], []
    it = img_ids
    if progress:
        from tqdm.auto import tqdm
        it = tqdm(img_ids, desc=key)
    for i in it:
        r = det.detect(key, image_path(i), names, conf=conf, max_det=100)
        ms.append(r["ms"])
        for s in r["suggestions"]:
            (x1, y1), (x2, y2) = s["box"]
            dets.append({"image_id": i, "category_id": name_to_id[s["class_name"]],
                         "bbox": [x1, y1, x2 - x1, y2 - y1], "score": s["score"]})
    return dets, ms


def coco_map(coco, dets, img_ids) -> dict:
    """Official COCO box AP via pycocotools, restricted to our images."""
    from pycocotools.cocoeval import COCOeval
    if not dets:
        return {k: 0.0 for k in ("AP", "AP50", "AP75", "AP_small", "AP_medium", "AP_large", "AR100")}
    dt = coco.loadRes(dets)
    ev = COCOeval(coco, dt, "bbox")
    ev.params.imgIds = list(img_ids)
    ev.evaluate(); ev.accumulate(); ev.summarize()
    s = ev.stats
    return {"AP": s[0], "AP50": s[1], "AP75": s[2], "AP_small": s[3], "AP_medium": s[4],
            "AP_large": s[5], "AR100": s[8]}


def precision_recall_at(coco, dets, img_ids, conf: float, iou_thr: float = 0.5,
                        with_matches: bool = False):
    """What a user sees at the UI's confidence: of the boxes shown, how many are
    right (precision); of the real objects, how many are suggested (recall).
    Greedy matching per image and class, highest score first, IoU >= 0.5.
    Crowd regions are neither counted as missed nor as false alarms."""
    tp = fp = 0
    n_gt = 0
    matches = []
    shown = [d for d in dets if d["score"] >= conf]
    for i in img_ids:
        anns = coco.loadAnns(coco.getAnnIds(imgIds=i))
        gts = [a for a in anns if not a["iscrowd"]]
        crowd = [a for a in anns if a["iscrowd"]]
        n_gt += len(gts)
        used = set()
        for d in sorted([d for d in shown if d["image_id"] == i], key=lambda d: -d["score"]):
            x, y, w, h = d["bbox"]
            db = [[x, y], [x + w, y + h]]
            best, best_iou = None, iou_thr
            for a in gts:
                if a["id"] in used or a["category_id"] != d["category_id"]:
                    continue
                v = box_iou(db, coco_box(a))
                if v >= best_iou:
                    best, best_iou = a, v
            if best is not None:
                used.add(best["id"]); tp += 1
                matches.append((d, best))
            elif any(c["category_id"] == d["category_id"] and box_iou(db, coco_box(c)) >= iou_thr for c in crowd):
                pass
            else:
                fp += 1
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / n_gt if n_gt else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    out = {"conf": conf, "shown": tp + fp, "correct": tp, "false_alarms": fp,
           "objects": n_gt, "precision": p, "recall": r, "f1": f1}
    return (out, matches) if with_matches else out


def eval_pipeline(coco, matches, max_n: int = 150, weights: str | None = None, progress=True) -> list[dict]:
    """Accepting a CORRECT suggestion: how good is the outline SAM then draws
    from that box? (This is exactly the app's suggestion-accept path.)"""
    from app.models import ClickSegmenter
    seg = ClickSegmenter(weights) if weights else ClickSegmenter()   # default: weights/mobile_sam.pt
    rng = random.Random(SEED)
    sample = list(matches)
    rng.shuffle(sample)
    sample = sorted(sample[:max_n], key=lambda m: m[1]["image_id"])
    rows = []
    it = sample
    if progress:
        from tqdm.auto import tqdm
        it = tqdm(sample, desc="YOLO -> SAM")
    for d, a in it:
        x, y, w, h = d["bbox"]
        path = image_path(a["image_id"])
        gt = gt_mask(coco, a)
        r = seg.segment(path, box=[[x, y], [x + w, y + h]])
        rows.append({"class": coco.loadCats(a["category_id"])[0]["name"], "size": size_bin(a["area"]),
                     "score": d["score"], "mask_iou": mask_iou(polygon_to_mask(r["polygon"], *gt.shape), gt)})
    return rows


# ============================================================== effort study (notebook 03)

IDLE_CAP_MS = 30_000     # a gap longer than this counts as 30 s: coffee breaks are not labelling


def load_study(data_dir: Path):
    """The study's own data folder (server started with --data): its database
    and its interaction log."""
    if not (data_dir / "annotator.db").exists():
        raise FileNotFoundError(
            f"No study data in {data_dir}.\nDo the timed study first (protocol at the top of this "
            f"notebook): start the app with\n  python -m app.server --data eval/studies/data_study\n"
            f"label half A in Manual mode and half B in Assisted mode, then run this cell again.")
    db = sqlite3.connect(data_dir / "annotator.db")
    db.row_factory = sqlite3.Row
    images = [dict(r) for r in db.execute("SELECT * FROM images")]
    classes = {r["id"]: r["name"] for r in db.execute("SELECT * FROM classes")}
    anns = []
    for r in db.execute("SELECT * FROM annotations"):
        a = dict(r); a["points"] = json.loads(a["points"]); a["class_name"] = classes[a["class_id"]]
        anns.append(a)
    events = [json.loads(l) for l in (data_dir / "logs" / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return images, anns, events


def is_effort_click(e: dict) -> bool:
    """A press on the photo that does labelling work. Left button always; right
    button only in the AI tool (remove-from-outline / reject a suggestion) -
    elsewhere it is a pan, i.e. navigation."""
    return e.get("event") == "click" and (e.get("button") == 0 or (e.get("button") == 2 and e.get("tool") == "ai"))


def panel_actions(ev: list[dict]) -> int:
    """Clicks on the side panels, which are work too but are not presses on the
    photo: picking a class or tool, Accept all, accepting / rejecting from the
    list, the Suggest button, changing detector or confidence.

    Found in the first study run (25 Nov): the assisted half showed 0 clicks
    because every label came from the "Accept all" button (9 presses), which the
    photo-click count did not see. A key press that triggered the same action is
    logged at the same millisecond and is already counted as a key, so those are
    skipped here."""
    key_t = {e["t"] for e in ev if e.get("event") == "key"}
    n = 0
    for e in ev:
        k = e.get("event")
        if e.get("t") in key_t:
            continue
        if k in ("class_pick", "tool", "sug_accept_all", "det_change", "sug_conf"):
            n += 1
        elif k in ("sug_accept", "sug_reject") and e.get("how") == "list":
            n += 1
        elif k == "sug_run" and e.get("why") == "button":
            n += 1
    return n


def image_effort(events: list[dict], image_id: int) -> dict:
    """Active time, clicks and keys spent on one image, and in which mode."""
    ev = sorted((e for e in events if e.get("image") == image_id and "t" in e), key=lambda e: e["t"])
    if not ev:
        return {"active_s": 0.0, "clicks": 0, "keys": 0, "mode": None}
    # A gap that starts with leaving the image is time spent ELSEWHERE (on other
    # images) until the user comes back: not this image's time. Found in the
    # balanced study (25 Nov), where revisited images had up to 30 s of phantom
    # time added per revisit by the idle cap.
    active = sum(min(b["t"] - a["t"], IDLE_CAP_MS) for a, b in zip(ev, ev[1:])
                 if a.get("event") != "image_leave")
    modes = [e.get("mode") for e in ev if e.get("event") in ("click", "ann_create", "key", "sug_accept")]
    mode = max(set(modes), key=modes.count) if modes else ev[0].get("mode")
    clicks = sum(is_effort_click(e) for e in ev)
    keys = sum(e.get("event") == "key" for e in ev)
    return {"active_s": active / 1000, "clicks": clicks, "keys": keys,
            "panel": (panel := panel_actions(ev)),
            "actions": clicks + keys + panel, "mode": mode,
            "undos": sum(e.get("event") == "undo" for e in ev),
            "ai_accepts": sum(e.get("event") in ("ai_accept", "sug_accept") for e in ev),
            "sug_rejects": sum(e.get("event") == "sug_reject" for e in ev)}


def per_class_scores(coco, images: list[dict], anns: list[dict], half_of: dict,
                     classes=EFFORT_CLASSES) -> list[dict]:
    """Found / required and mean IoU per class and half, so manual and assisted
    can be compared class by class (the pilot showed averages over different
    class mixes can mislead)."""
    rows = []
    for cls in classes:
        for half in ("A", "B"):
            req = found = 0
            ious: list[float] = []
            for img in images:
                cid = coco_id_from_name(img["name"])
                if half_of.get(cid) != half:
                    continue
                r = score_labels(coco, cid, [a for a in anns if a["image_id"] == img["id"]
                                             and a["class_name"].lower() == cls], [cls])
                req += r["required"]; found += r["found"]; ious += r["ious"]
            rows.append({"class": cls, "half": half, "required": req, "found": found,
                         "found %": found / req if req else None,
                         "mean IoU": float(np.mean(ious)) if ious else None})
    return rows


def score_labels(coco, img_id: int, anns_user: list[dict], classes: list[str],
                 min_area: int = MIN_EFFORT_AREA, iou_thr: float = 0.5) -> dict:
    """Compare a user's labels on one image with COCO ground truth.

    GT = target-class objects >= min_area. Target-class objects below that size
    are 'optional': labelling them is neither required nor counted as wrong.
    Matching: same class, mask IoU >= 0.5, best first. Boxes are compared as
    filled rectangles (so a box around a person scores lower than an outline,
    as it should)."""
    info = coco.loadImgs(img_id)[0]
    h, w = info["height"], info["width"]
    cat_ids = {c["name"]: c["id"] for c in coco.loadCats(coco.getCatIds(catNms=classes))}
    anns = coco.loadAnns(coco.getAnnIds(imgIds=img_id, catIds=list(cat_ids.values())))
    req = [a for a in anns if not a["iscrowd"] and a["area"] >= min_area]
    opt = [a for a in anns if a not in req]
    gtm = {a["id"]: gt_mask(coco, a) for a in anns}
    user = [u for u in anns_user if u["class_name"].lower() in cat_ids]
    other = [u for u in anns_user if u["class_name"].lower() not in cat_ids]

    def umask(u):
        return polygon_to_mask(u["points"], h, w) if u["kind"] == "polygon" else box_to_mask(u["points"], h, w)

    pairs = []
    for u in user:
        um, uc = umask(u), cat_ids[u["class_name"].lower()]
        for a in req + opt:
            if a["category_id"] == uc:
                v = mask_iou(um, gtm[a["id"]])
                if v >= iou_thr:
                    pairs.append((v, u["id"], a["id"]))
    pairs.sort(reverse=True)
    used_u, used_g, matched = set(), set(), []
    for v, uid, gid in pairs:
        if uid in used_u or gid in used_g:
            continue
        used_u.add(uid); used_g.add(gid)
        matched.append((v, uid, gid))
    req_ids = {a["id"] for a in req}
    m_req = [m for m in matched if m[2] in req_ids]
    wrong = [u for u in user if u["id"] not in used_u]
    return {"required": len(req), "found": len(m_req), "extra_optional": len(matched) - len(m_req),
            "wrong": len(wrong) + len(other), "labels": len(anns_user),
            "mean_iou": float(np.mean([m[0] for m in m_req])) if m_req else None,
            "ious": [m[0] for m in m_req]}
