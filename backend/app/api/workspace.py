"""Workspace endpoints: chat history, answer feedback, saved questions and catalog metadata."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, text

from app.auth.deps import CurrentUserDep, engine_dependency
from app.core.ratelimit import limiter
from app.pipeline.services import get_pipeline

router = APIRouter(prefix="/api/v1", tags=["workspace"])
EngineDep = Annotated[Engine, Depends(engine_dependency)]


class FeedbackIn(BaseModel):
    audit_id: int | None = None
    value: str = Field(pattern="^(up|down)$")
    comment: str | None = Field(default=None, max_length=500)


class SavedQueryIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=500)


def _rows(engine: Engine, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text(sql), params).mappings()]


# ---- chat history -------------------------------------------------------------------------------


@router.get("/chat/sessions")
def list_sessions(
    user: CurrentUserDep,
    engine: EngineDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return [
        {"id": str(row["id"]), "title": row["title"], "created_at": row["created_at"].isoformat()}
        for row in _rows(
            engine,
            "SELECT id, title, created_at FROM app.chat_sessions WHERE user_id = CAST(:u AS UUID) "
            "ORDER BY created_at DESC, id LIMIT :limit OFFSET :offset",
            {"u": str(user.id), "limit": limit, "offset": offset},
        )
    ]


@router.get("/chat/sessions/{session_id}")
def get_session(session_id: UUID, user: CurrentUserDep, engine: EngineDep) -> dict[str, Any]:
    owned = _rows(
        engine,
        "SELECT id, title FROM app.chat_sessions WHERE id = CAST(:s AS UUID) AND user_id = CAST(:u AS UUID)",
        {"s": str(session_id), "u": str(user.id)},
    )
    if not owned:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    messages = _rows(
        engine,
        "SELECT role, content, created_at FROM app.chat_messages WHERE session_id = CAST(:s AS UUID) ORDER BY created_at",
        {"s": str(session_id)},
    )
    return {
        "id": str(session_id),
        "title": owned[0]["title"],
        "messages": [
            {
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in messages
        ],
    }


# ---- feedback -------------------------------------------------------------------------------------


@router.post("/chat/feedback", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
def submit_feedback(
    request: Request, response: Response, body: FeedbackIn, user: CurrentUserDep, engine: EngineDep
) -> dict[str, str]:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app.answer_feedback (user_id, audit_id, value, comment) "
                "VALUES (CAST(:u AS UUID), :a, :v, :c)"
            ),
            {"u": str(user.id), "a": body.audit_id, "v": body.value, "c": body.comment},
        )
    return {"status": "recorded"}


# ---- saved questions -----------------------------------------------------------------------------


@router.get("/saved-queries")
def list_saved(
    user: CurrentUserDep,
    engine: EngineDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "question": row["question"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in _rows(
            engine,
            "SELECT id, title, question, created_at FROM app.saved_queries "
            "WHERE user_id = CAST(:u AS UUID) ORDER BY created_at DESC, id LIMIT :limit OFFSET :offset",
            {"u": str(user.id), "limit": limit, "offset": offset},
        )
    ]


@router.post("/saved-queries", status_code=status.HTTP_201_CREATED)
def create_saved(body: SavedQueryIn, user: CurrentUserDep, engine: EngineDep) -> dict[str, str]:
    with engine.begin() as connection:
        identifier: UUID = connection.execute(
            text(
                "INSERT INTO app.saved_queries (user_id, title, question) VALUES (CAST(:u AS UUID), :t, :q) RETURNING id"
            ),
            {"u": str(user.id), "t": body.title, "q": body.question},
        ).scalar_one()
    return {"id": str(identifier)}


@router.delete("/saved-queries/{saved_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved(saved_id: UUID, user: CurrentUserDep, engine: EngineDep) -> Response:
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM app.saved_queries WHERE id = CAST(:i AS UUID) AND user_id = CAST(:u AS UUID)"
            ),
            {"i": str(saved_id), "u": str(user.id)},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/saved-queries/{saved_id}/run")
def run_saved(saved_id: UUID, user: CurrentUserDep, engine: EngineDep) -> dict[str, str]:
    """Returns the saved question. The client sends it to the chat endpoint, so the normal policy applies."""
    rows = _rows(
        engine,
        "SELECT question FROM app.saved_queries WHERE id = CAST(:i AS UUID) AND user_id = CAST(:u AS UUID)",
        {"i": str(saved_id), "u": str(user.id)},
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Saved question not found"
        )
    return {"question": str(rows[0]["question"])}


# ---- catalog ------------------------------------------------------------------------------------


@router.get("/catalog/meta")
def catalog_meta(user: CurrentUserDep) -> dict[str, Any]:
    pipeline = get_pipeline()
    return {"data_as_of": pipeline.data_as_of().isoformat(), "role": user.role}


@router.get("/catalog/metrics")
def catalog_metrics(user: CurrentUserDep) -> list[dict[str, Any]]:
    vocabulary = get_pipeline().services.vocabulary
    return [
        {
            "name": item.name,
            "label": item.label,
            "description": item.description,
            "synonyms": list(item.synonyms),
        }
        for item in sorted(vocabulary.metrics.values(), key=lambda entry: entry.label)
    ]


@router.get("/catalog/dimensions")
def catalog_dimensions(user: CurrentUserDep) -> list[dict[str, Any]]:
    vocabulary = get_pipeline().services.vocabulary
    values: dict[str, list[str]] = {}
    for mapping in vocabulary.values:
        values.setdefault(mapping.dimension, []).append(mapping.value)
    return [
        {"name": name, "synonyms": list(terms), "values": sorted(values.get(name, []))}
        for name, terms in sorted(vocabulary.dimension_synonyms.items())
    ]
