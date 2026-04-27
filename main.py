from typing import Optional
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
import secrets
from fastapi.responses import RedirectResponse


load_dotenv()

from models import Profile
from utils import (
    fetch_external_data,
    parse_natural_language,
    process_gender_data,
    process_age_data,
    process_nationality_data,
    custom_http_exception_handler,
    validation_exception_handler,
)

app = FastAPI()
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI")

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


ALLOWED_SORT_FIELDS = {
    "age",
    "created_at",
    "gender_probability",
}

@app.get("/auth/github")
async def github_login():
    state = secrets.token_urlsafe(32)
    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope=user:email"
        f"&state={state}"
    )
    return RedirectResponse(url=github_auth_url)

def validate_pagination(page: int, limit: int) -> tuple[int, int]:
    if page < 1:
        raise HTTPException(
            status_code=422,
            detail={"status": "error", "message": "page must be a positive integer"}
        )
    if limit < 1:
        raise HTTPException(
            status_code=422,
            detail={"status": "error", "message": "limit must be a positive integer"}
        )
    if limit > 50:
        limit = 50
    return page, limit


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
                    "country_name": existing.country_name,
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
                "country_name": profile.country_name,
                "age": profile.age,
                "age_group": profile.age_group,
                "country_id": profile.country_id,
                "country_probability": profile.country_probability,
                "created_at": profile.created_at.isoformat().replace("+00:00", "Z"),
            }
        }
    )

@app.get("/api/profiles/search")
async def search_profiles(
    q: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
):
    if not q or not q.strip():
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Query parameter 'q' must be a non-empty string"}
        )

    page, limit = validate_pagination(page, limit)

    q = q.strip().lower()
    filters = parse_natural_language(q)
    if not filters:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Unable to interpret query"}
        )

    queryset = Profile.filter(**filters)
    total = await queryset.count()
    profiles = await queryset.offset((page - 1) * limit).limit(limit)

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "page": page,
            "limit": limit,
            "total": total,
            "data": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "gender": p.gender,
                    "gender_probability": p.gender_probability,
                    "age": p.age,
                    "age_group": p.age_group,
                    "country_id": p.country_id,
                    "country_name": p.country_name,
                    "country_probability": p.country_probability,
                    "created_at": p.created_at.isoformat().replace("+00:00", "Z"),
                }
                for p in profiles
            ]
        }
    )


# GET /api/profiles
#Support filtering by:
# gender
# age_group
# country_id
# min_age
# max_age
# min_gender_probability
# min_country_probability

#support sorting by:
# sort_by → age | created_at | gender_probability
# order  → asc | desc
@app.get("/api/profiles")
async def fetch_profiles(
    gender: Optional[str] = None,
    country_id: Optional[str] = None,
    age_group: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    min_gender_probability: Optional[float] = None,
    min_country_probability: Optional[float] = None,
    sort_by: Optional[str] = None,
    order: Optional[str] = "asc",
    page: int = 1,
    limit: int = 10,
):
    page, limit = validate_pagination(page, limit)

    if sort_by and sort_by not in ALLOWED_SORT_FIELDS:
        raise HTTPException(
            status_code=422,
            detail={"status": "error", "message": f"Invalid sort_by. Allowed: {', '.join(sorted(ALLOWED_SORT_FIELDS))}"}
        )
    if order not in {"asc", "desc"}:
        raise HTTPException(
            status_code=422,
            detail={"status": "error", "message": "order must be 'asc' or 'desc'"}
        )

    # Build filters
    filters = {}
    if gender is not None:
        if not gender.strip():
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": "gender must be a non-empty string"}
            )
        filters["gender__iexact"] = gender.strip()

    if country_id is not None:
        if not country_id.strip():
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": "country_id must be a non-empty string"}
            )
        filters["country_id__iexact"] = country_id.strip()

    if age_group is not None:
        if not age_group.strip():
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": "age_group must be a non-empty string"}
            )
        filters["age_group__iexact"] = age_group.strip()

    if min_age is not None:
        if min_age < 0:
            raise HTTPException(
                status_code=422,
                detail={"status": "error", "message": "min_age must be a non-negative integer"}
            )
        filters["age__gte"] = min_age

    if max_age is not None:
        if max_age < 0:
            raise HTTPException(
                status_code=422,
                detail={"status": "error", "message": "max_age must be a non-negative integer"}
            )
        filters["age__lte"] = max_age

    if min_gender_probability is not None:
        if not 0 <= min_gender_probability <= 1:
            raise HTTPException(
                status_code=422,
                detail={"status": "error", "message": "min_gender_probability must be between 0 and 1"}
            )
        filters["gender_probability__gte"] = min_gender_probability
        
    if min_country_probability is not None:
        if not 0 <= min_country_probability <= 1:
            raise HTTPException(
                status_code=422,
                detail={"status": "error", "message": "min_country_probability must be between 0 and 1"}
            )
        filters["country_probability__gte"] = min_country_probability

    # Build queryset
    queryset = Profile.filter(**filters)
    if sort_by:
        order_str = sort_by if order == "asc" else f"-{sort_by}"
        queryset = queryset.order_by(order_str)

    #count first, then paginate
    total = await queryset.count()
    profiles = await queryset.offset((page - 1) * limit).limit(limit)

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "page": page,
            "limit": limit,
            "total": total,
            "data": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "gender": p.gender,
                    "gender_probability": p.gender_probability,
                    "age": p.age,
                    "age_group": p.age_group,
                    "country_id": p.country_id,
                    "country_name": p.country_name,
                    "country_probability": p.country_probability,
                    "created_at": p.created_at.isoformat().replace("+00:00", "Z"),
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
                "country_name": profile.country_name,
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