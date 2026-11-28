"""The annotation server: a FastAPI app serving the browser UI and a small JSON API.

    .venv311\\Scripts\\python.exe -m app.server            then open http://127.0.0.1:8000
    .venv311\\Scripts\\python.exe -m app.server --data D:\\scratch --port 8001   (tests)

--data is the folder that holds the projects (see projects.py); one project is
open at a time, and every route below except /api/projects* works on it.

The server is the single source of truth: every annotation the browser draws is
saved here immediately. The browser only converts screen positions to image
pixels and shows what the server holds.
"""

from __future__ import annotations

import argparse
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import export
from .events import EventLog
from .models import SAM_WEIGHTS, ClickSegmenter, DetectError, Detector, SamError
from .projects import Projects
from .store import Store, StoreError

HERE = Path(__file__).parent
DEFAULT_DATA = HERE.parent / "data"

# A new project starts with NO classes: the user picks them first (the class
# picker opens by itself). Four starter classes used to be seeded here; they made
# the AI suggest objects the user never asked for. No label names live in the code.

app = FastAPI(title="Kontur")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

class _NoProject:
    """Stands in for the store while no project is open (the home page): any
    project route then answers 409 instead of touching a folder."""
    def __getattr__(self, name):
        raise HTTPException(409, "no project is open; choose one on the home page")


projects: Projects
store: Store | _NoProject
log: EventLog            # the open project's log; server.jsonl while none is open
server_log: EventLog     # model loading and project switches, whatever is open
segmenter: ClickSegmenter
detector: Detector
_switch = threading.Lock()


def configure(data_dir: Path, sam_weights: str = SAM_WEIGHTS) -> None:
    """Point the app at a data folder holding projects (see projects.py). The
    project opened last is opened again, so a restart lands where the user was."""
    global projects, server_log, segmenter, detector
    projects = Projects(data_dir)
    server_log = EventLog(Path(data_dir) / "logs" / "server.jsonl")
    segmenter = ClickSegmenter(sam_weights)
    detector = Detector()
    close_project()
    if projects.open_id is not None:
        open_project(projects.open_id)


def open_project(pid: int) -> None:
    """Swap the store and the log to one project's folder. The models stay
    loaded: SAM's cached embedding is keyed by the image's file path, so images
    of different projects can never be confused."""
    global store, log
    with _switch:
        folder = projects.folder(pid)
        store = Store(folder)
        log = EventLog(folder / "logs" / "events.jsonl")
        projects.mark_open(pid)
    log.server_event("project_open", project=pid)


def close_project() -> None:
    global store, log
    with _switch:
        store = _NoProject()
        log = server_log


def warm_up_models() -> None:
    """Load the models in the background as soon as the server starts, so the
    first AI click or suggestion does not pay for downloading and loading
    (61 s for the first click on 17 Nov). SAM first: it is used most."""
    try:
        r = segmenter.warm_up()
        log.server_event("ai_load", model=segmenter.weights, **r)
        print(f"  AI outline ready: {segmenter.weights} on {r['device']}, loaded in {r['load_ms'] / 1000:.1f} s")
    except Exception as e:
        log.server_event("ai_error", stage="load", model=segmenter.weights, error=f"{type(e).__name__}: {e}")
        print(f"  AI outline NOT available ({type(e).__name__}: {e}). Manual tools still work.")
    try:
        names = [c["name"] for c in store.classes()] or ["object"]   # a new project has no classes yet
    except HTTPException:
        names = ["object"]                                            # no project open: the home page
    for key in detector.cfg:
        try:
            r = detector.warm_up(key, names)
            log.server_event("ai_load", model=detector.cfg[key]["weights"], **r)
            print(f"  Suggestions ready: {detector.cfg[key]['label']}, loaded in {r['load_ms'] / 1000:.1f} s")
        except Exception as e:
            log.server_event("ai_error", stage="load", model=detector.cfg[key]["weights"],
                             error=f"{type(e).__name__}: {e}")
            print(f"  Suggestions with {detector.cfg[key]['label']} NOT available ({type(e).__name__}: {e}).")


def refuse(e: StoreError):
    raise HTTPException(400, str(e))


@app.middleware("http")
async def project_guard(request: Request, call_next):
    """The browser names the project it is showing (header X-Project) on every
    call. If another project is open by then (a second tab, or a slow AI answer
    arriving after the user switched), refuse, so nothing is ever saved into the
    wrong project. Image ids restart at 1 in every project, so they alone can't tell."""
    want = request.headers.get("x-project")
    if want and not request.url.path.startswith("/api/projects") and want != str(projects.open_id):
        return JSONResponse({"detail": "another project is open now; go back to Projects and reopen this one"},
                            status_code=409)
    return await call_next(request)


# ---------------------------------------------------------------- pages


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "static" / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- projects (home page)


class ProjectName(BaseModel):
    name: str


@app.get("/api/projects")
def list_projects():
    return {"projects": projects.all(), "open": projects.open_id}


@app.post("/api/projects")
def create_project(q: ProjectName):
    try:
        p = projects.create(q.name)
    except StoreError as e:
        refuse(e)
    server_log.server_event("project_create", project=p["id"], name=p["name"])
    return p


@app.put("/api/projects/{pid}")
def rename_project(pid: int, q: ProjectName):
    try:
        return projects.rename(pid, q.name)
    except StoreError as e:
        refuse(e)


@app.delete("/api/projects/{pid}")
def delete_project(pid: int):
    if pid == projects.open_id:
        close_project()
    try:
        where = projects.delete(pid)
    except StoreError as e:
        refuse(e)
    server_log.server_event("project_delete", project=pid, moved_to=where)
    return {"ok": True, "moved_to": where}


@app.post("/api/projects/{pid}/open")
def open_project_route(pid: int):
    try:
        open_project(pid)
    except StoreError as e:
        raise HTTPException(404, str(e))
    return state()


@app.post("/api/projects/close")
def close_project_route():
    close_project()
    return {"ok": True}


@app.get("/api/projects/{pid}/thumb/{image_id}")
def project_thumb(pid: int, image_id: int):
    """One of a project's photos, for the mosaic on its card on the home page."""
    try:
        return FileResponse(Store(projects.folder(pid)).image_path(image_id))
    except StoreError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- project state


@app.get("/api/state")
def state():
    pid = projects.open_id
    return {"project": projects.summary(pid) if pid is not None else None,
            "classes": store.classes(), "images": store.images()}


class NewClass(BaseModel):
    name: str


@app.post("/api/classes")
def add_class(q: NewClass):
    try:
        return store.add_class(q.name)
    except StoreError as e:
        refuse(e)


@app.delete("/api/classes/{class_id}")
def delete_class(class_id: int):
    try:
        store.delete_class(class_id)
    except StoreError as e:
        refuse(e)
    return {"ok": True}


@app.put("/api/classes/{class_id}")
def rename_class(class_id: int, q: NewClass):
    try:
        return store.rename_class(class_id, q.name)
    except StoreError as e:
        refuse(e)


@app.get("/api/classes/coverage")
def class_coverage():
    """Which detector can suggest each class, and under which of its own names:
    shown as badges, so the user knows BEFORE labelling where the AI will help."""
    classes = store.classes()
    return [{"id": c["id"], **cov} for c, cov in zip(classes, detector.coverage([c["name"] for c in classes]))]


@app.get("/api/ai/catalogue")
def ai_catalogue():
    """Optional shortcuts for the class picker: the names the fast detector was
    trained on, read from its weights file (none are written in this code)."""
    return {"names": sorted(detector.vocabulary(), key=str.lower), "detector": detector.cfg[detector._closed]["label"]}


# ---------------------------------------------------------------- images


@app.post("/api/images")
async def upload(files: list[UploadFile] = File(...)):
    added, rejected = [], []
    for f in files:
        data = await f.read()
        try:
            img = store.add_image(data, f.filename or "upload")
            added.append(img)
            log.server_event("upload", image=img["id"], name=img["name"],
                             width=img["width"], height=img["height"])
        except StoreError as e:
            rejected.append({"name": f.filename, "reason": str(e)})
    return {"added": added, "rejected": rejected}


@app.get("/api/images/{image_id}/file")
def image_file(image_id: int):
    try:
        return FileResponse(store.image_path(image_id))
    except StoreError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/images/{image_id}")
def delete_image(image_id: int):
    try:
        store.delete_image(image_id)
    except StoreError as e:
        raise HTTPException(404, str(e))
    log.server_event("delete_image", image=image_id)
    return {"ok": True}


# ---------------------------------------------------------------- annotations


@app.get("/api/images/{image_id}/annotations")
def annotations(image_id: int):
    return store.annotations(image_id)


class NewAnnotation(BaseModel):
    image_id: int
    class_id: int
    kind: str
    points: list[list[float]]
    source: str = "manual"


@app.post("/api/annotations")
def add_annotation(q: NewAnnotation):
    try:
        return store.add_annotation(q.image_id, q.class_id, q.kind, q.points, q.source)
    except StoreError as e:
        refuse(e)


class AnnotationChange(BaseModel):
    class_id: int | None = None
    points: list[list[float]] | None = None


@app.put("/api/annotations/{ann_id}")
def update_annotation(ann_id: int, q: AnnotationChange):
    try:
        return store.update_annotation(ann_id, q.class_id, q.points)
    except StoreError as e:
        refuse(e)


@app.delete("/api/annotations/{ann_id}")
def delete_annotation(ann_id: int):
    try:
        return store.delete_annotation(ann_id)
    except StoreError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- AI: click-to-segment (Phase 3)


def _image_path_or_404(image_id: int) -> Path:
    try:
        return store.image_path(image_id)
    except StoreError as e:
        raise HTTPException(404, str(e))


def _model_failed(e: Exception):
    # Model trouble (missing weights, no internet for the first download, a
    # torch error) must not take the manual tool down with it: report and carry on.
    log.server_event("ai_error", error=f"{type(e).__name__}: {e}")
    raise HTTPException(503, f"segmentation model unavailable: {type(e).__name__}: {e}")


@app.get("/api/ai/status")
def ai_status():
    return {"model": segmenter.weights, "device": segmenter.device, "state": segmenter.state,
            "load_ms": segmenter.load_ms, "last_encode_ms": segmenter.last_encode_ms}


class Prepare(BaseModel):
    image_id: int


@app.post("/api/ai/prepare")
def ai_prepare(q: Prepare):
    """Embed an image ahead of the first click, so that click answers quickly."""
    path = _image_path_or_404(q.image_id)
    try:
        r = segmenter.prepare(path)
    except Exception as e:
        _model_failed(e)
    if not r["cached"]:
        log.server_event("ai_prepare", image=q.image_id, model=segmenter.weights,
                         device=segmenter.device, encode_ms=r["encode_ms"], wait_ms=r.get("wait_ms"))
    return {**r, "model": segmenter.weights, "device": segmenter.device}


class Segment(BaseModel):
    image_id: int
    points: list[list[float]] | None = None   # clicks, image pixels
    labels: list[int] | None = None           # 1 = on the object, 0 = background
    box: list[list[float]] | None = None      # [[x1, y1], [x2, y2]]


@app.post("/api/ai/segment")
def ai_segment(q: Segment):
    path = _image_path_or_404(q.image_id)
    img = store.image(q.image_id)
    for x, y in (q.points or []) + (q.box or []):
        if not (0 <= x <= img["width"] and 0 <= y <= img["height"]):
            raise HTTPException(400, f"prompt ({x}, {y}) is outside the image")
    try:
        r = segmenter.segment(path, q.points, q.labels, q.box)
    except SamError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        _model_failed(e)
    log.server_event("ai_segment", image=q.image_id, n_points=len(q.points or []),
                     n_negative=sum(1 for v in (q.labels or []) if v == 0), box=q.box is not None,
                     score=r["score"], area=r["area"], decode_ms=r["decode_ms"],
                     encode_ms=r["encode_ms"], n_vertices=len(r["polygon"] or []),
                     wait_ms=r.get("wait_ms"))
    return {**r, "model": segmenter.weights}


# ---------------------------------------------------------------- AI: suggestions (Phase 4)


@app.get("/api/ai/detectors")
def ai_detectors():
    return detector.info()


class Detect(BaseModel):
    image_id: int
    model: str = "yoloe"
    conf: float = 0.35


@app.post("/api/ai/detect")
def ai_detect(q: Detect):
    """Suggested boxes for one image, each labelled with one of the user's classes."""
    path = _image_path_or_404(q.image_id)
    classes = store.classes()
    by_name = {c["name"]: c["id"] for c in classes}
    if not 0.01 <= q.conf <= 0.99:
        raise HTTPException(400, "confidence must be between 0.01 and 0.99")
    try:
        r = detector.detect(q.model, path, [c["name"] for c in classes], conf=q.conf)
    except DetectError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.server_event("ai_error", stage="detect", model=q.model, error=f"{type(e).__name__}: {e}")
        raise HTTPException(503, f"detector unavailable: {type(e).__name__}: {e}")
    for s in r["suggestions"]:
        s["class_id"] = by_name[s["class_name"]]
    log.server_event("ai_detect", image=q.image_id, model=q.model, conf=q.conf, ms=r["ms"],
                     n=len(r["suggestions"]), unsupported=r["unsupported"], n_ignored=len(r["ignored"]),
                     wait_ms=r.get("wait_ms"))
    return {**r, "model": q.model}


# ---------------------------------------------------------------- log and export


class Events(BaseModel):
    events: list[dict]


@app.post("/api/events")
def events(q: Events):
    return {"written": log.write(q.events)}


@app.get("/api/export/formats")
def export_formats():
    """The formats the export dialog offers."""
    return [{"key": k, "label": v[0]} for k, v in export.FORMATS.items()]


@app.get("/api/export")
def export_zip(formats: str | None = None, images: bool = True, only_labelled: bool = False):
    """One zip with the chosen formats, e.g. /api/export?formats=coco,yolo_det&images=0.
    No `formats` = every format (as before)."""
    try:
        keys = export.parse_formats(formats)
    except export.ExportError as e:
        raise HTTPException(400, str(e))
    data, summary = export.build_zip(store, keys, include_images=images, only_labelled=only_labelled)
    log.server_event("export", **summary)
    name = projects.get(projects.open_id)["name"] if projects.open_id is not None else "annotations"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name).strip("_") or "annotations"
    tag = keys[0].replace("_", "-") if len(keys) == 1 else "export"
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{safe}_{tag}.zip"'})


# ---------------------------------------------------------------- run


def main() -> None:
    ap = argparse.ArgumentParser(description="Kontur annotation server")
    ap.add_argument("--port", type=int, default=8000)
    # For tests: point at a scratch folder so a test never touches real labels or the log.
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--sam", default=SAM_WEIGHTS,
                    help="SAM weights for click-to-segment, e.g. mobile_sam.pt or sam2.1_t.pt")
    args = ap.parse_args()
    configure(args.data, args.sam)
    print(f"\n  Kontur. Data: {args.data.resolve()}   Click-to-segment: {args.sam}")
    print(f"  Projects: {len(projects.reg['projects'])}"
          + (f", reopening '{projects.get(projects.open_id)['name']}'" if projects.open_id is not None else ""))
    print(f"  Open http://127.0.0.1:{args.port}   (the AI model loads in the background)\n")
    threading.Thread(target=warm_up_models, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
