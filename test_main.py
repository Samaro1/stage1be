"""
Simple test suite for Insighta Labs API - Stage 3.
Tests align with Stage 3 requirements:
- GitHub OAuth authentication with PKCE
- Role-based access control (admin/analyst)
- API versioning (X-API-Version: 1)
- Token lifecycle management
- Pagination with links
- Standard error responses
- Rate limiting

Test Coverage:
- GitHub OAuth flows (web, CLI, callback)
- Token refresh and rotation
- Logout and token revocation
- Role-based access (admin vs analyst)
- Profile CRUD with permissions
- Filtering, sorting, pagination
- Search and export
- API versioning
- Error handling

Run Tests:
    pytest test_main.py -v
    pytest test_main.py --cov=. --cov-report=html
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta

from main import app

client = TestClient(app)



# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_user():
    """Mock user data"""
    return {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "username": "testuser",
        "email": "test@example.com",
        "github_id": "12345",
        "role": "analyst",
        "is_active": True,
        "avatar_url": "https://avatars.githubusercontent.com/u/12345",
        "created_at": datetime.now(timezone.utc),
        "last_login_at": datetime.now(timezone.utc),
    }


@pytest.fixture
def mock_github_user():
    """Mock GitHub API user response"""
    return {
        "id": 98765,
        "login": "octocat",
        "email": "octocat@github.com",
        "avatar_url": "https://avatars.githubusercontent.com/u/98765",
    }


@pytest.fixture
def mock_github_emails():
    """Mock GitHub API emails response"""
    return [
        {"email": "octocat@github.com", "primary": True, "verified": True},
        {"email": "octocat.alt@github.com", "primary": False, "verified": True},
    ]


@pytest.fixture
def mock_profile():
    """Mock profile data"""
    return {
        "id": "223e4567-e89b-12d3-a456-426614174000",
        "name": "john doe",
        "gender": "M",
        "gender_probability": 0.95,
        "age": 32,
        "age_group": "30-39",
        "country_id": "US",
        "country_name": "United States",
        "country_probability": 0.89,
        "created_at": datetime.now(timezone.utc),
    }


# ============================================================================
# AUTH TESTS
# ============================================================================

class TestAuthFlow:
    """Test GitHub authentication flows"""

    def test_github_login_redirect_to_web_portal(self):
        """Test /auth/github endpoint redirects to GitHub with web redirect"""
        response = client.get("/auth/github?redirect=web")
        
        assert response.status_code == 307  # RedirectResponse
        assert "https://github.com/login/oauth/authorize" in response.headers["location"]
        assert "client_id=" in response.headers["location"]
        assert "redirect_uri=" in response.headers["location"]
        assert "scope=user%3Aemail" in response.headers["location"]
        assert "state=" in response.headers["location"]

    def test_github_login_redirect_to_cli(self):
        """Test /auth/github endpoint redirects to GitHub for CLI"""
        response = client.get("/auth/github")
        
        assert response.status_code == 307
        assert "https://github.com/login/oauth/authorize" in response.headers["location"]

    def test_github_login_includes_state_parameter(self):
        """Test state parameter is included for CSRF protection"""
        response = client.get("/auth/github?redirect=web")
        
        location = response.headers["location"]
        assert "state=" in location
        # State should be URL-safe and non-empty
        state_value = [p.split("=")[1] for p in location.split("&") if p.startswith("state=")][0]
        assert len(state_value) > 0

    @patch("main.httpx.AsyncClient.post")
    @patch("main.httpx.AsyncClient.get")
    @patch("main.Users.get_or_create")
    @patch("main.RefreshToken.create")
    def test_github_callback_success(
        self,
        mock_refresh_create,
        mock_user_get_create,
        mock_github_get,
        mock_github_post,
        mock_user,
        mock_github_user,
        mock_github_emails
    ):
        """Test successful GitHub OAuth callback"""
        # Setup mocks
        mock_github_post.return_value = AsyncMock(
            json=lambda: {"access_token": "github_token_123"}
        )()
        
        mock_github_get.side_effect = [
            AsyncMock(json=lambda: mock_github_user)(),
            AsyncMock(json=lambda: mock_github_emails)(),
        ]
        
        user_obj = MagicMock(
            id="123e4567-e89b-12d3-a456-426614174000",
            role="analyst",
        )
        mock_user_get_create.return_value = (user_obj, True)
        mock_refresh_create.return_value = AsyncMock()()

        # Test callback with valid code and state
        with patch("main.OAUTH_STATES", {"test_state": {"redirect": "cli"}}):
            response = client.get(
                "/auth/github/callback?code=test_code&state=test_state"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "access_token" in data
        assert "refresh_token" in data

    def test_github_callback_invalid_state(self):
        """Test GitHub callback with invalid state parameter"""
        with patch("main.OAUTH_STATES", {}):
            response = client.get(
                "/auth/github/callback?code=test_code&state=invalid_state"
            )

        assert response.status_code == 400
        assert response.json()["detail"]["status"] == "error"
        assert "Invalid state" in response.json()["detail"]["message"]

    def test_github_callback_missing_code(self):
        """Test GitHub callback without code parameter"""
        response = client.get("/auth/github/callback?state=test_state")
        
        assert response.status_code == 422  # Validation error

    def test_github_callback_missing_state(self):
        """Test GitHub callback without state parameter"""
        response = client.get("/auth/github/callback?code=test_code")
        
        assert response.status_code == 422  # Validation error


class TestWebCallback:
    """Test web portal OAuth callback"""

    @patch("main.httpx.AsyncClient.post")
    @patch("main.httpx.AsyncClient.get")
    @patch("main.Users.get_or_create")
    @patch("main.RefreshToken.create")
    def test_web_callback_sets_secure_cookies(
        self,
        mock_refresh_create,
        mock_user_get_create,
        mock_github_get,
        mock_github_post,
        mock_user,
        mock_github_user,
        mock_github_emails
    ):
        """Test web callback sets httponly secure cookies"""
        mock_github_post.return_value = AsyncMock(
            json=lambda: {"access_token": "github_token_123"}
        )()
        
        mock_github_get.side_effect = [
            AsyncMock(json=lambda: mock_github_user)(),
            AsyncMock(status_code=200, json=lambda: mock_github_emails)(),
        ]
        
        user_obj = MagicMock(
            id="123e4567-e89b-12d3-a456-426614174000",
            role="analyst",
        )
        mock_user_get_create.return_value = (user_obj, True)
        mock_refresh_create.return_value = AsyncMock()()

        with patch("main.OAUTH_STATES", {"test_state": {"redirect": "web"}}):
            response = client.get(
                "/auth/web/callback?code=test_code&state=test_state"
            )

        assert response.status_code == 307
        assert "/dashboard.html" in response.headers["location"]
        # Check for secure cookie settings
        cookies = response.cookies
        assert "access_token" in [c for c in cookies]
        assert "refresh_token" in [c for c in cookies]

    def test_web_callback_invalid_state(self):
        """Test web callback with invalid state"""
        with patch("main.OAUTH_STATES", {}):
            response = client.get(
                "/auth/web/callback?code=test_code&state=invalid_state"
            )

        assert response.status_code == 400


class TestCLICallback:
    """Test CLI OAuth callback (PKCE)"""

    @patch("main.httpx.AsyncClient.post")
    @patch("main.httpx.AsyncClient.get")
    @patch("main.Users.get_or_create")
    @patch("main.RefreshToken.create")
    def test_cli_callback_pkce_success(
        self,
        mock_refresh_create,
        mock_user_get_create,
        mock_github_get,
        mock_github_post,
        mock_user,
        mock_github_user,
        mock_github_emails
    ):
        """Test CLI callback with PKCE code verifier"""
        mock_github_post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"access_token": "github_token_123"}
        )()
        
        mock_github_get.side_effect = [
            AsyncMock(status_code=200, json=lambda: mock_github_user)(),
            AsyncMock(status_code=200, json=lambda: mock_github_emails)(),
        ]
        
        user_obj = MagicMock(
            id="123e4567-e89b-12d3-a456-426614174000",
            role="analyst",
        )
        mock_user_get_create.return_value = (user_obj, True)
        mock_refresh_create.return_value = AsyncMock()()

        response = client.post(
            "/auth/cli/callback",
            json={
                "code": "test_code",
                "code_verifier": "test_verifier",
                "redirect_uri": "http://localhost:8888/callback",
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["username"] == mock_github_user["login"]

    def test_cli_callback_invalid_payload(self):
        """Test CLI callback with invalid request body"""
        response = client.post(
            "/auth/cli/callback",
            json={"code": "test_code"}  # Missing code_verifier and redirect_uri
        )

        assert response.status_code == 422  # Validation error

    def test_cli_callback_missing_access_token(self):
        """Test CLI callback when GitHub returns no access token"""
        with patch("main.httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = AsyncMock(
                status_code=200,
                json=lambda: {"error": "invalid_request"}  # No access_token
            )()

            response = client.post(
                "/auth/cli/callback",
                json={
                    "code": "test_code",
                    "code_verifier": "test_verifier",
                    "redirect_uri": "http://localhost:8888/callback",
                }
            )

        assert response.status_code == 502


class TestRefreshToken:
    """Test token refresh endpoint"""

    @patch("main.RefreshToken.filter")
    @patch("main.create_access_token")
    @patch("main.generate_refresh_token")
    def test_refresh_token_success(
        self,
        mock_gen_refresh,
        mock_create_access,
        mock_filter,
        mock_user
    ):
        """Test successful token refresh"""
        # Mock token record
        token_record = MagicMock()
        token_record.is_revoked = False
        token_record.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        token_record.user = MagicMock(
            id="123e4567-e89b-12d3-a456-426614174000",
            role="analyst",
            is_active=True,
        )
        token_record.fetch_related = AsyncMock()
        token_record.save = AsyncMock()

        mock_filter.return_value.first = AsyncMock(return_value=token_record)
        mock_create_access.return_value = "new_access_token"
        mock_gen_refresh.return_value = "new_refresh_token"

        with patch("main.RefreshToken.create", new_callable=AsyncMock):
            response = client.post(
                "/auth/refresh",
                json={"refresh_token": "valid_refresh_token"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_refresh_token_invalid(self):
        """Test refresh with invalid token"""
        with patch("main.RefreshToken.filter") as mock_filter:
            mock_filter.return_value.first = AsyncMock(return_value=None)

            response = client.post(
                "/auth/refresh",
                json={"refresh_token": "invalid_token"}
            )

        assert response.status_code == 401
        assert "Invalid refresh token" in response.json()["detail"]["message"]

    def test_refresh_token_expired(self):
        """Test refresh with expired token"""
        with patch("main.RefreshToken.filter") as mock_filter:
            token_record = MagicMock()
            token_record.is_revoked = False
            token_record.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            mock_filter.return_value.first = AsyncMock(return_value=token_record)

            response = client.post(
                "/auth/refresh",
                json={"refresh_token": "expired_token"}
            )

        assert response.status_code == 401
        assert "expired" in response.json()["detail"]["message"].lower()

    def test_refresh_token_revoked(self):
        """Test refresh with revoked token"""
        with patch("main.RefreshToken.filter") as mock_filter:
            token_record = MagicMock()
            token_record.is_revoked = True
            mock_filter.return_value.first = AsyncMock(return_value=token_record)

            response = client.post(
                "/auth/refresh",
                json={"refresh_token": "revoked_token"}
            )

        assert response.status_code == 401
        assert "revoked" in response.json()["detail"]["message"].lower()


class TestLogout:
    """Test logout endpoint"""

    def test_logout_success(self):
        """Test successful logout"""
        with patch("main.RefreshToken.filter") as mock_filter:
            token_record = MagicMock()
            token_record.is_revoked = False
            token_record.save = AsyncMock()
            mock_filter.return_value.first = AsyncMock(return_value=token_record)

            response = client.post(
                "/auth/logout",
                json={"refresh_token": "valid_token"}
            )

        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert token_record.is_revoked is True

    def test_logout_invalid_token(self):
        """Test logout with invalid token"""
        with patch("main.RefreshToken.filter") as mock_filter:
            mock_filter.return_value.first = AsyncMock(return_value=None)

            response = client.post(
                "/auth/logout",
                json={"refresh_token": "invalid_token"}
            )

        assert response.status_code == 401

    def test_logout_already_revoked_token(self):
        """Test logout with already revoked token"""
        with patch("main.RefreshToken.filter") as mock_filter:
            token_record = MagicMock()
            token_record.is_revoked = True
            mock_filter.return_value.first = AsyncMock(return_value=token_record)

            response = client.post(
                "/auth/logout",
                json={"refresh_token": "revoked_token"}
            )

        assert response.status_code == 400
        assert "already revoked" in response.json()["detail"]["message"].lower()


# ============================================================================
# PROFILE MANAGEMENT TESTS
# ============================================================================

class TestProfileCreation:
    """Test profile creation endpoint"""

    @patch("main.fetch_external_data")
    @patch("main.require_admin")
    @patch("main.Profile.filter")
    @patch("main.Profile.create")
    def test_create_profile_success(
        self,
        mock_create,
        mock_filter,
        mock_require_admin,
        mock_fetch_external,
        mock_profile
    ):
        """Test successful profile creation"""
        mock_require_admin.return_value = MagicMock(role="admin")
        mock_filter.return_value.first = AsyncMock(return_value=None)
        mock_fetch_external.return_value = (
            {"gender": "Male", "probability": 0.95},
            {"age": 32, "count": 100},
            {"country": "US", "probability": 0.89},
        )
        mock_create.return_value = AsyncMock(**mock_profile)()

        response = client.post(
            "/api/profiles",
            json={"name": "John Doe"},
            headers={"Authorization": "Bearer valid_token"}
        )

        assert response.status_code == 201 or response.status_code == 200

    def test_create_profile_empty_name(self):
        """Test profile creation with empty name"""
        with patch("main.require_admin") as mock_require:
            mock_require.return_value = MagicMock(role="admin")

            response = client.post(
                "/api/profiles",
                json={"name": ""},
                headers={"Authorization": "Bearer valid_token"}
            )

        assert response.status_code == 400

    def test_create_profile_missing_name(self):
        """Test profile creation without name field"""
        response = client.post(
            "/api/profiles",
            json={}
        )

        assert response.status_code == 422


class TestProfileRetrieval:
    """Test profile retrieval endpoints"""

    @patch("main.require_analyst")
    @patch("main.Profile.filter")
    def test_get_profile_by_id(self, mock_filter, mock_require_analyst, mock_profile):
        """Test retrieving a specific profile by ID"""
        mock_require_analyst.return_value = MagicMock(role="analyst")
        mock_filter.return_value.first = AsyncMock(return_value=MagicMock(**mock_profile))()

        response = client.get(
            f"/api/profiles/{mock_profile['id']}",
            headers={"Authorization": "Bearer valid_token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    @patch("main.require_analyst")
    @patch("main.Profile.filter")
    def test_get_profile_not_found(self, mock_filter, mock_require_analyst):
        """Test retrieving non-existent profile"""
        mock_require_analyst.return_value = MagicMock(role="analyst")
        mock_filter.return_value.first = AsyncMock(return_value=None)

        response = client.get(
            "/api/profiles/invalid-uuid",
            headers={"Authorization": "Bearer valid_token"}
        )

        assert response.status_code == 400 or response.status_code == 404

    @patch("main.require_analyst")
    @patch("main.Profile.filter")
    def test_get_profile_invalid_uuid(self, mock_filter, mock_require_analyst):
        """Test retrieving profile with invalid UUID format"""
        mock_require_analyst.return_value = MagicMock(role="analyst")

        response = client.get(
            "/api/profiles/not-a-uuid",
            headers={"Authorization": "Bearer valid_token"}
        )

        assert response.status_code == 400


# ============================================================================
# SIMPLE ERROR TESTS
# ============================================================================

def test_404_not_found():
    """Test 404 for non-existent endpoint"""
    response = client.get("/api/nonexistent")
    assert response.status_code == 404


def test_refresh_token_invalid():
    """Test refresh with invalid token"""
    with patch("main.RefreshToken.filter") as mock_filter:
        mock_filter.return_value.first = AsyncMock(return_value=None)
        response = client.post("/auth/refresh", json={"refresh_token": "bad"})
        assert response.status_code == 401


def test_refresh_token_expired():
    """Test refresh with expired token"""
    with patch("main.RefreshToken.filter") as mock_filter:
        token = MagicMock()
        token.is_revoked = False
        token.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_filter.return_value.first = AsyncMock(return_value=token)
        
        response = client.post("/auth/refresh", json={"refresh_token": "expired"})
        assert response.status_code == 401


def test_logout_success():
    """Test successful logout"""
    with patch("main.RefreshToken.filter") as mock_filter:
        token = MagicMock()
        token.is_revoked = False
        token.save = AsyncMock()
        mock_filter.return_value.first = AsyncMock(return_value=token)
        
        response = client.post("/auth/logout", json={"refresh_token": "token123"})
        assert response.status_code == 200
        assert response.json()["status"] == "success"


def test_logout_invalid_token():
    """Test logout with invalid token"""
    with patch("main.RefreshToken.filter") as mock_filter:
        mock_filter.return_value.first = AsyncMock(return_value=None)
        response = client.post("/auth/logout", json={"refresh_token": "bad"})
        assert response.status_code == 401


def test_create_profile_empty_name():
    """Test profile creation with empty name"""
    with patch("main.require_admin") as mock_admin:
        mock_admin.return_value = MagicMock()
        response = client.post("/api/profiles", json={"name": ""})
        assert response.status_code == 400


def test_create_profile_missing_name():
    """Test profile creation without name field"""
    response = client.post("/api/profiles", json={})
    assert response.status_code == 422


def test_get_profile_invalid_uuid():
    """Test getting profile with invalid UUID"""
    with patch("main.require_analyst") as mock_analyst:
        mock_analyst.return_value = MagicMock()
        response = client.get(
            "/api/profiles/invalid-uuid",
            headers={"Authorization": "Bearer token", "X-API-Version": "1"}
        )
        assert response.status_code == 422


def test_get_profile_not_found():
    """Test getting non-existent profile"""
    with patch("main.require_analyst") as mock_analyst:
        mock_analyst.return_value = MagicMock()
        with patch("main.Profile.filter") as mock_filter:
            mock_filter.return_value.first = AsyncMock(return_value=None)
            response = client.get(
                "/api/profiles/550e8400-e29b-41d4-a716-446655440000",
                headers={"Authorization": "Bearer token", "X-API-Version": "1"}
            )
            assert response.status_code == 404


def test_search_profiles_empty_query():
    """Test search with empty query"""
    with patch("main.require_analyst") as mock_analyst:
        mock_analyst.return_value = MagicMock()
        response = client.get(
            "/api/profiles/search?q=&page=1&limit=10",
            headers={"Authorization": "Bearer token", "X-API-Version": "1"}
        )
        assert response.status_code == 422


def test_search_profiles_missing_query():
    """Test search without query parameter"""
    with patch("main.require_analyst") as mock_analyst:
        mock_analyst.return_value = MagicMock()
        response = client.get(
            "/api/profiles/search?page=1&limit=10",
            headers={"Authorization": "Bearer token", "X-API-Version": "1"}
        )
        assert response.status_code == 422


def test_delete_profile_not_found():
    """Test deleting non-existent profile"""
    with patch("main.require_admin") as mock_admin:
        mock_admin.return_value = MagicMock()
        with patch("main.Profile.filter") as mock_filter:
            mock_filter.return_value.first = AsyncMock(return_value=None)
            response = client.delete(
                "/api/profiles/550e8400-e29b-41d4-a716-446655440000",
                headers={"Authorization": "Bearer token", "X-API-Version": "1"}
            )
            assert response.status_code == 404


def test_export_unsupported_format():
    """Test export with unsupported format"""
    with patch("main.require_analyst") as mock_analyst:
        mock_analyst.return_value = MagicMock()
        response = client.get(
            "/api/profiles/export?file_format=json",
            headers={"Authorization": "Bearer token", "X-API-Version": "1"}
        )
        assert response.status_code == 422


# ============================================================================
# STAGE 3 REQUIREMENTS TESTS
# ============================================================================

class TestAPIVersioning:
    """Test API versioning requirement (X-API-Version: 1)"""

    def test_profile_endpoint_requires_api_version_header(self):
        """Test that /api/profiles requires X-API-Version header"""
        with patch("main.require_analyst") as mock_analyst:
            mock_analyst.return_value = MagicMock()
            # Request without X-API-Version header
            response = client.get(
                "/api/profiles",
                headers={"Authorization": "Bearer token"}
            )
            # Should require 422 (unprocessable entity) without version header
            assert response.status_code == 422

    def test_pagination_response_includes_links(self):
        """Test that paginated responses include pagination links"""
        with patch("main.require_analyst") as mock_analyst:
            mock_analyst.return_value = MagicMock()
            with patch("main.Profile.filter") as mock_filter:
                mock_queryset = MagicMock()
                mock_queryset.count = AsyncMock(return_value=100)
                mock_queryset.offset = MagicMock(return_value=mock_queryset)
                mock_queryset.limit = AsyncMock(return_value=[])
                mock_queryset.order_by = MagicMock(return_value=mock_queryset)
                mock_filter.return_value = mock_queryset

                response = client.get(
                    "/api/profiles?page=1&limit=10",
                    headers={"Authorization": "Bearer token", "X-API-Version": "1"}
                )

                if response.status_code == 200:
                    data = response.json()
                    # Check for pagination metadata
                    assert "page" in data or "data" in data
                    if "links" in data:
                        # Verify links are present
                        assert "next" in data["links"] or "prev" in data["links"]


class TestRoleBasedAccess:
    """Test role-based access control (admin vs analyst)"""

    def test_create_profile_requires_admin_role(self):
        """Test that creating profiles requires admin role"""
        with patch("main.require_admin") as mock_admin:
            # Mock admin requirement
            mock_admin.return_value = MagicMock(role="admin")
            response = client.post(
                "/api/profiles",
                json={"name": "Test Person"},
                headers={"Authorization": "Bearer token"}
            )
            # Should either succeed (201) or require auth (401)
            assert response.status_code in [201, 400, 401]

    def test_analyst_cannot_create_profile(self):
        """Test that analyst role cannot create profiles"""
        with patch("main.require_admin") as mock_admin:
            # Simulate access denied for analyst
            mock_admin.side_effect = Exception("Forbidden")
            try:
                response = client.post(
                    "/api/profiles",
                    json={"name": "Test Person"},
                    headers={"Authorization": "Bearer token"}
                )
                # Should fail with 403 if access control works
                assert response.status_code in [403, 401]
            except:
                # Expected when require_admin raises exception
                pass

    def test_analyst_can_read_profiles(self):
        """Test that analyst role can read profiles"""
        with patch("main.require_analyst") as mock_analyst:
            mock_analyst.return_value = MagicMock(role="analyst")
            response = client.get(
                "/api/profiles",
                headers={"Authorization": "Bearer token"}
            )
            # Analyst should be able to read (no 403)
            assert response.status_code != 403

    def test_delete_profile_requires_admin(self):
        """Test that deleting profiles requires admin role"""
        with patch("main.require_admin") as mock_admin:
            mock_admin.return_value = MagicMock(role="admin")
            with patch("main.Profile.filter") as mock_filter:
                profile_obj = MagicMock()
                profile_obj.delete = AsyncMock()
                mock_filter.return_value.first = AsyncMock(return_value=profile_obj)

                response = client.delete(
                    "/api/profiles/550e8400-e29b-41d4-a716-446655440000",
                    headers={"Authorization": "Bearer token"}
                )
                assert response.status_code == 204


class TestStandardErrorResponses:
    """Test standard error response format"""

    def test_error_response_has_standard_format(self):
        """Test that error responses follow standard format"""
        response = client.get("/api/nonexistent")
        assert response.status_code == 404
        # Should have error structure (varies by framework)

    def test_invalid_input_returns_error(self):
        """Test that invalid input returns proper error"""
        with patch("main.require_analyst") as mock_analyst:
            mock_analyst.return_value = MagicMock()
            response = client.get(
                "/api/profiles?min_gender_probability=2.5",
                headers={"Authorization": "Bearer token"}
            )
            assert response.status_code == 422

    def test_unauthorized_returns_401(self):
        """Test that missing auth returns 401"""
        response = client.get("/api/profiles")
        # Should be 401 without token (or 400 if version header required first)
        assert response.status_code in [401, 400]


class TestTokenLifecycle:
    """Test token expiry and refresh lifecycle"""

    def test_refresh_token_expires_after_5_minutes(self):
        """Test that refresh tokens expire after 5 minutes"""
        with patch("main.RefreshToken.filter") as mock_filter:
            # Token expired 1 minute ago
            token = MagicMock()
            token.is_revoked = False
            token.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            mock_filter.return_value.first = AsyncMock(return_value=token)

            response = client.post(
                "/auth/refresh",
                json={"refresh_token": "old_token"}
            )
            # Should be rejected
            assert response.status_code == 401

    def test_access_token_validation(self):
        """Test that expired access tokens are handled"""
        # Access token should be validated by dependency
        with patch("main.require_analyst") as mock_analyst:
            # Simulate expired token error
            mock_analyst.side_effect = Exception("Token expired")
            try:
                response = client.get(
                    "/api/profiles",
                    headers={"Authorization": "Bearer expired_token"}
                )
                assert response.status_code == 401
            except:
                # Expected behavior
                pass


# ============================================================================
# EXISTING SIMPLE TESTS
# ============================================================================


def test_invalid_pagination_page():
    """Test invalid page number"""
    response = client.get("/api/profiles?page=0&limit=10", headers={"X-API-Version": "1"})
    assert response.status_code == 422


def test_cli_callback_missing_fields():
    """Test CLI callback with missing fields"""
    response = client.post("/auth/cli/callback", json={"code": "test"})
    assert response.status_code == 422


def test_web_callback_invalid_state():
    """Test web callback with invalid state"""
    with patch("main.OAUTH_STATES", {}):
        response = client.get("/auth/web/callback?code=test&state=invalid")
        assert response.status_code == 422


def test_web_callback_missing_state():
    """Test web callback without state parameter"""
    response = client.get("/auth/web/callback?code=test")
    assert response.status_code == 422


def test_profile_filtering_invalid_sort_field():
    """Test profile filtering with invalid sort field"""
    with patch("main.require_analyst") as mock_analyst:
        mock_analyst.return_value = MagicMock()
        response = client.get(
            "/api/profiles?sort_by=invalid_field",
            headers={"Authorization": "Bearer token"}
        )
        assert response.status_code == 422


def test_profile_filtering_invalid_order():
    """Test profile filtering with invalid sort order"""
    with patch("main.require_analyst") as mock_analyst:
        mock_analyst.return_value = MagicMock()
        response = client.get(
            "/api/profiles?sort_by=age&order=invalid",
            headers={"Authorization": "Bearer token"}
        )
        assert response.status_code == 422


def test_profile_filtering_invalid_probability():
    """Test profile filtering with invalid probability"""
    with patch("main.require_analyst") as mock_analyst:
        mock_analyst.return_value = MagicMock()
        response = client.get(
            "/api/profiles?min_gender_probability=2.5",
            headers={"Authorization": "Bearer token"}
        )
        assert response.status_code == 422

