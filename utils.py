from typing import Optional
from fastapi import HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import httpx
import asyncio
import re
from jose import jwt, JWTError
from datetime import datetime, timezone, timedelta
import secrets
import os
from fastapi.security import HTTPBearer,HTTPAuthorizationCredentials
from models import Users
from urllib.parse import urlencode


GENDERIZE_URL = "https://api.genderize.io"
AGIFY_URL = "https://api.agify.io"
NATIONALIZE_URL = "https://api.nationalize.io"

COUNTRY_MAP = {
    "tanzania": "TZ",
    "nigeria": "NG",
    "uganda": "UG",
    "sudan": "SD",
    "united states": "US",
    "madagascar": "MG",
    "south africa": "ZA",
    "united kingdom": "GB",
    "india": "IN",
    "cameroon": "CM",
    "mali": "ML",
    "angola": "AO",
    "kenya": "KE",
    "zambia": "ZM",
    "mozambique": "MZ",
    "france": "FR",
    "gabon": "GA",
    "rwanda": "RW",
    "namibia": "NA",
    "dr congo": "CD",
    "senegal": "SN",
    "ghana": "GH",
    "cape verde": "CV",
    "republic of the congo": "CG",
    "ethiopia": "ET",
    "eritrea": "ER",
    "morocco": "MA",
    "malawi": "MW",
    "brazil": "BR",
    "australia": "AU",
    "canada": "CA",
    "tunisia": "TN",
    "egypt": "EG",
    "algeria": "DZ",
    "libya": "LY",
    "zimbabwe": "ZW",
    "botswana": "BW",
    "somalia": "SO",
    "south sudan": "SS",
    "burundi": "BI",
    "liberia": "LR",
    "guinea": "GN",
    "guinea-bissau": "GW",
    "sierra leone": "SL",
    "togo": "TG",
    "benin": "BJ",
    "burkina faso": "BF",
    "niger": "NE",
    "chad": "TD",
    "central african republic": "CF",
    "equatorial guinea": "GQ",
    "djibouti": "DJ",
    "comoros": "KM",
    "mauritius": "MU",
    "seychelles": "SC",
    "lesotho": "LS",
    "eswatini": "SZ",
    "gambia": "GM",
    "mauritania": "MR",
    "western sahara": "EH",
    "china": "CN",
    "japan": "JP",
    "germany": "DE",
    "sao tome and principe": "ST",
}


# Exception Handlers

async def custom_http_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        if isinstance(exc.detail, dict):
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={"status": "error", "message": str(exc.detail)}
        )

    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"}
    )


async def validation_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Invalid query parameters"}
    )

# External API Fetch

async def fetch_external_data(name: str) -> tuple[dict, dict, dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            gender_res, age_res, nation_res = await asyncio.gather(
                client.get(GENDERIZE_URL, params={"name": name}),
                client.get(AGIFY_URL, params={"name": name}),
                client.get(NATIONALIZE_URL, params={"name": name}),
            )
        except httpx.RequestError:
            raise HTTPException(
                status_code=500,
                detail={"status": "error", "message": "Failed to reach external APIs"}
            )

    if gender_res.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail={"status": "error", "message": "Genderize returned an invalid response"}
        )

    if age_res.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail={"status": "error", "message": "Agify returned an invalid response"}
        )

    if nation_res.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail={"status": "error", "message": "Nationalize returned an invalid response"}
        )

    return gender_res.json(), age_res.json(), nation_res.json()


# Data Processors

def process_gender_data(data: dict) -> dict:
    gender = data.get("gender")
    count = data.get("count")

    if not gender or count in (None, 0):
        raise HTTPException(
            status_code=502,
            detail={"status": "error", "message": "Genderize returned an invalid response"}
        )

    return {
        "gender": gender,
        "gender_probability": float(data.get("probability", 0.0)),
    }


def process_age_data(data: dict) -> dict:
    age = data.get("age")

    if age is None:
        raise HTTPException(
            status_code=502,
            detail={"status": "error", "message": "Agify returned an invalid response"}
        )

    age = int(age)

    if age <= 12:
        age_group = "child"
    elif age <= 19:
        age_group = "teenager"
    elif age <= 59:
        age_group = "adult"
    else:
        age_group = "senior"

    return {
        "age": age,
        "age_group": age_group,
    }

COUNTRY_CODE_TO_NAME = {v: k.title() for k, v in COUNTRY_MAP.items()}
def process_nationality_data(data: dict) -> dict:
    countries = data.get("country")

    if not countries or not isinstance(countries, list):
        raise HTTPException(
            status_code=502,
            detail={"status": "error", "message": "Nationalize returned an invalid response"}
        )

    top_country = max(countries, key=lambda x: x.get("probability", 0))

    country_id = top_country.get("country_id")
    probability = top_country.get("probability")

    if not country_id:
        raise HTTPException(
            status_code=502,
            detail={"status": "error", "message": "Nationalize returned an invalid response"}
        )

    return {
        "country_id": country_id,
        "country_name": COUNTRY_CODE_TO_NAME.get(country_id, country_id),
        "country_probability": float(probability or 0.0),
    }

# "young males"                          → gender=male + min_age=16 + max_age=24
# "females above 30"                     → gender=female + min_age=30
# "people from angola"                   → country_id=AO
# "adult males from kenya"               → gender=male + age_group=adult + country_id=KE
# "male and female teenagers above 17"   → age_group=teenager + min_age=17
def parse_natural_language(q: str) -> dict:
    filters: dict[str, object] = {}
    q_lower = q.lower().strip()
    tokens = re.findall(r"\w+", q_lower)
    token_set = set(tokens)

    # Gender detection
    female_tokens = {"female", "females", "woman", "women"}
    male_tokens = {"male", "males", "man", "men"}
    found_female = bool(token_set & female_tokens)
    found_male = bool(token_set & male_tokens)
    if found_female and not found_male:
        filters["gender"] = "female"
    elif found_male and not found_female:
        filters["gender"] = "male"

    # Age group detection
    if "child" in q_lower or "children" in q_lower:
        filters["age_group"] = "child"
    elif "teenager" in q_lower or "teenagers" in q_lower or "teen" in token_set or "teens" in token_set:
        filters["age_group"] = "teenager"
    elif "adult" in q_lower or "adults" in q_lower:
        filters["age_group"] = "adult"
    elif "senior" in q_lower or "seniors" in q_lower or "elderly" in q_lower:
        filters["age_group"] = "senior"

    # Young range mapping
    if "young" in q_lower:
        filters.setdefault("age__gte", 16)
        filters.setdefault("age__lte", 24)

    # Age above/below patterns
    age_above_match = re.search(r"(?:above|over|older than)\s+(\d+)", q_lower)
    age_below_match = re.search(r"(?:below|under|younger than)\s+(\d+)", q_lower)
    if age_above_match:
        filters["age__gte"] = int(age_above_match.group(1))
    if age_below_match:
        filters["age__lte"] = int(age_below_match.group(1))

    # Country detection
    for country_name in sorted(COUNTRY_MAP.keys(), key=len, reverse=True):
        if country_name in q_lower:
            filters["country_id"] = COUNTRY_MAP[country_name]
            break

    return filters



JWT_SECRET = os.getenv("JWT_SECRET", "fallback_secret_for_dev")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 3
REFRESH_TOKEN_EXPIRE_MINUTES = 5

##ACCESS TOKEN UTILS 
def create_access_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Invalid or expired token"}
        )

def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


security= HTTPBearer()
from fastapi import Cookie

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    access_token: Optional[str] = Cookie(default=None)
):
    token = None
    if credentials:
        token = credentials.credentials
    elif access_token:
        token = access_token

    if not token:
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "message": "Not authenticated"}
        )

    payload = decode_access_token(token)
    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(status_code=401, detail={"status": "error", "message": "Invalid token payload"})

    user = await Users.filter(id=user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail={"status": "error", "message": "User not found"})
    if not user.is_active:
        raise HTTPException(status_code=403, detail={"status": "error", "message": "User is inactive"})

    return user

async def require_admin(user: Users = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail={
                "status": "error",
                "message": "Admin access required"
            }
        )
    return user

async def require_analyst(user: Users= Depends(get_current_user)):
    return user

def build_pagination_links(request: Request, page: int, limit: int, total_pages: int):
    base_url = str(request.url).split("?")[0]

    query_params = dict(request.query_params)

    def make_url(new_page):
        params = query_params.copy()
        params["page"] = new_page
        params["limit"] = str(limit)

        query_string = urlencode(params)
        if query_string:      
            return f"{base_url}?{query_string}"
        return base_url
    
    return {
        "self": make_url(page),
        "next": make_url(page + 1) if page < total_pages else None,
        "prev": make_url(page - 1) if page > 1 else None
    }

def normalize_cache_key(
    filters: dict,
    page: int,
    limit: int,
    sort_by: str | None = None,
    order: str | None = None,
) -> str:
    parts = []

    # Normalize and clean filters
    cleaned_filters = {}
    for key, value in filters.items():
        if value is None:
            continue

        # Normalize strings to lowercase
        if isinstance(value, str):
            value = value.strip().lower()

        cleaned_filters[key] = value

    # Sort filters by key (alphabetical sort)
    for key in sorted(cleaned_filters.keys()):
        value = cleaned_filters[key]
        parts.append(f"{key}={value}")

    # Add pagination
    parts.append(f"page={page}")
    parts.append(f"limit={limit}")

    # Add sorting, only if provided
    if sort_by:
        parts.append(f"sort_by={sort_by}")
    if order:
        parts.append(f"order={order}")

    #Join into single string
    return "|".join(parts)