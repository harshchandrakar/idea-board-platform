"""Idea Board API — a deliberately tiny FastAPI service.

Full CRUD:
  GET    /api/health       -> {"status": "ok"}   (used by probes + the AI health check)
  GET    /api/ideas        -> [Idea, ...]          (newest first)
  POST   /api/ideas        -> Idea                  ({"content": "..."})
  GET    /api/ideas/{id}   -> Idea                  (single idea, 404 if missing)
  PUT    /api/ideas/{id}   -> Idea                  (update content, 404 if missing)
  DELETE /api/ideas/{id}   -> {"deleted": id}       (404 if missing)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from db import Idea, SessionLocal, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # ensure the table exists before serving traffic
    yield


app = FastAPI(title="Idea Board API", version="1.0.0", lifespan=lifespan)

# Let the browser frontend call the API cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class NewIdea(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class UpdateIdea(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ideas")
def list_ideas():
    with SessionLocal() as session:
        rows = session.query(Idea).order_by(Idea.created_at.desc(), Idea.id.desc()).all()
        return [row.to_dict() for row in rows]


@app.post("/api/ideas", status_code=201)
def add_idea(idea: NewIdea):
    with SessionLocal() as session:
        row = Idea(content=idea.content)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.to_dict()


@app.get("/api/ideas/{idea_id}")
def get_idea(idea_id: int):
    with SessionLocal() as session:
        row = session.get(Idea, idea_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Idea not found")
        return row.to_dict()


@app.put("/api/ideas/{idea_id}")
def update_idea(idea_id: int, idea: UpdateIdea):
    with SessionLocal() as session:
        row = session.get(Idea, idea_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Idea not found")
        row.content = idea.content
        session.commit()
        session.refresh(row)
        return row.to_dict()


@app.delete("/api/ideas/{idea_id}")
def delete_idea(idea_id: int):
    with SessionLocal() as session:
        row = session.get(Idea, idea_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Idea not found")
        session.delete(row)
        session.commit()
        return {"deleted": idea_id}


# --- Optional observability: expose Prometheus metrics if the package is present.
# Guarded so the app runs fine without the extra dependency (see Part G).
try:  # pragma: no cover - optional dependency
    from prometheus_fastapi_instrumentator import Instrumentator, metrics

    _inst = Instrumentator().instrument(app)
    # Explicit http_requests_total{method,handler,status} — the counter the canary
    # analysis queries (success rate = non-5xx / total). Status is the code string.
    _inst.add(metrics.requests())
    _inst.expose(app)  # adds GET /metrics
except Exception:  # pragma: no cover
    pass


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
