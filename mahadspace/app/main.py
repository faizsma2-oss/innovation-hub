"""MahadSpace: the web server. Run with  uvicorn app.main:app  from the mahadspace folder."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import auth, db, insights, members, reports, telegram_routes
from .auth import current_user

STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app):
    db.init()
    yield


app = FastAPI(title="MahadSpace", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(telegram_routes.router)


@app.middleware("http")
async def no_cache_for_api(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") or request.url.path in ("/", "/sw.js"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


# ── Reports ──────────────────────────────────────────────────────────────────

Broker = Literal["vantage", "puprime"]
Section = Literal["ib_account_report", "rebate"]


@app.post("/api/reports/{broker}")
async def import_report(broker: Broker, request: Request, section: Section, filename: str = "report.xlsx",
                        user: dict = Depends(current_user)):
    data = await request.body()
    allowed = ("xlsx", "csv") if section == "rebate" else ("xlsx", "csv", "json")
    if filename.lower().rsplit(".", 1)[-1] not in allowed:
        raise HTTPException(422, f"Unsupported file type. Choose {', '.join('.' + a for a in allowed)}.")
    result = reports.import_report(user["id"], broker, section, filename, data)
    with db.connect() as conn:
        members.repair_links(conn, user["id"], reports.uid_index(conn, user["id"]))
    return result


@app.delete("/api/reports/{broker}")
def remove_report(broker: Broker, section: Section, user: dict = Depends(current_user)):
    return reports.remove_section(user["id"], broker, section)


@app.get("/api/reports/status")
def report_status(user: dict = Depends(current_user)):
    return reports.status(user["id"])


@app.get("/api/reports/data")
def report_data(user: dict = Depends(current_user)):
    return reports.data(user["id"])


@app.get("/api/reports/rebate-insights")
def rebate_insights(user: dict = Depends(current_user)):
    return insights.rebate_insights(user["id"])


@app.get("/api/reports/template.csv")
def report_template():
    header = "User ID,Account,Name,Balance,Account Equity,Last Trade Date,Last Deposit Date\n"
    example = "12345678,800123,Example Client,1250.50,1180.25,2026-08-14,2026-07-30\n"
    return PlainTextResponse(header + example, media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="mahadspace-report-template.csv"'})


# ── Dashboard cache ──────────────────────────────────────────────────────────

def dashboard_summary(user_id: int) -> dict:
    with db.connect() as conn:
        directory = members.directory(conn, user_id)
        return {"summary": directory["summary"], "last_synced_at": db.get_state(conn, user_id, "last_synced_at")}


@app.get("/api/cache")
def cache(user: dict = Depends(current_user)):
    return dashboard_summary(user["id"])


@app.post("/api/sync")
def sync(user: dict = Depends(current_user)):
    with db.connect() as conn:
        members.repair_links(conn, user["id"], reports.uid_index(conn, user["id"]))
        db.set_state(conn, user["id"], "last_synced_at", db.now())
    return dashboard_summary(user["id"])


# ── The page ─────────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/sw.js")
def service_worker():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
