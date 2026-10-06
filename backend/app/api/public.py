"""Public website endpoints. No authentication, strict validation and rate limits."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Engine, text

from app.auth.deps import engine_dependency, request_context
from app.auth.service import RequestContext
from app.core.ratelimit import limiter

router = APIRouter(prefix="/api/v1/public", tags=["public"])
Topic = Literal["Request a walkthrough", "Technical question", "Partnership", "Other"]


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    company: str | None = Field(default=None, max_length=120)
    topic: Topic
    message: str = Field(min_length=10, max_length=2000)
    consent: Literal[True]
    # Honeypot: real visitors never fill this in
    website: str | None = Field(default=None, max_length=200)


@router.post("/contact", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/hour")
def contact(
    request: Request,
    response: Response,
    body: ContactIn,
    engine: Annotated[Engine, Depends(engine_dependency)],
    context: Annotated[RequestContext, Depends(request_context)],
) -> dict[str, str]:
    if body.website:
        # Accept silently so that bots get no signal, but store nothing.
        return {"status": "received"}
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO app.contact_requests
                    (name, email, company, topic, message, consent_given, client_ip)
                VALUES (:name, :email, :company, :topic, :message, TRUE, :client_ip)
                """
            ),
            {
                "name": body.name,
                "email": str(body.email),
                "company": body.company or None,
                "topic": body.topic,
                "message": body.message,
                "client_ip": context.client_ip,
            },
        )
    return {"status": "received"}
