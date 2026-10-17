import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import budget, db
from .intake.routes import router as intake_router
from .intake.brain import get_brain
from .models import DEMO_USER, Status, SubmissionIn, SubmissionOut
from .review import screening
from .meetings.routes import router as meetings_router
from .reports.routes import router as reports_router
from .scale.routes import router as scale_router
from .research.evaluation_routes import router as evaluation_router
from .research.pilot_routes import router as pilot_router
from .research.routes import router as research_router
from .review.routes import router as review_router

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Reads ANTHROPIC_API_KEY from .env (never committed). Real environment variables win.
load_dotenv(PROJECT_ROOT / ".env")


# 1. Startup: make sure the database file and tables exist before any request arrives.
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    screening.screen_unscreened()
    yield


# The application object. Every route is attached to it.
app = FastAPI(title="Innovation Hub API", lifespan=lifespan)

# Browsers must check for a newer page, script or stylesheet every time (cheap: unchanged
# files answer "304 Not Modified"), so an update is never hidden behind an old cached copy.
@app.middleware("http")
async def always_revalidate(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith(("/js/", "/styles/")):
        response.headers["Cache-Control"] = "no-cache"
    return response


# Public demo: every visitor gets a private sandbox, their own copy of the demo database tied to a
# browser cookie, so nobody sees anyone else's entries. Sandboxes untouched for 24 hours are deleted.
SANDBOXES = os.environ.get("HUB_SANDBOXES") == "on"
SANDBOX_DIR = PROJECT_ROOT / "data" / "sandboxes"
COOKIE = "hub_sandbox"
SANDBOX_HOURS = 24
MAX_SANDBOXES = 500
_last_cleanup = 0.0


def clean_old_sandboxes():
    global _last_cleanup
    if time.time() - _last_cleanup < 600:   # at most every 10 minutes
        return
    _last_cleanup = time.time()
    files = sorted(SANDBOX_DIR.glob("*.db"), key=lambda f: f.stat().st_mtime)
    for index, file in enumerate(files):
        too_old = time.time() - file.stat().st_mtime > SANDBOX_HOURS * 3600
        too_many = len(files) - index > MAX_SANDBOXES
        if too_old or too_many:
            file.unlink(missing_ok=True)


@app.middleware("http")
async def visitor_sandbox(request, call_next):
    if not SANDBOXES or not request.url.path.startswith("/api/"):
        # Only data requests need a sandbox. The page, scripts and styles (and Render's port
        # scan, which requests the page) are answered at once without creating one.
        return await call_next(request)
    visitor = request.cookies.get(COOKIE, "")
    is_new = not re.fullmatch(r"[0-9a-f]{32}", visitor)
    if is_new and request.url.path == "/api/health":
        # Render's health check (and any cookie-less ping) must not create a sandbox each time.
        return await call_next(request)
    if is_new:
        visitor = uuid.uuid4().hex
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    file = SANDBOX_DIR / f"{visitor}.db"
    db_token, visitor_token = db.current_file.set(file), budget.current_visitor.set(visitor)
    try:
        if not file.exists():               # a fresh copy of the demo for this visitor
            db.init_db()
            screening.screen_unscreened()
        else:
            file.touch()                    # still in use: keep it another 24 hours
        response = await call_next(request)
    finally:
        db.current_file.reset(db_token)
        budget.current_visitor.reset(visitor_token)
    if is_new:
        response.set_cookie(COOKIE, visitor, max_age=SANDBOX_HOURS * 3600, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https")
    clean_old_sandboxes()
    return response


# 2. The intake assistant's routes live in backend/intake/routes.py,
#    and the reviewer's in backend/review/routes.py.
app.include_router(intake_router)
app.include_router(review_router)
app.include_router(research_router)
app.include_router(evaluation_router)
app.include_router(pilot_router)
app.include_router(meetings_router)
app.include_router(scale_router)
app.include_router(reports_router)


# 3. Routes. Each one pairs an address with a function.
@app.get("/api/health")
def health():
    brain = get_brain()
    return {"status": "ok", "milestone": "11", "brain": brain.name,
            "public_demo": SANDBOXES, "budget": budget.status()}


@app.get("/api/submissions", response_model=list[SubmissionOut])
def list_submissions(status: Status | None = None):
    with db.connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM submissions WHERE status = ? ORDER BY pk DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM submissions ORDER BY pk DESC").fetchall()
    return [db.to_public(row) for row in rows]


@app.get("/api/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: str):
    return find_submission(submission_id)


# The plain form still posts here: it's the fallback when someone prefers a form.
@app.post("/api/submissions", response_model=SubmissionOut, status_code=201)
def create_submission(submission: SubmissionIn):
    with db.connect() as conn:
        new_id = db.insert_submission(conn, submission.model_dump(), DEMO_USER)
        screening.screen(conn, new_id)
    return find_submission(new_id)


def find_submission(submission_id: str) -> dict:
    """Look up 'SUB-0001', or reply 404."""
    with db.connect() as conn:
        record = db.get_submission(conn, submission_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    return record


# 4. The web page. Only the page, scripts and styles are public, never the
#    database, backend code or .venv.
app.mount("/js", StaticFiles(directory=PROJECT_ROOT / "js"), name="js")
app.mount("/styles", StaticFiles(directory=PROJECT_ROOT / "styles"), name="styles")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(PROJECT_ROOT / "index.html")
