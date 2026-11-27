"""Storage: one SQLite file for classes, images and annotations, plus the image
files themselves on disk.

All geometry is stored in the image's own pixel coordinates (floats, origin at
the top-left corner of the top-left pixel), exactly as COCO expects. The browser
converts screen positions to these coordinates; nothing here knows about zoom.

A box is stored as two corner points [[x1, y1], [x2, y2]] with x1 < x2, y1 < y2.
A polygon is stored as its vertices [[x, y], ...], at least three, not closed.
"""

from __future__ import annotations

import io
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageOps

# A spread of easily told-apart colours, assigned to classes in order.
PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0",
           "#f032e6", "#bcf60c", "#fabebe", "#008080", "#e6beff", "#9a6324",
           "#fffac8", "#800000", "#aaffc3", "#808000", "#ffd8b1", "#000075"]

KINDS = ("box", "polygon")
SOURCES = ("manual", "sam", "yolo", "yolo+sam")

SCHEMA = """
CREATE TABLE IF NOT EXISTS classes (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    colour  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
    id        INTEGER PRIMARY KEY,
    file      TEXT NOT NULL,          -- stored file name under images/
    name      TEXT NOT NULL,          -- original upload name, for display and export
    width     INTEGER NOT NULL,
    height    INTEGER NOT NULL,
    added_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS annotations (
    id         INTEGER PRIMARY KEY,
    image_id   INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    class_id   INTEGER NOT NULL REFERENCES classes(id),
    kind       TEXT NOT NULL,         -- 'box' or 'polygon'
    points     TEXT NOT NULL,         -- JSON [[x, y], ...] in image pixels
    source     TEXT NOT NULL,         -- who drew it: 'manual', 'sam', 'yolo', 'yolo+sam'
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ann_image ON annotations(image_id);
"""


class StoreError(ValueError):
    """A request the store refuses: bad geometry, unknown id, duplicate name."""


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.images_dir = self.root / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "annotator.db"
        with self._db() as db:
            db.executescript(SCHEMA)

    # A fresh connection per call: FastAPI runs plain endpoints on a thread
    # pool, and sqlite3 connections must not be shared between threads.
    # Commits on success, rolls back on error, and always closes.
    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------ classes

    def classes(self) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM classes ORDER BY id")]

    def add_class(self, name: str) -> dict:
        name = name.strip()
        if not name:
            raise StoreError("class name is empty")
        with self._db() as db:
            n = db.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
            try:
                cur = db.execute("INSERT INTO classes (name, colour) VALUES (?, ?)",
                                 (name, PALETTE[n % len(PALETTE)]))
            except sqlite3.IntegrityError:
                raise StoreError(f"class '{name}' already exists") from None
            return dict(db.execute("SELECT * FROM classes WHERE id = ?",
                                   (cur.lastrowid,)).fetchone())

    def rename_class(self, class_id: int, name: str) -> dict:
        """Fix a class name without touching its labels: annotations point at
        the class id, so every label follows the new name."""
        name = name.strip()
        if not name:
            raise StoreError("class name is empty")
        self._check_class(class_id)
        with self._db() as db:
            try:
                db.execute("UPDATE classes SET name = ? WHERE id = ?", (name, class_id))
            except sqlite3.IntegrityError:
                raise StoreError(f"class '{name}' already exists") from None
            return dict(db.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone())

    def delete_class(self, class_id: int) -> None:
        with self._db() as db:
            used = db.execute("SELECT COUNT(*) FROM annotations WHERE class_id = ?",
                              (class_id,)).fetchone()[0]
            if used:
                raise StoreError(f"class is used by {used} annotation(s); delete or "
                                 "re-class them first")
            db.execute("DELETE FROM classes WHERE id = ?", (class_id,))

    # ------------------------------------------------------------ images

    def add_image(self, data: bytes, name: str) -> dict:
        """Store an uploaded image. EXIF rotation is applied once, here, so the
        pixels on disk, the browser's view and the stored coordinates all agree:
        otherwise a phone photo can display rotated while its labels are not."""
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception:
            raise StoreError(f"'{name}' is not an image this server can read") from None
        fmt = img.format  # read before exif_transpose, which returns a new image without it
        img = ImageOps.exif_transpose(img)
        ext = ".jpg" if fmt == "JPEG" else ".png"
        if ext == ".jpg" and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        with self._db() as db:
            cur = db.execute(
                "INSERT INTO images (file, name, width, height, added_at) VALUES (?, ?, ?, ?, ?)",
                ("", name, img.width, img.height, time.time()))
            image_id = cur.lastrowid
            file = f"{image_id}{ext}"
            if ext == ".jpg":
                img.save(self.images_dir / file, quality=95)
            else:
                img.save(self.images_dir / file)
            db.execute("UPDATE images SET file = ? WHERE id = ?", (file, image_id))
        return self.image(image_id)

    def images(self) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute(
                "SELECT i.*, (SELECT COUNT(*) FROM annotations a WHERE a.image_id = i.id) "
                "AS n_annotations FROM images i ORDER BY i.id")]

    def image(self, image_id: int) -> dict:
        with self._db() as db:
            r = db.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        if r is None:
            raise StoreError(f"no image {image_id}")
        return dict(r)

    def image_path(self, image_id: int) -> Path:
        return self.images_dir / self.image(image_id)["file"]

    def delete_image(self, image_id: int) -> None:
        path = self.image_path(image_id)
        with self._db() as db:
            db.execute("DELETE FROM images WHERE id = ?", (image_id,))
        path.unlink(missing_ok=True)

    # ------------------------------------------------------------ annotations

    def annotations(self, image_id: int | None = None) -> list[dict]:
        sql, args = "SELECT * FROM annotations", ()
        if image_id is not None:
            sql, args = sql + " WHERE image_id = ?", (image_id,)
        with self._db() as db:
            rows = db.execute(sql + " ORDER BY id", args).fetchall()
        return [_ann(r) for r in rows]

    def add_annotation(self, image_id: int, class_id: int, kind: str,
                       points: list, source: str = "manual") -> dict:
        img = self.image(image_id)
        self._check_class(class_id)
        if source not in SOURCES:
            raise StoreError(f"unknown source '{source}'")
        pts = clean_points(kind, points, img["width"], img["height"])
        now = time.time()
        with self._db() as db:
            cur = db.execute(
                "INSERT INTO annotations (image_id, class_id, kind, points, source, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (image_id, class_id, kind, json.dumps(pts), source, now, now))
            return _ann(db.execute("SELECT * FROM annotations WHERE id = ?",
                                   (cur.lastrowid,)).fetchone())

    def update_annotation(self, ann_id: int, class_id: int | None = None,
                          points: list | None = None) -> dict:
        ann = self.annotation(ann_id)
        img = self.image(ann["image_id"])
        fields, args = [], []
        if class_id is not None:
            self._check_class(class_id)
            fields.append("class_id = ?"); args.append(class_id)
        if points is not None:
            pts = clean_points(ann["kind"], points, img["width"], img["height"])
            fields.append("points = ?"); args.append(json.dumps(pts))
        if not fields:
            return ann
        fields.append("updated_at = ?"); args.append(time.time())
        with self._db() as db:
            db.execute(f"UPDATE annotations SET {', '.join(fields)} WHERE id = ?",
                       (*args, ann_id))
        return self.annotation(ann_id)

    def annotation(self, ann_id: int) -> dict:
        with self._db() as db:
            r = db.execute("SELECT * FROM annotations WHERE id = ?", (ann_id,)).fetchone()
        if r is None:
            raise StoreError(f"no annotation {ann_id}")
        return _ann(r)

    def delete_annotation(self, ann_id: int) -> dict:
        ann = self.annotation(ann_id)
        with self._db() as db:
            db.execute("DELETE FROM annotations WHERE id = ?", (ann_id,))
        return ann

    def _check_class(self, class_id: int) -> None:
        with self._db() as db:
            if db.execute("SELECT 1 FROM classes WHERE id = ?", (class_id,)).fetchone() is None:
                raise StoreError(f"no class {class_id}")


def _ann(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["points"] = json.loads(d["points"])
    return d


def clean_points(kind: str, points: list, width: int, height: int) -> list[list[float]]:
    """Validate geometry and clamp it to the image. Drawing a few pixels past the
    edge is normal when tracing an object that touches the border; storing a
    vertex outside the image is not, because COCO and YOLO would then disagree
    about where it is."""
    if kind not in KINDS:
        raise StoreError(f"unknown kind '{kind}'")
    try:
        pts = [[float(x), float(y)] for x, y in points]
    except (TypeError, ValueError):
        raise StoreError("points must be a list of [x, y] pairs") from None
    if not all(math.isfinite(v) for p in pts for v in p):
        raise StoreError("points contain NaN or infinity")
    pts = [[min(max(x, 0.0), float(width)), min(max(y, 0.0), float(height))] for x, y in pts]
    if kind == "box":
        if len(pts) != 2:
            raise StoreError("a box needs exactly two corner points")
        (xa, ya), (xb, yb) = pts
        pts = [[min(xa, xb), min(ya, yb)], [max(xa, xb), max(ya, yb)]]
        if pts[1][0] - pts[0][0] < 1 or pts[1][1] - pts[0][1] < 1:
            raise StoreError("box is smaller than one pixel")
    else:
        if len(pts) < 3:
            raise StoreError("a polygon needs at least three points")
        if polygon_area(pts) < 1:
            raise StoreError("polygon has no area")
    return [[round(x, 2), round(y, 2)] for x, y in pts]


def polygon_area(pts: list[list[float]]) -> float:
    """Shoelace formula, absolute value."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def bbox_of(kind: str, pts: list[list[float]]) -> list[float]:
    """COCO bbox [x, y, w, h] of an annotation."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
