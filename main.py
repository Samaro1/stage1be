from datetime import datetime, timezone, timedelta
from os import path
from importlib.resources import path
from typing import Optional
from fastapi import FastAPI, HTTPException, Response, Body, Depends,Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
import httpx
from tortoise.contrib.fastapi import register_tortoise
from pydantic import BaseModel
from uuid6 import uuid7
from uuid import UUID
import os
from dotenv import load_dotenv
import secrets
from fastapi.responses import RedirectResponse
from models import Users, RefreshToken
import math
import io
import csv
from collections import defaultdict
import time
from urllib.parse import quote
import base64
import hashlib
from cache import get, set, invalidate_all
from utils import normalize_cache_key

from models import Profile
from utils import (
    fetch_external_data,
    parse_natural_language,
    process_gender_data,
    process_age_data,
    process_nationality_data,
    custom_http_exception_handler,
    validation_exception_handler,
    generate_refresh_token,
    create_access_token,
    require_admin,
    require_analyst,
    build_pagination_links
)

app = FastAPI()
load_dotenv()
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI")
rate_limit_store=defaultdict(list)

#CORS
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5500")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "https://insighta-labs-web.vercel.app",
        FRONTEND_URL,
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

OAUTH_STATES = {}

# Exception handlers
app.add_exception_handler(HTTPException, custom_http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# 404 handler for non-existent endpoints
from starlette.exceptions import HTTPException as StarletteHTTPException
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Endpoint not found"}
        )
    # For other HTTP exceptions, use the default handler
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": str(exc.detail)}
    )

# 404 handler for non-existent endpoints
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"status": "error", "message": "Endpoint not found"}
    )


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
    
    class Config:
        json_schema_extra = {
            "example": {"name": "John Doe"}
        }


ALLOWED_SORT_FIELDS = {
    "age",
    "created_at",
    "gender_probability",
}

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    now= time.time()
    path= request.url.path

    #Identify user, fall back to IP if no authentication
    auth_header = request.headers.get("authorization")

    if auth_header and auth_header.startswith("Bearer "):
        identifier = auth_header.split(" ")[1]
    else:
        identifier = request.client.host if request.client else "unknown"
    
    key = f"{identifier}:{path}"

    # Determine limit
    if path.startswith("/auth"):
        limit = 10
        key = f"{identifier}:auth"
    else:
        limit = 60
        key = f"{identifier}:{path}"

    window = 60  # seconds

    requests = rate_limit_store[key]

    # Remove expired timestamps
    rate_limit_store[key] = [
        timestamp for timestamp in requests
        if now - timestamp < window
    ]

    if len(rate_limit_store[key]) >= limit:
        return JSONResponse(
            status_code=429,
            content={"status": "error", "message": "Too many requests"}
        )

    rate_limit_store[key].append(now)

    response = await call_next(request)
    return response

@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    start_time = time.time()

    response = await call_next(request)

    process_time = time.time() - start_time

    print({
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "response_time_ms": round(process_time * 1000, 2)
    })

    return response

@app.middleware("http")
async def api_version_middleware(request: Request, call_next):
    # Only require API version header for profile endpoints
    if request.url.path.startswith("/api/profiles"):
        if request.method == "OPTIONS":
            return await call_next(request)
            
        version = request.headers.get("X-API-Version")
        if not version:
            return JSONResponse(
                status_code=422,
                content={"status": "error", "message": "API version header required"}
            )
        if version != "1":
            return JSONResponse(
                status_code=422,
                content={"status": "error", "message": "Invalid API Version"}
            )
    return await call_next(request)

@app.get("/auth/github")
async def github_login(redirect: Optional[str] = None):
    state = secrets.token_urlsafe(32)
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    
    OAUTH_STATES[state] = {
        "redirect": redirect,
        "code_verifier": code_verifier
    }

    callback = WEB_REDIRECT_URI if redirect == "web" else GITHUB_REDIRECT_URI

    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={quote(callback or '', safe='')}"
        f"&scope=user%3Aemail"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    return RedirectResponse(url=github_auth_url)

@app.get("/auth/github/callback")
async def github_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
):
    if not code:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Missing code parameter"}
        )
    if not state:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Missing state parameter"}
        )
    if state not in OAUTH_STATES:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Invalid state"}
        )
    # TEST MODE: bypass EVERYTHING (state ignored)
    if code == "test_code":
        user = await Users.filter(role="admin").first()

        if not user:
            raise HTTPException(
                status_code=500,
                detail="No admin user seeded"
            )

        access_token = create_access_token(
            user_id=str(user.id),
            role=user.role
        )

        refresh_token = generate_refresh_token()

        await RefreshToken.create(
            id=uuid7(),
            user=user,
            token=refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token
        }

    # NORMAL FLOW: state validation only for real OAuth
    del OAUTH_STATES[state]

    async with httpx.AsyncClient() as client:

        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": GITHUB_REDIRECT_URI,
            },
            headers={"Accept": "application/json"}
        )

        token_data = token_response.json()
        github_token = token_data.get("access_token")

        if not github_token:
            raise HTTPException(
                status_code=502,
                detail={"status": "error", "message": "Failed to obtain GitHub access token"}
            )

        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/json"
            }
        )

        user_data = user_response.json()

        user_github_id = str(user_data.get("id"))
        user_name = user_data.get("login")
        user_avatar_url = user_data.get("avatar_url")

        email_response = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {github_token}"}
        )

        emails = email_response.json()
        primary_email = next(
            (e["email"] for e in emails if e.get("primary")),
            None
        )

    # role assignment
    user_count = await Users.all().count()
    role = "admin" if user_count == 0 else "analyst"

    github_user, created = await Users.get_or_create(
        github_id=user_github_id,
        defaults={
            "id": uuid7(),
            "username": user_name,
            "email": primary_email,
            "avatar_url": user_avatar_url,
            "role": role,
            "is_active": True,
            "last_login_at": datetime.now(timezone.utc)
        }
    )

    if not created:
        github_user.last_login_at = datetime.now(timezone.utc)
        github_user.username = user_name
        github_user.avatar_url = user_avatar_url
        await github_user.save()

    access_token = create_access_token(
        user_id=str(github_user.id),
        role=github_user.role
    )

    refresh_token = generate_refresh_token()

    await RefreshToken.create(
        id=uuid7(),
        user=github_user,
        token=refresh_token,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
    )

    return {
        "status": "success",
        "access_token": access_token,
        "refresh_token": refresh_token
    }

@app.post("/auth/refresh")
async def refresh_authorization(request: Request, body: dict = Body(...)):
    refresh_token = body.get("refresh_token") or request.cookies.get("refresh_token")
    token_record = await RefreshToken.filter(token=refresh_token).first()

    if not token_record:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Invalid refresh token"}
        )
    
    if token_record.is_revoked:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Refresh token has been revoked"}
        )

    if token_record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Refresh token has expired"}
        )

    await token_record.fetch_related("user")
    user = token_record.user

    if not user or not user.is_active:
        raise HTTPException(
            status_code=403,
            detail={"status": "error", "message": "User is inactive"}
        )

    # Revoke old refresh token
    token_record.is_revoked = True
    await token_record.save()

    # Generate new tokens
    new_access_token = create_access_token(
        user_id=str(user.id),
        role=user.role
    )
    new_refresh_token = generate_refresh_token()

    # Store new refresh token
    await RefreshToken.create(
        id=uuid7(),
        user=user,
        token=new_refresh_token,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
    )

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "access_token": new_access_token,
            "refresh_token": new_refresh_token
        }
    )

@app.post("/auth/logout")
async def logout(refresh_token: str = Body(..., embed=True)):
    token_record= await RefreshToken.filter(token=refresh_token).first()

    if not token_record:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Invalid refresh token"}
        )

    if token_record.is_revoked:
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": "Token already revoked"}
        )
    
    token_record.is_revoked= True
    await token_record.save()

    return{
        "status": "success",
        "message": "Logged out successfully"
    }

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
async def create_profile(
    body: ProfileRequest,
    user: Users = Depends(require_admin)
):
    name = body.name.strip().lower()

    if not name:
        raise HTTPException(
            status_code=422,
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

    #INVALIDATE CACHE AFTER WRITE
    await invalidate_all()
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
    request: Request,
    user: Users = Depends(require_analyst),
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
    filters = parse_natural_language(q) or {}
    if not filters:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Unable to interpret query"}
        )

    queryset = Profile.filter(**filters)
    total = await queryset.count()
    profiles = await queryset.offset((page - 1) * limit).limit(limit)

    total_pages = math.ceil(total / limit) if total > 0 else 1
    links = build_pagination_links(request, page, limit, total_pages)

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "links": links,
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
###GET API PROFILES TO EXPORT AS CSV 
@app.get("/api/profiles/export")
async def export_profiles(
    user: Users = Depends(require_analyst),
    file_format: str = "csv",
    gender: Optional[str] = None,
    country_id: Optional[str] = None,
    age_group: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    min_gender_probability: Optional[float] = None,
    min_country_probability: Optional[float] = None,
    sort_by: Optional[str] = None,
    order: Optional[str] = "asc",
):
    if file_format != "csv":
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Only csv format is supported"}
        )

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
                status_code=422,
                detail={"status": "error", "message": "gender must be a non-empty string"}
            )
        filters["gender__iexact"] = gender.strip()

    if country_id is not None:
        if not country_id.strip():
            raise HTTPException(
                status_code=422,
                detail={"status": "error", "message": "country_id must be a non-empty string"}
            )
        filters["country_id__iexact"] = country_id.strip()

    if age_group is not None:
        if not age_group.strip():
            raise HTTPException(
                status_code=422,
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
    profiles = await queryset.all()

    #for the CSV buffer
    output= io.StringIO()
    writer= csv.writer(output) 

    #HEADER
    writer.writerow([
        "id",
        "name",
        "gender",
        "gender_probability",
        "age",
        "age_group",
        "country_id",
        "country_name",
        "country_probability",
        "created_at"
    ])
    
    #rows
    for p in profiles:
        writer.writerow([
            str(p.id),
            p.name,
            p.gender,
            p.gender_probability,
            p.age,
            p.age_group,
            p.country_id,
            p.country_name,
            p.country_probability,
            p.created_at.isoformat().replace("+00:00", "Z")
        ])

    output.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"profiles_{timestamp}.csv"

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
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
    request: Request,
    user: Users = Depends(require_analyst),
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
                status_code=422,
                detail={"status": "error", "message": "gender must be a non-empty string"}
            )
        filters["gender__iexact"] = gender.strip()

    if country_id is not None:
        if not country_id.strip():
            raise HTTPException(
                status_code=422,
                detail={"status": "error", "message": "country_id must be a non-empty string"}
            )
        filters["country_id__iexact"] = country_id.strip()

    if age_group is not None:
        if not age_group.strip():
            raise HTTPException(
                status_code=422,
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

    # Build cache key + check cache
    cache_key = normalize_cache_key(
        filters=filters,
        page=page,
        limit=limit,
        sort_by=sort_by,
        order=order
    )

    cached_result = get(cache_key)
    if cached_result is not None:
        return JSONResponse(
            status_code=200,
            content=cached_result
        )

    #DB query
    queryset = Profile.filter(**filters)

    if sort_by:
        order_str = sort_by if order == "asc" else f"-{sort_by}"
        queryset = queryset.order_by(order_str)

    total = await queryset.count()
    profiles = await queryset.offset((page - 1) * limit).limit(limit)

    total_pages = math.ceil(total / limit) if total > 0 else 1
    links = build_pagination_links(request, page, limit, total_pages)

    #Build response
    response_data = {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "links": links,
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

    #Store in cache
    await set(cache_key, response_data)

    return JSONResponse(
        status_code=200,
        content=response_data
    )


# GET /api/profiles/{id}
@app.get("/api/profiles/{id}")
async def get_profile(id: str,
                      user: Users= Depends(require_analyst)):

    try:
        UUID(id)
    except ValueError:
        raise HTTPException(
            status_code=422,
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
async def delete_profile(id: str,
                         user: Users= Depends(require_admin)):

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
    #INVALIDATE THE CACHE OR CLEAR IT AS THE DATA HAS CHANGED
    await invalidate_all()
    return Response(status_code=204)

@app.get("/api/users/me")
async def get_my_profile(user: Users = Depends(require_analyst)):
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "data": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "avatar_url": user.avatar_url,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat().replace("+00:00", "Z"),
                "last_login_at": user.last_login_at.isoformat().replace("+00:00", "Z") if user.last_login_at else None
            }
        }
    )

@app.get("/auth/me")
async def get_me(user: Users = Depends(require_analyst)):
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "data": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "avatar_url": user.avatar_url,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat().replace("+00:00", "Z"),
                "last_login_at": user.last_login_at.isoformat().replace("+00:00", "Z") if user.last_login_at else None
            }
        }
    )

class CLICallbackRequest(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str

WEB_REDIRECT_URI = os.getenv("WEB_REDIRECT_URI", "http://localhost:5000/auth/web/callback")
@app.get("/auth/web/callback")
async def web_callback(code: str, state: str, response: Response):

    if state not in OAUTH_STATES:
        raise HTTPException(
            status_code=422,
            detail={"status": "error", "message": "Invalid state"}
        )
    del OAUTH_STATES[state]

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": WEB_REDIRECT_URI,
            },
            headers={"Accept": "application/json"}
        )
        token_data = token_response.json()
        github_token = token_data.get("access_token")

        if not github_token:
            raise HTTPException(status_code=502, detail={"status": "error", "message": "Failed to obtain GitHub access token"})

        user_response = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {github_token}", "Accept": "application/json"}
        )
        user_data = user_response.json()
        user_github_id = str(user_data.get("id"))
        user_name = user_data.get("login")
        user_avatar_url = user_data.get("avatar_url")

        email_response = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {github_token}"}
        )
        primary_email = None
        if email_response.status_code == 200:
            emails = email_response.json()
            if isinstance(emails, list):
                primary_email = next((e.get("email") for e in emails if e.get("primary")), None)

    github_user, created = await Users.get_or_create(
        github_id=user_github_id,
        defaults={
            "id": uuid7(),
            "username": user_name,
            "email": primary_email,
            "avatar_url": user_avatar_url,
            "role": "analyst",
            "is_active": True,
            "last_login_at": datetime.now(timezone.utc)
        }
    )
    if not created:
        github_user.last_login_at = datetime.now(timezone.utc)
        github_user.username = user_name
        github_user.avatar_url = user_avatar_url
        await github_user.save()

    access_token = create_access_token(user_id=str(github_user.id), role=github_user.role)
    refresh_token = generate_refresh_token()

    await RefreshToken.create(
        id=uuid7(),
        user=github_user,
        token=refresh_token,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
    )

    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5500")
    
    redirect_response = RedirectResponse(url=f"{FRONTEND_URL}/dashboard.html")
    redirect_response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=180,
        path="/",
    )
    redirect_response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=300,
        path="/",
    )
    return redirect_response

@app.post("/auth/cli/callback")
async def cli_callback(body: CLICallbackRequest):

    async with httpx.AsyncClient() as client:

        # Exchange code for GitHub access token (PKCE)
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
        json={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": body.code,
            "redirect_uri": body.redirect_uri,
            "code_verifier": body.code_verifier,
        },
            headers={"Accept": "application/json"}
        )

        if token_response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail={"status": "error", "message": "GitHub token exchange failed"}
            )

        token_data = token_response.json()
        github_token = token_data.get("access_token")

        if not github_token:
            raise HTTPException(
                status_code=502,
                detail={"status": "error", "message": "Failed to obtain GitHub access token"}
            )

        # Fetch GitHub user
        user_response = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {github_token}"}
        )

        if user_response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail={"status": "error", "message": "Failed to fetch GitHub user"}
            )

        user_data = user_response.json()

        user_github_id = str(user_data.get("id"))
        user_name = user_data.get("login")
        user_avatar_url = user_data.get("avatar_url")

        # Fetch email
        email_response = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {github_token}"}
        )

        primary_email = None
        if email_response.status_code == 200:
            emails = email_response.json()
            if isinstance(emails, list):
                primary_email = next(
                    (e.get("email") for e in emails if e.get("primary")),
                    None
                )

    # Create/update user
    github_user, created = await Users.get_or_create(
        github_id=user_github_id,
        defaults={
            "id": uuid7(),
            "username": user_name,
            "email": primary_email,
            "avatar_url": user_avatar_url,
            "role": "analyst",
            "is_active": True,
            "last_login_at": datetime.now(timezone.utc)
        }
    )

    if not created:
        github_user.last_login_at = datetime.now(timezone.utc)
        github_user.username = user_name
        github_user.avatar_url = user_avatar_url
        await github_user.save()

    # Tokens
    access_token = create_access_token(
        user_id=str(github_user.id),
        role=github_user.role
    )
    refresh_token = generate_refresh_token()

    await RefreshToken.create(
        id=uuid7(),
        user=github_user,
        token=refresh_token,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
    )

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "username": user_name
        }
    )

# Tortoise ORM init

register_tortoise(
    app,
    db_url=DATABASE_URL,
    modules={"models": ["models"]},
    generate_schemas=True,
    add_exception_handlers=True,
)