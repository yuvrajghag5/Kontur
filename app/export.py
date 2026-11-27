"""Export the open project as one zip, in the formats the user ticks, so the labels
train real models without conversion:

    coco       coco/annotations.json   COCO instances: a box for every label,
                                       polygon segmentation for outlines
    yolo_det   yolo-detect/            Ultralytics detection dataset: images/,
                                       labels/ (class cx cy w h), data.yaml
    yolo_seg   yolo-segment/           Ultralytics segmentation dataset: images/,
                                       labels/ (class x1 y1 x2 y2 ...), data.yaml;
                                       outlines only (a box has no outline)
    voc        voc/Annotations/*.xml   Pascal VOC: one XML per photo, boxes
    masks      masks/*.png             one PNG per photo, pixel = class index
                                       (1..K in classes.txt order), 0 = unlabelled
    csv        labels.csv              one row per label: photo, class, box, outline
    preview    preview/*.jpg           the photos with every label drawn on, for
                                       looking at and sharing, NOT for training

Options: include the photos themselves (images/, and inside each YOLO dataset,
which needs them next to its labels), and export only photos that have labels.

Each photo is exported under one name, "<id>_<original name>", in every format,
so the same photo can be found in all of them. classes.txt is always included.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import zipfile
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

from .store import Store, bbox_of, polygon_area

# key: (label in the UI, one line for the README inside the zip)
FORMATS = {
    "coco":     ("COCO JSON", "coco/annotations.json  COCO instances (boxes; outlines also as segmentation)"),
    "yolo_det": ("YOLO detection", "yolo-detect/           Ultralytics detection dataset (class cx cy w h, normalised)"),
    "yolo_seg": ("YOLO segmentation", "yolo-segment/          Ultralytics segmentation dataset (outlines only; boxes are skipped)"),
    "voc":      ("Pascal VOC XML", "voc/Annotations/       Pascal VOC, one XML per photo (boxes)"),
    "masks":    ("PNG masks", "masks/                 PNG per photo, value = class index (1..K, classes.txt order), 0 = none;\n"
                              "                       only outlines are drawn, boxes have no outline"),
    "csv":      ("CSV table", "labels.csv             one row per label: photo, class, kind, box, outline points"),
    "preview":  ("Photos with labels drawn", "preview/               the photos with every label drawn on (class colour + name);\n"
                                             "                     for looking at and sharing, NOT for training"),
}


class ExportError(ValueError):
    """An export request the server refuses: no format, or an unknown one."""


def export_name(img: dict) -> str:
    """Unique, filesystem-safe export stem for an image."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", img["name"].rsplit(".", 1)[0]).strip("_") or "image"
    return f"{img['id']}_{stem}"


def parse_formats(text: str | None) -> list[str]:
    """'coco,yolo_det' -> ['coco', 'yolo_det']. Nothing given = every format."""
    if not text:
        return list(FORMATS)
    keys = [k.strip() for k in text.split(",") if k.strip()]
    bad = [k for k in keys if k not in FORMATS]
    if bad:
        raise ExportError(f"unknown export format(s): {', '.join(bad)}; known: {', '.join(FORMATS)}")
    if not keys:
        raise ExportError("choose at least one export format")
    return list(dict.fromkeys(keys))


def coco_dict(store: Store, images: list[dict] | None = None) -> dict:
    classes = store.classes()
    images = store.images() if images is None else images
    keep = {i["id"] for i in images}
    out = {
        "info": {"description": "Kontur export", "date_created": time.strftime("%Y-%m-%d %H:%M:%S")},
        "licenses": [],
        "categories": [{"id": c["id"], "name": c["name"], "supercategory": ""} for c in classes],
        "images": [],
        "annotations": [],
    }
    for img in images:
        ext = img["file"].rsplit(".", 1)[1]
        out["images"].append({"id": img["id"], "file_name": f"{export_name(img)}.{ext}",
                              "width": img["width"], "height": img["height"]})
    for a in store.annotations():
        if a["image_id"] not in keep:
            continue
        x, y, w, h = bbox_of(a["kind"], a["points"])
        ann = {"id": a["id"], "image_id": a["image_id"], "category_id": a["class_id"],
               "bbox": [round(v, 2) for v in (x, y, w, h)], "iscrowd": 0,
               "attributes": {"kind": a["kind"], "source": a["source"]}}
        if a["kind"] == "polygon":
            ann["segmentation"] = [[round(v, 2) for p in a["points"] for v in p]]
            ann["area"] = round(polygon_area(a["points"]), 2)
        else:
            # A box carries no outline, so it gets no segmentation; area is the box's.
            ann["segmentation"] = []
            ann["area"] = round(w * h, 2)
        out["annotations"].append(ann)
    return out


def _data_yaml(classes: list[dict]) -> str:
    return ("path: .\ntrain: images\nval: images\n"
            f"nc: {len(classes)}\n"
            "names: [" + ", ".join(json.dumps(c["name"]) for c in classes) + "]\n")


def _voc_xml(img: dict, file_name: str, anns: list[dict], names: dict[int, str]) -> str:
    objs = []
    for a in anns:
        x, y, w, h = bbox_of(a["kind"], a["points"])
        # VOC boxes are whole pixels, 1-based, inclusive
        x1, y1 = max(1, round(x) + 1), max(1, round(y) + 1)
        x2, y2 = min(img["width"], round(x + w)), min(img["height"], round(y + h))
        objs.append(
            "  <object>\n"
            f"    <name>{escape(names[a['class_id']])}</name>\n"
            "    <pose>Unspecified</pose>\n    <truncated>0</truncated>\n    <difficult>0</difficult>\n"
            f"    <bndbox><xmin>{x1}</xmin><ymin>{y1}</ymin><xmax>{max(x1, x2)}</xmax><ymax>{max(y1, y2)}</ymax></bndbox>\n"
            "  </object>\n")
    return ("<annotation>\n"
            "  <folder>images</folder>\n"
            f"  <filename>{escape(file_name)}</filename>\n"
            "  <source><database>Kontur</database></source>\n"
            f"  <size><width>{img['width']}</width><height>{img['height']}</height><depth>3</depth></size>\n"
            "  <segmented>0</segmented>\n"
            + "".join(objs) +
            "</annotation>\n")


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def preview_image(path, anns: list[dict], classes: dict[int, dict]) -> bytes:
    """The photo with its labels drawn on, as the app shows them: each label in
    its class colour, outlines lightly filled, a name tag on every label.
    Sizes scale with the photo, so tags read the same on small and large photos."""
    img = Image.open(path).convert("RGB")
    W, H = img.size
    unit = max(W, H) / 1000                      # 1 unit = 1/1000 of the longer side
    line = max(2, round(3 * unit))
    font = ImageFont.load_default(size=max(11, round(16 * unit)))
    pad = max(2, round(4 * unit))

    # outline fills go on a transparent layer, so they tint the photo instead of hiding it
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fill = ImageDraw.Draw(layer)
    for a in anns:
        if a["kind"] == "polygon":
            fill.polygon([tuple(p) for p in a["points"]], fill=_hex(classes[a["class_id"]]["colour"]) + (70,))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    draw = ImageDraw.Draw(img)
    for a in anns:
        col = _hex(classes[a["class_id"]]["colour"])
        x, y, w, h = bbox_of(a["kind"], a["points"])
        if a["kind"] == "polygon":
            pts = [tuple(p) for p in a["points"]]
            draw.line(pts + [pts[0]], fill=col, width=line, joint="curve")
        else:
            draw.rectangle([x, y, x + w, y + h], outline=col, width=line)
        # the name tag sits above the label, or inside it at the top edge of the photo
        name = classes[a["class_id"]]["name"]
        l, t, r, b = draw.textbbox((0, 0), name, font=font)
        tw, th = r - l + 2 * pad, b - t + 2 * pad
        tx = min(max(0, x), max(0, W - tw))
        ty = y - th if y - th >= 0 else y
        draw.rectangle([tx, ty, tx + tw, ty + th], fill=col)
        lum = 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]
        draw.text((tx + pad - l, ty + pad - t), name, font=font, fill=(20, 20, 20) if lum > 150 else (255, 255, 255))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def build_zip(store: Store, formats: list[str] | None = None, include_images: bool = True,
              only_labelled: bool = False) -> tuple[bytes, dict]:
    """The zip, plus a small summary (photos, labels, what was skipped) for the log."""
    formats = list(FORMATS) if formats is None else formats
    classes = store.classes()
    index = {c["id"]: i for i, c in enumerate(classes)}  # YOLO class index, 0-based
    names = {c["id"]: c["name"] for c in classes}
    by_id = {c["id"]: c for c in classes}
    by_image: dict[int, list[dict]] = {}
    for a in store.annotations():
        by_image.setdefault(a["image_id"], []).append(a)
    images = [i for i in store.images() if not only_labelled or by_image.get(i["id"])]
    n_labels = sum(len(by_image.get(i["id"], [])) for i in images)
    boxes_skipped_seg = 0

    rows = []                                    # for labels.csv
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("classes.txt", "\n".join(c["name"] for c in classes) + "\n")
        if "coco" in formats:
            z.writestr("coco/annotations.json", json.dumps(coco_dict(store, images), indent=1))
        if "yolo_det" in formats:
            z.writestr("yolo-detect/data.yaml", _data_yaml(classes))
        if "yolo_seg" in formats:
            z.writestr("yolo-segment/data.yaml", _data_yaml(classes))

        for img in images:
            stem = export_name(img)
            ext = img["file"].rsplit(".", 1)[1]
            file_name = f"{stem}.{ext}"
            anns = by_image.get(img["id"], [])
            W, H = img["width"], img["height"]

            if include_images:
                data = store.image_path(img["id"]).read_bytes()
                z.writestr(f"images/{file_name}", data)
                # an Ultralytics dataset finds labels by swapping images/ for labels/,
                # so each YOLO dataset carries its own copy of the photos
                if "yolo_det" in formats:
                    z.writestr(f"yolo-detect/images/{file_name}", data)
                if "yolo_seg" in formats:
                    z.writestr(f"yolo-segment/images/{file_name}", data)

            if "yolo_det" in formats:
                det = []
                for a in anns:
                    x, y, w, h = bbox_of(a["kind"], a["points"])
                    det.append(f"{index[a['class_id']]} {(x + w / 2) / W:.6f} {(y + h / 2) / H:.6f} {w / W:.6f} {h / H:.6f}")
                z.writestr(f"yolo-detect/labels/{stem}.txt", "\n".join(det) + ("\n" if det else ""))

            if "yolo_seg" in formats:
                seg = []
                for a in anns:
                    if a["kind"] != "polygon":
                        boxes_skipped_seg += 1
                        continue
                    seg.append(f"{index[a['class_id']]} " + " ".join(f"{px / W:.6f} {py / H:.6f}" for px, py in a["points"]))
                z.writestr(f"yolo-segment/labels/{stem}.txt", "\n".join(seg) + ("\n" if seg else ""))

            if "voc" in formats:
                z.writestr(f"voc/Annotations/{stem}.xml", _voc_xml(img, file_name, anns, names))

            if "masks" in formats:
                mask = Image.new("L", (W, H), 0)
                draw = ImageDraw.Draw(mask)
                for a in anns:
                    if a["kind"] == "polygon":
                        # Later annotations paint over earlier ones where they overlap.
                        draw.polygon([tuple(p) for p in a["points"]], fill=index[a["class_id"]] + 1)
                png = io.BytesIO()
                mask.save(png, format="PNG")
                z.writestr(f"masks/{stem}.png", png.getvalue())

            if "preview" in formats:
                z.writestr(f"preview/{stem}.jpg", preview_image(store.image_path(img["id"]), anns, by_id))

            if "csv" in formats:
                for a in anns:
                    x, y, w, h = bbox_of(a["kind"], a["points"])
                    rows.append([file_name, W, H, names[a["class_id"]], a["kind"], a["source"],
                                 round(x, 2), round(y, 2), round(x + w, 2), round(y + h, 2),
                                 json.dumps(a["points"]) if a["kind"] == "polygon" else ""])

        if "csv" in formats:
            out = io.StringIO()
            wr = csv.writer(out, lineterminator="\n")
            wr.writerow(["image", "width", "height", "class", "kind", "source",
                         "x_min", "y_min", "x_max", "y_max", "outline_points"])
            wr.writerows(rows)
            z.writestr("labels.csv", out.getvalue())

        lines = ["Kontur export", "",
                 f"{len(images)} photos, {n_labels} labels, {len(classes)} classes"
                 + (" (only photos with labels)" if only_labelled else ""), ""]
        lines += [FORMATS[k][1] for k in formats]
        lines.append("classes.txt            class names, one per line (YOLO index = line number - 1)")
        if include_images:
            lines.append("images/                the photos, same names in every format")
        else:
            lines.append("(photos not included: copy them next to the labels yourself)")
        if boxes_skipped_seg:
            lines.append(f"\nNote: {boxes_skipped_seg} box label(s) are not in yolo-segment/: a box has no outline.")
        z.writestr("README.txt", "\n".join(lines) + "\n")

    return buf.getvalue(), {"images": len(images), "annotations": n_labels, "formats": formats,
                            "include_images": include_images, "only_labelled": only_labelled,
                            "boxes_skipped_seg": boxes_skipped_seg}
