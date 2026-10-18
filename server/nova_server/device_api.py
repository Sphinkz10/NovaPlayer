"""Shared validation for owner decisions and the isolated HTTPS device API."""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from fastapi.responses import JSONResponse


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid')


class StartDevice(Payload):
    label: str = Field(min_length=1, max_length=64)

    @field_validator('label')
    @classmethod
    def visible_label(cls, value):
        if not value.strip() or not value.isprintable():
            raise ValueError('Invalid label')
        return value.strip()


class DeviceCode(Payload):
    device_code: str = Field(min_length=40, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')


class RefreshDevice(Payload):
    refresh_token: str = Field(min_length=40, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')


class UserCode(Payload):
    user_code: str = Field(min_length=8, max_length=12, pattern=r'^[A-Za-z0-9 -]+$')


class DeviceDecision(UserCode):
    request_id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    approve: bool = Field(strict=True)


async def device_error(request, exc):
    return JSONResponse(status_code=exc.status, content={'error': exc.code},
                        headers={'Retry-After': str(exc.retry_after)} if exc.retry_after else {})


async def invalid_device_payload(request, exc):
    # Never echo credentials from Pydantic errors.
    return JSONResponse(status_code=422, content={'error': 'invalid_request'})
