## Profile Intelligence Service
This project is a Profile Intelligence Service API built with FastAPI.
It accepts a name, enriches it using multiple external APIs, stores the result, and provides endpoints to retrieve and manage the data.

### Features
- Integrates with 3 external APIs:
  - Gender prediction
  - Age estimation
  - Nationality prediction
- Processes and normalizes external data
- Stores structured data in PostgreSQL
- Provides RESTful endpoints
- Implements idempotency (no duplicate records)
- Supports filtering
- Handles edge cases and external API failures
- Returns consistent JSON responses

### Tech Stack
- FastAPI
- Tortoise ORM
- PostgreSQL
- httpx (async API requests)
- Python 3.12

## Setup Instructions 
1. Clone the repository
  git clone https://github.com/your-username/your-repo-name.git
  cd stage1be
2. Create virtual environment
  python3 -m venv venv
  source venv/bin/activate
3. Install dependencies
  pip install -r requirements.txt
4. Setup environment variables
  Create a .env file:
  create a postgres database and then use the username and password below
  DATABASE_URL=postgres://username:yourpassword@localhost:5432/stage1db
6. Run the server
  uvicorn main:app --reload
  
  Server runs on:
  
  http://localhost:8000

## API Endpoints
1. Create Profile

POST /api/profiles

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
