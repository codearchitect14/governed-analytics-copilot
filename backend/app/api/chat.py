"""Chat endpoint: runs the query pipeline and streams its steps as server sent events."""

import json
from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.deps import CurrentUserDep, request_context
from app.auth.service import CurrentUser, RequestContext
from app.core.ratelimit import limiter
from app.pipeline.orchestrator import QueryPipeline
from app.pipeline.services import get_pipeline

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: UUID | None = None


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _stream(
    pipeline: QueryPipeline,
    body: QueryRequest,
    user: CurrentUser,
    context: RequestContext,
) -> Iterator[str]:
    for item in pipeline.run(body.question, user, context, body.session_id):
        yield _sse(item.kind, item.data)


@router.post(
    "/query",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Pipeline steps, then the result",
        }
    },
)
@limiter.limit("30/minute")
def query(
    request: Request,
    body: QueryRequest,
    user: CurrentUserDep,
    context: Annotated[RequestContext, Depends(request_context)],
) -> StreamingResponse:
    pipeline = get_pipeline()
    return StreamingResponse(
        _stream(pipeline, body, user, context),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
