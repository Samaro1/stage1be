from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.requests import Request
import httpx
from uuid6 import uuid7
from datetime import datetime, timezone

app = FastAPI()

GENDERIZE_URL= "https://api.genderize.io"
AGIFY_URL = "https://api.agify.io"
NATIONALIZE_URL = "https://api.nationalize.io"


# Custom exception handler for HTTPException to ensure error responses matches the requirement
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail
        )
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "message": str(exc.detail)
        }
    )

@app.get("/api/profiles")
async def predict(name: str = Query(..., description="The name to predict gender, age, and  nationality")):
    
    #Missing or empty name returns 400 Bad Request
    if not name.strip():
        raise HTTPException(status_code=400,detail="Name parameter must be a non-empty string")
    
    #Non-string name returns 422 Unprocessable Entity
    if not name.isalpha():
        raise HTTPException(status_code=422, detail="Name parameter must contain only alphabetic characters")

    try:
        async with httpx.AsyncClient() as client:
            genderize_response = await client.get(GENDERIZE_URL, params={"name": name})
            agify_response = await client.get(AGIFY_URL, params={"name": name})
            nationalize_response = await client.get(NATIONALIZE_URL, params={"name": name})

            if genderize_response.status_code != 200:
                raise HTTPException(status_code=genderize_response.status_code, detail=genderize_response.text)
            if agify_response.status_code != 200:
                raise HTTPException(status_code=agify_response.status_code, detail=agify_response.text)
            if nationalize_response.status_code != 200:
                raise HTTPException(status_code=nationalize_response.status_code, detail=nationalize_response.text)
            gender_data = genderize_response.json()
            age_data = agify_response.json()
            nation_data = nationalize_response.json()
            
    #Extract gender, gender_probability, and count from Genderize. Rename count to sample_size
            gender= gender_data.get("gender")
            gender_probability= gender_data.get("probability")
            sample_size= gender_data.get("count")

    #Genderize returns gender: null or count: 0 → return error, do not store
            if gender is None or sample_size == 0:
                raise HTTPException(status_code=404, detail="Gender data not found")

    #Extract age from Agify. Classify age_group: 0–12 → child, 13–19 → teenager, 20–59 → adult, 60+ → senior
            age= age_data.get("age")
            if age is not None:
                if age <= 12:
                    age_group = "child"
                elif age <= 19:
                    age_group = "teenager"
                elif age <= 59:
                    age_group = "adult"
                else:
                    age_group = "senior"
    #Agify returns age: null → return error, do not store
            else:
                raise HTTPException(status_code=404, detail="Age data not found")


    #Extract country list from Nationalize. Pick the country with the highest probability as country_id
            country_data = nation_data.get("country", [])
            if country_data:
                country_id = max(country_data, key=lambda x: x.get("probability", 0)).get("country_id")
                country_probability = max(country_data, key=lambda x: x.get("probability", 0)).get("probability")
            else:                
    #Nationalize returns no country data → return error, do not store
                raise HTTPException(status_code=404, detail="Country data not found")


    #Store the processed result with a UUID v7 id and UTC created_at timestamp
            result = {
                "id": str(uuid7()),
                "name": name,
                "gender": gender,
                "gender_probability": gender_probability,
                "sample_size": sample_size,
                "age": age,
                "age_group": age_group,
                "country_id": country_id,
                "country_probability": country_probability,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            return JSONResponse(content={"status": "success", "data": result})










    except httpx.RequestError:
         raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": "Request failed"}
        )