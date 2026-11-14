from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, approval, audit, auth, batch, chat, drafts, master, ocr, orders, params
from app.core.errors import BizError
from app.core.logging import setup_logging

setup_logging()
app = FastAPI(title="智能商贸提单助手")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BizError)
async def biz_error_handler(_: Request, exc: BizError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "issues": exc.detail})


for r in (
    auth.router, master.router, drafts.router, chat.router, ocr.router, batch.router, orders.router, approval.router,
    admin.router, params.router, audit.router,
):
    app.include_router(r)


@app.get("/api/health")
async def health():
    return {"ok": True}
