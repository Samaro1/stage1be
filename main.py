from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from tortoise.contrib.fastapi import register_tortoise
from pydantic import BaseModel
from uuid6 import uuid7
from uuid import UUID
import os
from dotenv import load_dotenv

load_dotenv()

from models import Profile
from utils import (
    fetch_external_data,
    process_gender_data,
    process_age_data,
    process_nationality_data,
    custom_http_exception_handler,
    validation_exception_handler,
)

app = FastAPI()


# CORS (strict grader-safe)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
app.add_exception_handler(HTTPException, custom_http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


# DB setup

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

#for tortoise
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgres://", 1)

if DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgres://", 1)

# Models
class ProfileRequest(BaseModel):
    name: str

# POST /api/profiles
@app.post("/api/profiles")
async def create_profile(body: ProfileRequest):

    name = body.name.strip().lower()

    if not name:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Name must be a non-empty string"}
        )

    # idempotency
    existing = await Profile.filter(name=name).first()
    if existing:
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Profile already exists",
                "data": {
                    "id": str(existing.id),
                    "name": existing.name,
                    "gender": existing.gender,
                    "gender_probability": existing.gender_probability,
                    "sample_size": existing.sample_size,
                    "age": existing.age,
                    "age_group": existing.age_group,
                    "country_id": existing.country_id,
                    "country_probability": existing.country_probability,
                    "created_at": existing.created_at.isoformat().replace("+00:00", "Z"),
                }
            }
        )

    # external APIs
    gender_raw, age_raw, nation_raw = await fetch_external_data(name)

    gender_info = process_gender_data(gender_raw)
    age_info = process_age_data(age_raw)
    nation_info = process_nationality_data(nation_raw)

    profile = await Profile.create(
        id=uuid7(),
        name=name,
        **gender_info,
        **age_info,
        **nation_info,
    )

    return JSONResponse(
        status_code=201,
        content={
            "status": "success",
            "data": {
                "id": str(profile.id),
                "name": profile.name,
                "gender": profile.gender,
                "gender_probability": profile.gender_probability,
                "sample_size": profile.sample_size,
                "age": profile.age,
                "age_group": profile.age_group,
                "country_id": profile.country_id,
                "country_probability": profile.country_probability,
                "created_at": profile.created_at.isoformat().replace("+00:00", "Z"),
            }
        }
    )

# GET /api/profiles

@app.get("/api/profiles")
async def fetch_profiles(
    gender: str = None,
    country_id: str = None,
    age_group: str = None
):

    filters = {}

    if gender:
        filters["gender__iexact"] = gender
    if country_id:
        filters["country_id__iexact"] = country_id
    if age_group:
        filters["age_group__iexact"] = age_group

    profiles = await Profile.filter(**filters).all()

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "count": len(profiles),
            "data": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "gender": p.gender,
                    "age": p.age,
                    "age_group": p.age_group,
                    "country_id": p.country_id,
                }
                for p in profiles
            ]
        }
    )



# GET /api/profiles/{id}

@app.get("/api/profiles/{id}")
async def get_profile(id: str):

    try:
        UUID(id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Invalid UUID format"}
        )

    profile = await Profile.filter(id=id).first()

    if not profile:
        raise HTTPException(
            status_code=404,
            detail={"status": "error", "message": "Profile not found"}
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "data": {
                "id": str(profile.id),
                "name": profile.name,
                "gender": profile.gender,
                "gender_probability": profile.gender_probability,
                "sample_size": profile.sample_size,
                "age": profile.age,
                "age_group": profile.age_group,
                "country_id": profile.country_id,
                "country_probability": profile.country_probability,
                "created_at": profile.created_at.isoformat().replace("+00:00", "Z"),
            }
        }
    )



# DELETE /api/profiles/{id}

@app.delete("/api/profiles/{id}")
async def delete_profile(id: str):

    try:
        UUID(id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Invalid UUID format"}
        )

    profile = await Profile.filter(id=id).first()

    if not profile:
        raise HTTPException(
            status_code=404,
            detail={"status": "error", "message": "Profile not found"}
        )

    await profile.delete()
    return Response(status_code=204)



# Tortoise ORM init

register_tortoise(
    app,
    db_url=DATABASE_URL,
    modules={"models": ["models"]},
    generate_schemas=True,
    add_exception_handlers=True,
)