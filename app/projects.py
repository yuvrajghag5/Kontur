"""Projects: one folder per project, listed in one small registry file.

    <data>/projects.json            the registry: names, folders, which one is open
    <data>/projects/<id>/           a project: annotator.db, images/, logs/events.jsonl
    <data>/trash/<id>-<time>/       a deleted project, moved here, never erased

Each project folder has exactly the layout the app used before projects existed,
so `Store` and `EventLog` work on it unchanged. A data folder from before
projects (annotator.db directly in <data>) is registered as a project whose
folder is "." and left where it is. The effort-study folders
(eval/studies/data_study, data_study2) have the same layout, so `--data` opens
them like any data folder.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

from .store import Store, StoreError

LEGACY = "."             # a pre-projects data folder: the project IS the data folder
NAME_MAX = 60


class Projects:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.file = self.root / "projects.json"
        self._lock = threading.Lock()
        if self.file.exists():
            self.reg = json.loads(self.file.read_text(encoding="utf-8"))
        else:
            self.reg = {"projects": [], "open": None}
            if (self.root / "annotator.db").exists():
                self.reg["projects"].append({"id": 1, "name": "My first project", "folder": LEGACY,
                                             "created_at": time.time(), "last_opened": None})
            self._save()

    def _save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.reg, indent=1), encoding="utf-8")
        tmp.replace(self.file)                     # never leave a half-written registry

    # ------------------------------------------------------------ lookups

    def get(self, pid: int) -> dict:
        for p in self.reg["projects"]:
            if p["id"] == pid:
                return p
        raise StoreError(f"no project {pid}")

    def folder(self, pid: int) -> Path:
        f = self.get(pid)["folder"]
        return self.root if f == LEGACY else self.root / f

    @property
    def open_id(self) -> int | None:
        pid = self.reg.get("open")
        return pid if any(p["id"] == pid for p in self.reg["projects"]) else None

    def summary(self, pid: int) -> dict:
        """What the home page shows on a project's card."""
        p = self.get(pid)
        store = Store(self.folder(pid))
        images = store.images()
        classes = store.classes()
        return {**p,
                "n_images": len(images),
                "n_labelled": sum(1 for i in images if i["n_annotations"]),
                "n_annotations": sum(i["n_annotations"] for i in images),
                "classes": [c["name"] for c in classes],
                "colours": [c["colour"] for c in classes],
                "thumbs": [i["id"] for i in images[:4]],     # a contact-sheet mosaic on the card
                "legacy": p["folder"] == LEGACY}

    def all(self) -> list[dict]:
        # most recently used first; never-opened projects by creation time
        ps = sorted(self.reg["projects"], key=lambda p: (p["last_opened"] or p["created_at"]), reverse=True)
        return [self.summary(p["id"]) for p in ps]

    # ------------------------------------------------------------ changes

    def _clean_name(self, name: str, skip: int | None = None) -> str:
        name = " ".join((name or "").split())
        if not name:
            raise StoreError("project name is empty")
        if len(name) > NAME_MAX:
            raise StoreError(f"project name is longer than {NAME_MAX} characters")
        if any(p["name"].lower() == name.lower() and p["id"] != skip for p in self.reg["projects"]):
            raise StoreError(f"a project called '{name}' already exists")
        return name

    def create(self, name: str) -> dict:
        with self._lock:
            name = self._clean_name(name)
            pid = self._next_id()
            folder = f"projects/{pid}"
            # ids are never reused (see _next_id), so a leftover folder can only be a stray: refuse, don't mix
            if (self.root / folder).exists():
                raise StoreError(f"folder {folder} already exists; move it away first")
            Store(self.root / folder)                  # creates annotator.db and images/
            self.reg["projects"].append({"id": pid, "name": name, "folder": folder,
                                         "created_at": time.time(), "last_opened": None})
            self.reg["next_id"] = pid + 1
            self._save()
        return self.summary(pid)

    def _next_id(self) -> int:
        """A project number that was never used before, even by a deleted project.
        Taking max(ids) + 1 would hand a deleted project's number to the next new
        one (seen on 25 Nov: delete 1 and 2, create -> 1 again), so an old link
        such as #/p/1 would quietly open a different project. A counter in the
        registry only goes up; it also looks at trash/ and projects/, for
        registries written before the counter existed."""
        used = [p["id"] for p in self.reg["projects"]]
        for sub in ("trash", "projects"):
            d = self.root / sub
            if d.is_dir():
                used += [int(x.name.split("-")[0]) for x in d.iterdir() if x.name.split("-")[0].isdigit()]
        return max([self.reg.get("next_id", 1)] + [u + 1 for u in used])

    def rename(self, pid: int, name: str) -> dict:
        with self._lock:
            p = self.get(pid)
            p["name"] = self._clean_name(name, skip=pid)
            self._save()
        return self.summary(pid)

    # what a pre-projects data folder holds for its one project
    LEGACY_ITEMS = ("annotator.db", "annotator.db-wal", "annotator.db-shm", "images", "logs/events.jsonl")

    def delete(self, pid: int) -> str:
        """Move the project to trash/ and forget it. Returns where it went.
        Nothing is erased: the folder can be moved back by hand."""
        with self._lock:
            p = self.get(pid)
            dest = self.root / "trash" / f"{pid}-{time.strftime('%Y%m%d-%H%M%S')}"
            dest.mkdir(parents=True, exist_ok=True)
            if p["folder"] == LEGACY:
                # the project IS the data folder: move only its own files, keep
                # projects.json, projects/ and trash/ where they are
                for item in self.LEGACY_ITEMS:
                    src = self.root / item
                    if src.exists():
                        (dest / item).parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(src), str(dest / item))
            else:
                shutil.move(str(self.root / p["folder"]), str(dest / "project"))
            self.reg["projects"] = [x for x in self.reg["projects"] if x["id"] != pid]
            if self.reg.get("open") == pid:
                self.reg["open"] = None
            self._save()
        return str(dest.relative_to(self.root))

    def mark_open(self, pid: int) -> None:
        with self._lock:
            self.get(pid)["last_opened"] = time.time()
            self.reg["open"] = pid
            self._save()
