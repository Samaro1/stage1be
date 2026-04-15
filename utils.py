from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import httpx
import asyncio


GENDERIZE_URL = "https://api.genderize.io"
AGIFY_URL = "https://api.agify.io"
NATIONALIZE_URL = "https://api.nationalize.io"


# ─── Exception Handlers ───────────────────────────────────────────────────────

async def custom_http_exception_handler(request: Request, exc: Exception):
    exc = exc if isinstance(exc, HTTPException) else HTTPException(status_code=500)
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": str(exc.detail)}
    )


async def validation_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Name must be a string"}
    )


async def fetch_external_data(name: str) -> tuple[dict, dict, dict]:
    """Call all three APIs concurrently and return raw responses."""
    async with httpx.AsyncClient() as client:
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
        raise HTTPException(status_code=502, detail={"status": "error", "message": "Genderize API error"})
    if age_res.status_code != 200:
        raise HTTPException(status_code=502, detail={"status": "error", "message": "Agify API error"})
    if nation_res.status_code != 200:
        raise HTTPException(status_code=502, detail={"status": "error", "message": "Nationalize API error"})

    return gender_res.json(), age_res.json(), nation_res.json()


def process_gender_data(data: dict) -> dict:
    """Extract and validate gender fields from Genderize response."""
    gender = data.get("gender")
    sample_size = data.get("count")

    if gender is None or sample_size == 0:
        raise HTTPException(
            status_code=422,
            detail={"status": "error", "message": "Insufficient gender data for this name"}
        )

    return {
        "gender": gender,
        "gender_probability": data.get("probability"),
        "sample_size": sample_size,
    }


def process_age_data(data: dict) -> dict:
    """Extract age and derive age_group from Agify response."""
    age = data.get("age")

    if age is None:
        raise HTTPException(
            status_code=422,
            detail={"status": "error", "message": "Insufficient age data for this name"}
        )

    if age <= 12:
        age_group = "child"
    elif age <= 19:
        age_group = "teenager"
    elif age <= 59:
        age_group = "adult"
    else:
        age_group = "senior"

    return {"age": age, "age_group": age_group}


def process_nationality_data(data: dict) -> dict:
    """Extract the highest probability country from Nationalize response."""
    countries = data.get("country", [])

    if not countries:
        raise HTTPException(
            status_code=422,
            detail={"status": "error", "message": "No nationality data found for this name"}
        )

    top_country = max(countries, key=lambda x: x.get("probability", 0))

    return {
        "country_id": top_country.get("country_id"),
        "country_probability": top_country.get("probability"),
    }