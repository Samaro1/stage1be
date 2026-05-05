# Insighta Labs - Profile Intelligence Service API

A secure, scalable FastAPI backend for profile intelligence enrichment with GitHub OAuth authentication. The service accepts names, enriches them using multiple external APIs, stores results in PostgreSQL, and provides advanced search, filtering, and export capabilities.

## Table of Contents
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Authentication](#authentication)
- [API Endpoints](#api-endpoints)
- [Setup Instructions](#setup-instructions)
- [Environment Variables](#environment-variables)
- [Testing](#testing)
- [Deployment](#deployment)
- [Error Handling](#error-handling)

## Features

### Data Enrichment
- Integrates with 3 external APIs:
  - **Genderize.io**: Gender prediction with confidence scores
  - **Agify.io**: Age estimation
  - **Nationalize.io**: Nationality/country prediction
- Processes and normalizes external data automatically
- Idempotent profile creation (no duplicate records)

### Performance Optimizations
- **In-memory caching**: Fast retrieval of recently accessed profiles with TTL and LRU eviction
- **Database indexing**: Optimized indexes on gender, country, age group, and composite fields for fast queries
- **Query optimization**: Efficient filtering, sorting, and pagination using indexed columns

### Bulk Data Ingestion
- **CSV upload support**: Stream-parse and validate large CSV files for bulk profile creation
- **Chunked processing**: Process data in chunks to handle large files efficiently
- **Data validation**: Comprehensive validation of CSV rows with error reporting
- **Duplicate handling**: Skip or update existing profiles during bulk import

### Backend Infrastructure
- Secure GitHub OAuth/GitHub App authentication
- Multiple auth flows: Web Portal, CLI (PKCE), and Server-to-Server
- Role-based access control (Admin, Analyst)
- Refresh token rotation with revocation tracking
- Rate limiting per endpoint
- Request/response logging middleware

### API Features
- Advanced filtering, sorting, and pagination
- Natural language search queries
- CSV export functionality
- PostgreSQL with UUID v7 IDs
- Consistent JSON responses with UTC ISO 8601 timestamps
- CORS enabled for frontend integration
- Comprehensive error handling

## Tech Stack
- **Framework**: FastAPI 0.135.3
- **ORM**: Tortoise ORM 1.1.7
- **Database**: PostgreSQL 14+
- **Authentication**: GitHub OAuth / GitHub Apps
- **Async HTTP**: httpx 0.28.1
- **Caching**: In-memory LRU cache with TTL
- **Data Ingestion**: CSV processing with validation
- **Python**: 3.12+
- **ID Generation**: uuid6 for UUID v7
- **Testing**: pytest, pytest-asyncio

## Architecture

### Authentication Flow

#### 1. Web Portal Flow
```
Frontend (Vercel) → Backend /auth/github?redirect=web
                  → GitHub Authorization Page
                  → GitHub → Backend /auth/web/callback
                  → Backend sets secure cookies
                  → Redirect to Dashboard (Frontend)
```

#### 2. CLI Flow (PKCE)
```
CLI App → Backend /auth/cli/callback (POST with code + code_verifier)
       → GitHub token exchange
       → Backend returns access_token + refresh_token (JSON)
```

#### 3. Server-to-Server Flow
```
External App → Backend /auth/github/callback (traditional OAuth)
            → Backend returns tokens (JSON)
```

### User Model
- `id`: UUID v7
- `github_id`: GitHub user ID
- `username`: GitHub username
- `email`: Primary GitHub email
- `avatar_url`: GitHub avatar
- `role`: "analyst" or "admin"
- `is_active`: Boolean
- `created_at`: ISO 8601 UTC timestamp
- `last_login_at`: ISO 8601 UTC timestamp

### Profile Model
- `id`: UUID v7
- `name`: Person name (lowercase)
- `gender`: "M" or "F"
- `gender_probability`: 0-1 confidence score
- `age`: Estimated age (integer)
- `age_group`: Age range (e.g., "30-39")
- `country_id`: ISO country code
- `country_name`: Full country name
- `country_probability`: 0-1 confidence score
- `created_at`: ISO 8601 UTC timestamp

## Authentication

### GitHub OAuth Setup

1. **Create GitHub App** (for web portal + CLI):
   - Go to GitHub Settings → Developer settings → GitHub Apps
   - Create a new GitHub App
   - Set **Authorization callback URLs** to:
     - Production: `https://stage1be-production.up.railway.app/auth/web/callback`
     - Development: `http://localhost:8000/auth/web/callback` (if needed)

2. **Generate Client Credentials**:
   - Generate a new client secret
   - Note your Client ID

3. **Set Environment Variables**:
   ```
   GITHUB_CLIENT_ID=your_client_id
   GITHUB_CLIENT_SECRET=your_client_secret
   GITHUB_REDIRECT_URI=http://localhost:8000/auth/github/callback (local)
   WEB_REDIRECT_URI=https://stage1be-production.up.railway.app/auth/web/callback (prod)
   ```

### Token Management

- **Access Token**: Short-lived (default: 3 minutes), included in Authorization header
- **Refresh Token**: Longer-lived (default: 5 minutes), can be rotated
- **Token Rotation**: Each refresh generates new tokens and revokes the old one
- **Logout**: Revokes the refresh token immediately

## API Endpoints

### Authentication Endpoints

#### GET `/auth/github`
Initiate GitHub authentication flow.
- **Query Parameters**:
  - `redirect` (optional): "web" for web portal, omit for CLI
- **Response**: Redirect to GitHub authorization page
- **Example**: `GET /auth/github?redirect=web`

#### GET `/auth/github/callback`
GitHub OAuth callback (server-to-server).
- **Query Parameters**:
  - `code`: Authorization code from GitHub
  - `state`: State parameter for CSRF protection
- **Response**: `200 OK`
  ```json
  {
    "status": "success",
    "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "refresh_token": "secure_random_token"
  }
  ```

#### GET `/auth/web/callback`
GitHub OAuth callback for web portal.
- **Query Parameters**: Same as `/auth/github/callback`
- **Response**: `307 Temporary Redirect` to frontend dashboard
- **Cookies Set**:
  - `access_token`: HttpOnly, Secure, SameSite=None
  - `refresh_token`: HttpOnly, Secure, SameSite=None

#### POST `/auth/cli/callback`
CLI authentication with PKCE code verifier.
- **Request Body**:
  ```json
  {
    "code": "authorization_code",
    "code_verifier": "pkce_code_verifier",
    "redirect_uri": "http://localhost:8888/callback"
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "status": "success",
    "access_token": "...",
    "refresh_token": "...",
    "username": "octocat"
  }
  ```

#### POST `/auth/refresh`
Refresh access token.
- **Request Body**:
  ```json
  {
    "refresh_token": "current_refresh_token"
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "status": "success",
    "access_token": "new_access_token",
    "refresh_token": "new_refresh_token"
  }
  ```

#### POST `/auth/logout`
Revoke refresh token.
- **Request Body**:
  ```json
  {
    "refresh_token": "token_to_revoke"
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "status": "success",
    "message": "Logged out successfully"
  }
  ```

#### GET `/auth/me`
Get current user info (requires authentication).
- **Headers**: `Authorization: Bearer <access_token>`
- **Response**: `200 OK`
  ```json
  {
    "status": "success",
    "data": {
      "id": "...",
      "username": "octocat",
      "email": "octocat@github.com",
      "role": "analyst",
      "avatar_url": "...",
      "is_active": true,
      "created_at": "2024-01-15T10:30:00Z",
      "last_login_at": "2024-01-20T14:22:00Z"
    }
  }
  ```

### Profile Endpoints

#### POST `/api/profiles` ⚠️ Admin Only
Create a new profile with enriched data.
- **Request Body**:
  ```json
  {
    "name": "John Doe"
  }
  ```
- **Response**: `201 Created`
  ```json
  {
    "status": "success",
    "data": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "john doe",
      "gender": "M",
      "gender_probability": 0.95,
      "age": 32,
      "age_group": "30-39",
      "country_id": "US",
      "country_name": "United States",
      "country_probability": 0.89,
      "created_at": "2024-01-15T10:30:00Z"
    }
  }
  ```

#### GET `/api/profiles`
Fetch profiles with advanced filtering, sorting, and pagination.
- **Query Parameters**:
  - `page`: Page number (default: 1)
  - `limit`: Items per page (default: 10, max: 50)
  - `gender`: Filter by gender ("M" or "F")
  - `country_id`: Filter by country code
  - `age_group`: Filter by age group
  - `min_age`: Minimum age
  - `max_age`: Maximum age
  - `min_gender_probability`: Minimum gender confidence (0-1)
  - `min_country_probability`: Minimum country confidence (0-1)
  - `sort_by`: Sort field ("age", "created_at", "gender_probability")
  - `order`: Sort order ("asc" or "desc")
- **Response**: `200 OK`
  ```json
  {
    "status": "success",
    "page": 1,
    "limit": 10,
    "total": 150,
    "total_pages": 15,
    "links": {
      "next": "/api/profiles?page=2&limit=10",
      "prev": null
    },
    "data": [...]
  }
  ```

#### GET `/api/profiles/{id}`
Get a specific profile by ID.
- **Response**: `200 OK` (profile data)

#### GET `/api/profiles/search`
Search profiles using natural language.
- **Query Parameters**:
  - `q`: Search query (required, non-empty)
  - `page`, `limit`: Pagination
- **Example**: `GET /api/profiles/search?q=male%20from%20US&page=1&limit=10`

#### GET `/api/profiles/export`
Export profiles as CSV.
- **Query Parameters**: Same filtering options as `GET /api/profiles`
- **Response**: `200 OK` with CSV file
  ```
  Content-Type: text/csv
  Content-Disposition: attachment; filename="profiles_20240115_103000.csv"
  ```

#### DELETE `/api/profiles/{id}` ⚠️ Admin Only
Delete a profile.
- **Response**: `204 No Content`

## Setup Instructions

### Local Development

1. **Clone the repository**
   ```bash
   git clone https://github.com/samaro1/stage1be
   cd stage1be/stage1be
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create `.env` file**
   ```env
   # Database
   DATABASE_URL=postgres://username:password@localhost:5432/stage1db

   # GitHub OAuth
   GITHUB_CLIENT_ID=your_client_id
   GITHUB_CLIENT_SECRET=your_client_secret
   GITHUB_REDIRECT_URI=http://localhost:8000/auth/github/callback
   WEB_REDIRECT_URI=http://localhost:8000/auth/web/callback

   # Frontend
   FRONTEND_URL=http://localhost:5500

   # JWT
   JWT_SECRET=your-secret-key-at-least-32-characters-long
   ```

5. **Run migrations** (if needed)
   ```bash
   # Tortoise ORM will auto-create tables
   ```

6. **Start the server**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

   Server runs at: `http://localhost:8000`
   API docs at: `http://localhost:8000/docs`

## Environment Variables

### Required
| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgres://user:pass@localhost:5432/db` |
| `GITHUB_CLIENT_ID` | GitHub OAuth App Client ID | `Ov23limfL4j3...` |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth App Secret | `2c6a115efc54a6ae...` |

### Optional
| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_REDIRECT_URI` | Server-to-server callback URI | `http://localhost:8000/auth/github/callback` |
| `WEB_REDIRECT_URI` | Web portal callback URI | `http://localhost:5000/auth/web/callback` |
| `FRONTEND_URL` | Frontend base URL for redirects | `http://localhost:5500` |
| `JWT_SECRET` | Secret for JWT signing | (must be set) |

## Testing

### Run Tests
```bash
# Install test dependencies (already in requirements.txt)
pip install -r requirements.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test class
pytest test_main.py::TestAuthFlow -v

# Run with detailed output
pytest -v -s
```

### Test Coverage
- ✅ Authentication flows (Web, CLI, Server-to-Server)
- ✅ Token refresh and rotation
- ✅ Logout and token revocation
- ✅ Profile creation, retrieval, filtering
- ✅ Search and export functionality
- ✅ Error handling and validation
- ✅ Rate limiting
- ✅ CORS and middleware
- ✅ End-to-end integration tests

### Test File Structure
```
test_main.py
├── TestAuthFlow          # GitHub OAuth flows
├── TestWebCallback       # Web portal callback
├── TestCLICallback       # CLI PKCE flow
├── TestRefreshToken      # Token refresh logic
├── TestLogout            # Logout functionality
├── TestProfileCreation   # Profile POST
├── TestProfileRetrieval  # Profile GET
├── TestProfileFiltering  # Filtering & pagination
├── TestProfileSearch     # Natural language search
├── TestProfileExport     # CSV export
├── TestProfileDeletion   # Profile DELETE
├── TestRateLimiting      # Rate limit middleware
├── TestErrorHandling     # Error responses
└── TestIntegration       # End-to-end tests
```

## Deployment

### Railway Deployment

1. **Push code to GitHub**
   ```bash
   git push origin main
   ```

2. **Connect to Railway**
   - Go to [railway.app](https://railway.app)
   - Create new project
   - Connect GitHub repository
   - Select branch to deploy

3. **Set Environment Variables**
   On Railway dashboard:
   - `DATABASE_URL`: PostgreSQL connection
   - `GITHUB_CLIENT_ID`: GitHub App Client ID
   - `GITHUB_CLIENT_SECRET`: GitHub App Secret
   - `GITHUB_REDIRECT_URI`: `https://stage1be-production.up.railway.app/auth/github/callback`
   - `WEB_REDIRECT_URI`: `https://stage1be-production.up.railway.app/auth/web/callback`
   - `FRONTEND_URL`: `https://insighta-labs-web.vercel.app`
   - `JWT_SECRET`: Strong random secret

4. **Update GitHub App**
   - Go to GitHub Settings → Developer settings → GitHub Apps
   - Update Callback URLs:
     - `https://stage1be-production.up.railway.app/auth/web/callback`
     - `https://stage1be-production.up.railway.app/auth/github/callback`

5. **Database Setup**
   ```bash
   # Railway will auto-create PostgreSQL
   # Tortoise ORM will auto-migrate tables on first run
   ```

6. **Deploy**
   - Railway automatically deploys on push
   - Check deployment logs: `railway logs`

### Health Check
```bash
curl -X GET https://stage1be-production.up.railway.app/auth/me
# Should return 401 (unauthenticated) which is expected
```

## Error Handling

All errors return consistent JSON format:

```json
{
  "status": "error",
  "message": "Description of error",
  "detail": { ... }
}
```

### Common Error Codes

| Status | Meaning | Example |
|--------|---------|---------|
| 400 | Bad Request | Empty name, invalid parameters |
| 401 | Unauthorized | Missing/invalid token |
| 403 | Forbidden | Insufficient permissions (not admin) |
| 404 | Not Found | Profile doesn't exist |
| 422 | Validation Error | Invalid UUID format, missing fields |
| 429 | Too Many Requests | Rate limit exceeded |
| 502 | Bad Gateway | GitHub API error |

### Rate Limiting

- **Auth endpoints**: 10 requests per 60 seconds
- **API endpoints**: 60 requests per 60 seconds
- Identified by: Authorization token or IP address

## Development Notes

### Adding a New Endpoint

1. Create endpoint function in `main.py`
2. Add appropriate dependencies (`require_admin`, `require_analyst`)
3. Return `JSONResponse` with consistent format
4. Add tests in `test_main.py`
5. Document in README

### External API Integration

The service integrates with three external APIs for enrichment:
- **Genderize.io**: Gender prediction
- **Agify.io**: Age estimation
- **Nationalize.io**: Nationality prediction

If an external API fails, the profile creation will fail gracefully with a 502 error.

## Contributing

1. Create a feature branch
2. Make changes and add tests
3. Run `pytest` to verify
4. Submit PR to `main` branch

## License

Proprietary - Insighta Labs

## Support

For issues or questions, contact the Insighta Labs team.

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

### Upload Profiles CSV
**POST /api/profiles/upload** ⚠️ Admin Only

Upload a CSV file to bulk create profiles. The CSV should have columns: name, gender, gender_probability, age, age_group, country_id, country_name, country_probability.

Request: Multipart form data with `file` field containing CSV file.

Response:
```json
{
  "status": "success",
  "inserted": 150,
  "skipped": 5,
  "errors": []
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
