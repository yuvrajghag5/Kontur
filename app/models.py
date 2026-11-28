"""The AI models behind the assisted tools.

Phase 3: click-to-segment with MobileSAM (Zhang et al. 2023, "Faster Segment
Anything"), a distilled version of Meta's Segment Anything (Kirillov et al.
2023). It is loaded through the Ultralytics library.

How a click becomes an outline:
1. When an image opens in assisted mode, its embedding is computed once by
   SAM's image encoder (`prepare`). This is the slow step.
2. Each click, or a box, runs only SAM's light prompt decoder on that cached
   embedding (`segment`), so it answers quickly.
3. The mask is turned into one polygon: the outline of its largest piece,
   simplified to about a pixel. The UI then treats it like a hand-drawn polygon.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import cv2
import numpy as np

# All pretrained weights live in one folder, weights/ in the project root.
# They are used as published, never retrained (fingerprints: docs/tech.md).
# Ultralytics downloads a missing file into the exact path it is given, so a
# fresh copy of the project fills this folder on its first start.
WEIGHTS_DIR = Path(__file__).resolve().parent.parent / "weights"
SAM_WEIGHTS = "mobile_sam.pt"       # "sam2.1_t.pt" also works (--sam)
TEXT_ENCODER = "mobileclip_blt.ts"  # YOLOE's text encoder (MobileCLIP), 600 MB


def weight_path(name: str) -> str:
    """A bare file name -> weights/<name>; a path with a folder is kept as given."""
    p = Path(name)
    if p.parent == Path("."):
        WEIGHTS_DIR.mkdir(exist_ok=True)
        p = WEIGHTS_DIR / p
    return str(p)


class SamError(RuntimeError):
    pass


# ONE lock for ALL model work, SAM and both detectors together.
# Measured in the balanced study (25 Nov): opening an image started SAM's encode
# and YOLOE's detection at the same time, in two server threads. Each PyTorch call
# tries to use every CPU core, so they fought: YOLOE took up to 5.3 s and the
# encode up to 10 s, against 0.19 s and 0.83 s measured one at a time
# (notebook 02). Taking turns is faster for both than running side by side.
INFERENCE_LOCK = threading.RLock()


class _Turn:
    """`with _Turn() as t:` waits for the models to be free; t.wait_ms is how long
    this request queued behind other model work (logged, so waiting is visible)."""

    def __enter__(self):
        t0 = time.perf_counter()
        INFERENCE_LOCK.acquire()
        self.wait_ms = round((time.perf_counter() - t0) * 1000, 1)
        return self

    def __exit__(self, *exc):
        INFERENCE_LOCK.release()


class ClickSegmenter:
    """One SAM predictor, holding the embedding of one image at a time."""

    def __init__(self, weights: str = SAM_WEIGHTS):
        self.weights = Path(weights).name      # the name shown in the UI and the log
        self.path = weight_path(weights)       # where the file is loaded from
        self._predictor = None
        self._image_key: tuple | None = None    # (path, mtime) of the image now embedded
        self.last_encode_ms: float | None = None
        self.state = "not loaded"               # not loaded / loading / ready / error: ...
        self.load_ms: float | None = None

    def warm_up(self) -> dict:
        """Load the model and run the encoder once on a tiny blank image.

        Called in the background when the server starts. Measured on 17 Nov: the
        first AI request took 61 s because it paid for the weight download, model
        build, torch's first-run setup and the real encode all at once, while the
        user was waiting. Warming up at start moves all but the real encode out of
        the user's way."""
        with _Turn():
            self.state = "loading"
            t0 = time.perf_counter()
            try:
                self._load().set_image(np.zeros((64, 64, 3), dtype=np.uint8))
                self._image_key = ("warm-up",)
            except Exception as e:
                self.state = f"error: {type(e).__name__}: {e}"
                raise
            self.load_ms = round((time.perf_counter() - t0) * 1000, 1)
            self.state = "ready"
            return {"load_ms": self.load_ms, "device": self.device}

    def _load(self):
        if self._predictor is None:
            # Imported here, not at module level: the manual tool must start and
            # work even if the model stack is missing or broken.
            if "sam2" in self.weights:
                from ultralytics.models.sam import SAM2Predictor as Predictor
            else:
                from ultralytics.models.sam import Predictor
            # conf=0: Ultralytics drops masks scoring at or below `conf`. We always
            # want SAM's answer, with its own score shown, not silence.
            self._predictor = Predictor(overrides=dict(
                model=self.path, task="segment", mode="predict", imgsz=1024,
                conf=0.0, save=False, verbose=False))
        return self._predictor

    @property
    def device(self) -> str:
        p = self._predictor
        return str(getattr(p, "device", "not loaded")) if p is not None else "not loaded"

    def prepare(self, image_path: Path) -> dict:
        """Embed an image (once). Returns timing so the UI and log can show it."""
        with _Turn() as turn:
            return {**self._prepare(image_path), "wait_ms": turn.wait_ms}

    def _prepare(self, image_path: Path) -> dict:
        key = (str(image_path), image_path.stat().st_mtime)
        if key == self._image_key:
            return {"cached": True, "encode_ms": 0.0}
        p = self._load()
        t0 = time.perf_counter()
        p.set_image(str(image_path))
        self._image_key = key
        self.last_encode_ms = round((time.perf_counter() - t0) * 1000, 1)
        self.state = "ready"
        return {"cached": False, "encode_ms": self.last_encode_ms}

    def segment(self, image_path: Path, points: list[list[float]] | None = None,
                labels: list[int] | None = None, box: list[list[float]] | None = None) -> dict:
        """Outline one object from clicks (1 = on the object, 0 = not on it)
        and/or a box [[x1, y1], [x2, y2]], all in image pixels."""
        if not points and not box:
            raise SamError("give at least one click or a box")
        if points and (labels is None or len(labels) != len(points)):
            raise SamError("every click needs a label (1 = object, 0 = background)")
        with _Turn() as turn:
            prep = self._prepare(image_path)
            p = self._predictor
            kwargs = {}
            if points:
                # Shape (1 object, k clicks, 2): all clicks describe the SAME object.
                kwargs["points"] = [[[float(x), float(y)] for x, y in points]]
                kwargs["labels"] = [[int(v) for v in labels]]
            if box:
                (x1, y1), (x2, y2) = box
                kwargs["bboxes"] = [[min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]]
            # A single click is ambiguous (the shirt, or the whole person?): ask
            # for SAM's three candidate masks and keep the best-scored, as the SAM
            # paper recommends. With more prompts, one mask is better.
            multi = bool(points) and len(points) == 1 and not box
            t0 = time.perf_counter()
            results = p(multimask_output=multi, **kwargs)
            decode_ms = round((time.perf_counter() - t0) * 1000, 1)

        r = results[0]
        if r.masks is None or len(r.masks.data) == 0:
            return {"polygon": None, "score": None, "area": 0, "decode_ms": decode_ms, **prep,
                    "wait_ms": turn.wait_ms}
        masks = r.masks.data.cpu().numpy().astype(bool)          # (n, H, W), original image size
        scores = r.boxes.data[:, 4].cpu().numpy()                 # SAM's own quality estimate
        best = int(np.argmax(scores))
        mask = masks[best]
        polygon = mask_to_polygon(mask)
        return {"polygon": polygon, "score": round(float(scores[best]), 3),
                "area": int(mask.sum()), "decode_ms": decode_ms, **prep, "wait_ms": turn.wait_ms}


class DetectError(RuntimeError):
    pass


# Phase 4: object suggestions. Two detectors behind one interface, chosen in
# the UI, so the evaluation can compare them on the same images.
DETECTORS = {
    "yolo11n": {
        "weights": "yolo11n.pt",
        "label": "YOLO11n · 80 COCO classes",
        "open_vocab": False,
        "about": "Fast closed-set detector trained on COCO. Suggests only the 80 COCO "
                 "classes, mapped to your class names where they match.",
    },
    "yoloe": {
        "weights": "yoloe-11s-seg.pt",
        "label": "YOLOE-11s · your class names",
        "open_vocab": True,
        "about": "Open-vocabulary detector: looks for whatever class names you have, "
                 "with no retraining. Broader training data, slower, more false alarms "
                 "on vague names.",
    },
}

# No label names live in this code. A closed-set detector (YOLO11n) brings its
# own list of class names inside its weights file; Kontur reads it from there at
# run time (Detector.vocabulary). The user's labels are whatever they type, saved
# per project.

def norm_label(name: str) -> str:
    """Compare labels loosely: case, extra spaces, "_" and "-" do not matter."""
    return " ".join(name.replace("_", " ").replace("-", " ").lower().split())


def match_name(name: str, vocabulary: list[str]) -> str | None:
    """The detector's own name for a user's label, if it has one: the same word,
    ignoring case and spacing, or its singular (a trailing "s" or "es" removed).
    Nothing fuzzier, so a match is never a surprise; the UI shows every match."""
    own = {norm_label(v): v for v in vocabulary}
    n = norm_label(name)
    for cand in (n, n[:-1] if n.endswith("s") else None, n[:-2] if n.endswith("es") else None):
        if cand and cand in own:
            return own[cand]
    return None


class Detector:
    """Loads each detector once, on first use or at start-up, and runs it."""

    def __init__(self, weights: dict[str, str] | None = None):
        self.cfg = {k: dict(v) for k, v in DETECTORS.items()}
        self._closed = next(k for k, c in self.cfg.items() if not c["open_vocab"])   # YOLO11n
        for k, w in (weights or {}).items():
            self.cfg[k]["weights"] = w
        self._models: dict[str, object] = {}
        self._yoloe_names: tuple[str, ...] | None = None   # classes YOLOE is currently set to
        self.state = {k: "not loaded" for k in self.cfg}
        self.load_ms: dict[str, float | None] = {k: None for k in self.cfg}

    def info(self) -> list[dict]:
        return [{"key": k, "label": c["label"], "weights": c["weights"], "open_vocab": c["open_vocab"],
                 "about": c["about"], "state": self.state[k], "load_ms": self.load_ms[k]}
                for k, c in self.cfg.items()]

    def _model(self, key: str):
        if key not in self.cfg:
            raise DetectError(f"unknown detector '{key}'")
        if key not in self._models:
            self.state[key] = "loading"
            t0 = time.perf_counter()
            try:
                path = weight_path(self.cfg[key]["weights"])
                if self.cfg[key]["open_vocab"]:
                    from ultralytics import YOLOE
                    from ultralytics.nn.text_model import MobileCLIPTS
                    m = YOLOE(path)
                    # Ultralytics would look for the text encoder by bare name in
                    # the folder the server runs from, and load all 600 MB again on
                    # every class change. Give it ours, from weights/, loaded once.
                    device = next(m.model.parameters()).device
                    m.model.clip_model = MobileCLIPTS(device, weight=weight_path(TEXT_ENCODER))
                    self._models[key] = m
                else:
                    from ultralytics import YOLO
                    self._models[key] = YOLO(path)
            except Exception as e:
                self.state[key] = f"error: {type(e).__name__}: {e}"
                raise
            self.load_ms[key] = round((time.perf_counter() - t0) * 1000, 1)
            self.state[key] = "ready"
        return self._models[key]

    def vocabulary(self) -> list[str]:
        """The class names the closed-set detector was trained on, read from its
        weights file (YOLO11n: COCO's 80). Empty if the model cannot load."""
        try:
            with _Turn():
                return list(self._model(self._closed).names.values())
        except Exception:
            return []

    def coverage(self, class_names: list[str]) -> list[dict]:
        """What each detector can do for each of the user's labels, for the badges."""
        vocab = self.vocabulary()
        return [{"name": n, "yolo11n": match_name(n, vocab), "yoloe": True} for n in class_names]

    def decoys(self, user_names: list[str]) -> list[str]:
        """The detector vocabulary minus the user's labels: extra YOLOE prompts, so an
        object outside the user's labels gets a name of its own (and is dropped)."""
        vocab = self.vocabulary()
        taken = {norm_label(n) for n in user_names} | {norm_label(m) for n in user_names if (m := match_name(n, vocab))}
        return [v for v in vocab if norm_label(v) not in taken]

    def warm_up(self, key: str, class_names: list[str]) -> dict:
        """Load a detector and run it once on a blank image, so the first real
        suggestion does not pay for downloads and torch's first-run setup."""
        t0 = time.perf_counter()
        self.detect(key, np.zeros((64, 64, 3), dtype=np.uint8), class_names or ["object"], conf=0.5)
        return {"load_ms": self.load_ms[key], "warm_ms": round((time.perf_counter() - t0) * 1000, 1)}

    def detect(self, key: str, image, class_names: list[str], conf: float = 0.35,
               max_det: int = 60, use_decoys: bool = True) -> dict:
        """Boxes for an image (a path, or an array for the warm-up), each with
        one of `class_names`. Returns the suggestions, the time taken, which of
        the user's classes this detector cannot suggest at all, and the objects
        it saw that are outside the user's classes ("ignored")."""
        with _Turn() as turn:
            model = self._model(key)
            # index -> (user class name or None, detector's own name)
            if self.cfg[key]["open_vocab"]:
                names = [n for n in dict.fromkeys(n.strip() for n in class_names) if n]
                if not names:
                    raise DetectError("add at least one class first")
                # Decoys: the detector-vocabulary names the user did NOT choose.
                # Without them YOLOE must squeeze every object into one of the
                # user's few words, so an animal can come back named as a piece
                # of furniture. With its own name on offer, it is named correctly
                # and dropped (listed as "ignored").
                decoys = self.decoys(names) if use_decoys else []
                prompts = names + decoys
                if tuple(prompts) != self._yoloe_names:
                    # Turning names into text embeddings is the slow part of a
                    # class change; done only when the prompt list actually changes.
                    # cache_clip_model=True: use the encoder set in _model (weights/)
                    emb = model.model.get_text_pe(prompts, cache_clip_model=True)
                    model.set_classes(prompts, emb)
                    self._yoloe_names = tuple(prompts)
                label = {i: (n if i < len(names) else None, n) for i, n in enumerate(prompts)}
                unsupported: list[str] = []
                # one box per object: with decoys, a dog must not ALSO come back as a chair
                agnostic = bool(decoys)
            else:
                label = {i: (None, n) for i, n in model.names.items()}
                own_ids = {v: k for k, v in model.names.items()}
                taken, unsupported = set(), []
                for n in class_names:
                    target = match_name(n, list(own_ids))
                    if target not in own_ids:
                        unsupported.append(n)
                        continue
                    i = own_ids[target]
                    if i not in taken:
                        label[i] = (n, target)
                        taken.add(i)
                agnostic = False
            src = str(image) if isinstance(image, Path) else image
            t0 = time.perf_counter()
            r = model.predict(src, conf=conf, max_det=max_det, verbose=False, imgsz=640,
                              agnostic_nms=agnostic)[0]
            ms = round((time.perf_counter() - t0) * 1000, 1)

        out, ignored = [], []
        boxes = r.boxes
        for xyxy, score, cls in zip(boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy(),
                                    boxes.cls.cpu().numpy().astype(int)):
            user_name, own_name = label.get(int(cls), (None, str(cls)))
            x1, y1, x2, y2 = (round(float(v), 1) for v in xyxy)
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            if user_name is None:       # an object outside the user's classes: report, don't suggest
                ignored.append({"class_name": own_name, "score": round(float(score), 3)})
                continue
            s = {"box": [[x1, y1], [x2, y2]], "score": round(float(score), 3), "class_name": user_name}
            if own_name.lower() != user_name.strip().lower():
                s["matched_as"] = own_name          # the detector's own spelling of the user's label
            out.append(s)
        out.sort(key=lambda s: -s["score"])
        return {"suggestions": out, "ms": ms, "unsupported": unsupported, "ignored": ignored,
                "wait_ms": turn.wait_ms}


def mask_to_polygon(mask: np.ndarray, tolerance: float = 1.0) -> list[list[float]] | None:
    """Outline of the mask's largest connected piece, as a polygon in image pixels.

    - Only the largest piece is kept: a click means one object, and SAM's stray
      specks would otherwise become separate polygons.
    - Holes are ignored, as in COCO's polygon format.
    - The outline is simplified (Douglas-Peucker) to about `tolerance` pixels,
      which keeps the polygon editable by hand.
    - Contour points are pixel indices; +0.5 moves them to pixel centres in the
      continuous image coordinates used everywhere else.
    """
    m = mask.astype(np.uint8)
    found = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = found[-2]                      # OpenCV 3 returns 3 values, 4+ returns 2
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 4:
        return None
    eps = max(tolerance, 0.002 * cv2.arcLength(c, True))
    c = cv2.approxPolyDP(c, eps, True)
    if len(c) < 3:
        return None
    return [[round(float(x) + 0.5, 2), round(float(y) + 0.5, 2)] for x, y in c.reshape(-1, 2)]
