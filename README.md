# Profile Intelligence Service

This project is a Profile Intelligence Service API built with FastAPI. It accepts a name, enriches it using multiple external APIs, stores the result, and provides endpoints to retrieve, filter, search, and manage the data.

## Features
- Integrates with 3 external APIs:
  - Gender prediction (Genderize.io)
  - Age estimation (Agify.io)
  - Nationality prediction (Nationalize.io)
- Processes and normalizes external data
- Stores structured data in PostgreSQL with UUID v7 IDs
- Provides RESTful endpoints with advanced filtering, sorting, and pagination
- Implements idempotency (no duplicate records)
- Supports natural language search queries
- Handles edge cases and external API failures
- Returns consistent JSON responses with UTC ISO 8601 timestamps
- CORS enabled with `Access-Control-Allow-Origin: *`

## Tech Stack
- FastAPI
- Tortoise ORM
- PostgreSQL
- httpx (async API requests)
- Python 3.12
- uuid6 for UUID v7 generation

## Setup Instructions
1. Clone the repository
   ```
   git clone https://github.com/samaro1/stage1be
   cd stage1be
   ```
2. Create virtual environment
   ```
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies
   ```
   pip install -r requirements.txt
   ```
4. Setup environment variables
   Create a `.env` file:
   ```
   DATABASE_URL=postgres://username:yourpassword@localhost:5432/stage1db
   ```
5. Run the server
   ```
   uvicorn main:app --reload
   ```

   Server runs on: http://localhost:8000

## API Endpoints

### Create Profile
**POST /api/profiles**

Request:
```json
{
  "name": "ella"
}
```

Response:
```json
{
  "status": "success",
  "data": {
    "id": "018f8b8c-1234-5678-9abc-def012345678",
    "name": "ella",
    "gender": "female",
    "gender_probability": 0.99,
    "age": 46,
    "age_group": "adult",
    "country_id": "US",
    "country_name": "United States",
    "country_probability": 0.85,
    "created_at": "2026-04-01T12:00:00Z"
  }
}
```

### Get Profile by ID
**GET /api/profiles/{id}**

Response:
```json
{
  "status": "success",
  "data": {
    "id": "018f8b8c-1234-5678-9abc-def012345678",
    "name": "ella",
    "gender": "female",
    "gender_probability": 0.99,
    "age": 46,
    "age_group": "adult",
    "country_id": "US",
    "country_name": "United States",
    "country_probability": 0.85,
    "created_at": "2026-04-01T12:00:00Z"
  }
}
```

### Get All Profiles (with Advanced Filtering, Sorting, and Pagination)
**GET /api/profiles**

Supported filters:
- `gender` (string)
- `age_group` (string)
- `country_id` (string)
- `min_age` (integer)
- `max_age` (integer)
- `min_gender_probability` (float)
- `min_country_probability` (float)

Sorting:
- `sort_by`: `age`, `created_at`, `gender_probability`
- `order`: `asc`, `desc`

Pagination:
- `page` (default: 1)
- `limit` (default: 10, max: 50)

Example: `/api/profiles?gender=male&country_id=NG&min_age=25&sort_by=age&order=desc&page=1&limit=10`

Response:
```json
{
  "status": "success",
  "page": 1,
  "limit": 10,
  "total": 2026,
  "data": [
    {
      "id": "018f8b8c-1234-5678-9abc-def012345678",
      "name": "emmanuel",
      "gender": "male",
      "gender_probability": 0.95,
      "age": 25,
      "age_group": "adult",
      "country_id": "NG",
      "country_name": "Nigeria",
      "country_probability": 0.90,
      "created_at": "2026-04-01T12:00:00Z"
    }
  ]
}
```

### Natural Language Search
**GET /api/profiles/search**

Supports plain English queries that are parsed into filters. Pagination applies.

Example: `/api/profiles/search?q=young males from nigeria&page=1&limit=10`

Mappings:
- "young males" → `gender=male + min_age=16 + max_age=24`
- "females above 30" → `gender=female + min_age=30`
- "people from angola" → `country_id=AO`
- "adult males from kenya" → `gender=male + age_group=adult + country_id=KE`
- "male and female teenagers above 17" → `age_group=teenager + min_age=17`

Response: Same as GET /api/profiles

If query can't be interpreted:
```json
{
  "status": "error",
  "message": "Unable to interpret query"
}
```

### Delete Profile
**DELETE /api/profiles/{id}**

Response: 204 No Content

## Error Handling
All errors follow this structure:
```json
{
  "status": "error",
  "message": "<error message>"
}
```

Status codes:
- 400 Bad Request — Missing or empty parameter
- 422 Unprocessable Entity — Invalid parameter type or value
- 404 Not Found — Profile not found
- 500/502 — Server failure or external API error
```json
{
  "name": "ella"
}
```
Response:
```json
{
  "status": "success",
  "data": {
    "id": "...",
    "name": "ella",
    "gender": "female",
    "gender_probability": 0.99,
    "sample_size": 1234,
    "age": 46,
    "age_group": "adult",
    "country_id": "US",
    "country_probability": 0.85,
    "created_at": "2026-04-01T12:00:00Z"
  }
}
```
2. Get Profile by ID

GET /api/profiles/{id}

3. Get All Profiles (with filters)

GET /api/profiles?gender=male&country_id=NG&age_group=adult

Response:
```json
{
  "status": "success",
  "count": 2,
  "data": [
    {
      "id": "...",
      "name": "emmanuel",
      "gender": "male",
      "age": 25,
      "age_group": "adult",
      "country_id": "NG"
    }
  ]
}
```
4. Delete Profile

DELETE /api/profiles/{id}

Response:

204 No Content

### Error Handling

All errors follow this structure:
```json
{
  "status": "error",
  "message": "Error description"
}
```
