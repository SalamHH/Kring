"""Anonymous devices (§8.6): register, update, and delete everything (GDPR erase, §8.8)."""

from __future__ import annotations

import secrets
import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from app.api.deps import CurrentDevice, Session, hash_secret
from app.api.errors import ApiError
from app.api.ratelimit import retry_after_header

router = APIRouter(prefix="/v1/devices", tags=["devices"])

Platform = Literal["ios", "android"]


def _check_tz(v: str | None) -> str | None:
    if v is None:
        return v
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown time zone: {v}") from e
    return v


class DeviceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    push_token: str | None = Field(default=None, min_length=1, max_length=255)
    platform: Platform | None = None
    tz: str | None = Field(default=None, max_length=64)

    _tz = field_validator("tz")(_check_tz)


class DeviceUpdate(DeviceIn):
    """Only the fields sent are changed. push_token and platform may be sent as null to clear them."""

    @field_validator("tz")
    @classmethod
    def _tz_not_null(cls, v: str | None) -> str | None:
        if v is None:
            raise ValueError("tz cannot be null")
        return v


class Registered(BaseModel):
    device_id: uuid.UUID
    secret: str


class DeviceOut(BaseModel):
    device_id: uuid.UUID
    platform: Platform | None
    tz: str
    has_push_token: bool


@router.post("", status_code=201, response_model=Registered)
async def register(request: Request, session: Session, body: DeviceIn | None = None) -> Registered:
    client = request.client.host if request.client else "unknown"
    wait = request.app.state.register_limiter.hit(client)
    if wait is not None:
        raise ApiError(
            429, "rate_limited", "Too many registrations", headers={"Retry-After": retry_after_header(wait)}
        )
    body = body or DeviceIn()
    device_id = uuid.uuid4()
    secret = secrets.token_urlsafe(32)  # 32 random bytes
    await session.execute(
        text("""
            INSERT INTO devices (id, secret_hash, push_token, platform, tz, last_seen_at)
            VALUES (:id, :h, :push_token, :platform, COALESCE(:tz, 'Europe/Oslo'), now())
        """),
        {
            "id": device_id,
            "h": hash_secret(secret),
            "push_token": body.push_token,
            "platform": body.platform,
            "tz": body.tz,
        },
    )
    return Registered(device_id=device_id, secret=secret)


async def _device_out(session: Session, device_id: uuid.UUID) -> DeviceOut:
    row = (
        await session.execute(
            text("SELECT id, platform, tz, push_token IS NOT NULL AS has FROM devices WHERE id = :id"),
            {"id": device_id},
        )
    ).one()
    return DeviceOut(device_id=row.id, platform=row.platform, tz=row.tz, has_push_token=row.has)


@router.put("/me", response_model=DeviceOut)
async def update_me(body: DeviceUpdate, device: CurrentDevice, session: Session) -> DeviceOut:
    fields = body.model_dump(exclude_unset=True)
    if fields:
        sets = ", ".join(f"{k} = :{k}" for k in fields)  # keys come from the model, not the client
        await session.execute(text(f"UPDATE devices SET {sets} WHERE id = :id"), {**fields, "id": device.id})
    return await _device_out(session, device.id)


@router.delete("/me", status_code=204)
async def delete_me(device: CurrentDevice, session: Session) -> Response:
    # places and notifications go by ON DELETE CASCADE. placement_feedback has no foreign key
    # (it outlives a deleted event), so the device's rows there are deleted by hand.
    await session.execute(
        text(
            "DELETE FROM placement_feedback WHERE place_id IN (SELECT id FROM places WHERE device_id = :id)"
        ),
        {"id": device.id},
    )
    await session.execute(text("DELETE FROM devices WHERE id = :id"), {"id": device.id})
    return Response(status_code=204)
