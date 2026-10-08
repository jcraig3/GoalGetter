"""What a person sees when something they typed is refused.

**One place for both halves.** A name made only of spaces was accepted and
saved as a blank card (QA-5); a refusal that was caught read "Value error, A
competition has to end after it starts" (QA-13), or "String should have at
least 1 character" without saying which field. The client shows the first
message it is given, so the message has to be one a person can act on.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BeforeValidator, StringConstraints


def Name(max_length: int) -> Any:  # noqa: N802 — used as a type, so named like one
    """A name: trimmed, and at least one character once trimmed.

    `"   "` used to pass `min_length=1` and save a board with a blank title.
    Trimming first makes a name of spaces an empty one, which is refused.
    """
    return Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)
    ]


def OptionalName(max_length: int) -> Any:  # noqa: N802
    """A name that may be left out: trimmed, and blank means none at all.

    For a goal, whose title falls back to whose it is and what it measures —
    a name of spaces would otherwise win over that and head the wall blank.
    """
    # The limit sits on the string branch alone: applied to the whole union it
    # is applied to None too, which has no length and raises.
    return Annotated[
        Annotated[str, StringConstraints(max_length=max_length)] | None,
        BeforeValidator(lambda v: (v.strip() or None) if isinstance(v, str) else v),
    ]


def _field(loc: tuple[Any, ...] | list[Any]) -> str:
    """"name" → "Name", "starts_at" → "Starts at". The body itself says nothing."""
    parts = [str(p) for p in loc if p not in ("body", "query", "path") and not isinstance(p, int)]
    if not parts:
        return "This"
    return parts[-1].replace("_", " ").capitalize()


def plain(error: dict[str, Any]) -> str:
    """One validation error, said the way a person would say it."""
    kind = error.get("type", "")
    ctx = error.get("ctx") or {}
    field = _field(error.get("loc", ()))
    msg = str(error.get("msg", ""))

    # A validator's own sentence — ours — with Pydantic's label taken off.
    if kind in ("value_error", "assertion_error"):
        for prefix in ("Value error, ", "Assertion failed, "):
            if msg.startswith(prefix):
                return msg[len(prefix):]
        return msg
    if kind == "missing":
        return f"{field} is required."
    if kind == "string_too_short":
        return (
            f"{field} can't be empty."
            if ctx.get("min_length") == 1
            else f"{field} needs at least {ctx.get('min_length')} characters."
        )
    if kind == "string_too_long":
        return f"{field} can be at most {ctx.get('max_length')} characters."
    if kind in ("greater_than_equal", "greater_than", "less_than_equal", "less_than"):
        bound = {
            "greater_than_equal": ("at least", "ge"),
            "greater_than": ("more than", "gt"),
            "less_than_equal": ("at most", "le"),
            "less_than": ("less than", "lt"),
        }[kind]
        return f"{field} has to be {bound[0]} {ctx.get(bound[1])}."
    if kind.endswith("_parsing") or kind.endswith("_type"):
        return f"{field} isn't a valid value."
    return f"{field}: {msg[:1].lower()}{msg[1:]}" if msg else f"{field} isn't valid."


async def handle(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """The same 422 shape as FastAPI's own — a list under `detail` — with each
    `msg` rewritten. Clients that read the list keep working; the one that
    shows the first message now shows a sentence."""
    errors = []
    for error in exc.errors():
        rewritten = dict(error)
        rewritten["msg"] = plain(error)
        # `ctx` can hold the exception object a validator raised, which does
        # not serialise; the message above already says what it said.
        rewritten.pop("ctx", None)
        errors.append(rewritten)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})
