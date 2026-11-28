"""Build app/detector_groups.json: how the class picker groups the fast detector's names.

YOLO11n's weights carry its 80 class names but no grouping. COCO, the dataset it
was trained on, defines one: every category has a "supercategory" (vehicle,
animal, kitchen, ...). This script copies that grouping from COCO's official
annotation file into a small data file, so no label name is ever typed into
Kontur's code.

    .venv311\\Scripts\\python.exe -m app.make_detector_groups eval/data/instances_val2017.json

The file is only used for the picker's optional shortcuts. If it is missing, or a
detector name is not in it, the picker simply lists that name under "Other".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).with_name("detector_groups.json")


def build(annotations: Path) -> dict:
    cats = sorted(json.loads(Path(annotations).read_text(encoding="utf-8"))["categories"], key=lambda c: c["id"])
    groups: dict[str, list[str]] = {}
    for c in cats:                                   # COCO's own order, its own group names
        groups.setdefault(c["supercategory"].capitalize(), []).append(c["name"])
    return {"source": f"COCO 2017 supercategories, from {Path(annotations).name}", "groups": groups}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    data = build(Path(sys.argv[1]))
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"wrote {OUT}: {len(data['groups'])} groups, {sum(map(len, data['groups'].values()))} names")
