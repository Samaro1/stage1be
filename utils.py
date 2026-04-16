from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import httpx
import asyncio

GENDERIZE_URL = "https://api.genderize.io"
AGIFY_URL = "https://api.agify.io"
NATIONALIZE_URL = "https://api.nationalize.io"


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
        content={"status": "error", "message": "Name must be a string"}
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
        "sample_size": int(count),
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
        "country_probability": float(probability or 0.0),
    }