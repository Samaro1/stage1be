from tortoise.models import Model
from tortoise import fields

class Profile(Model):
    id = fields.UUIDField(pk=True)
    name = fields.CharField(max_length=255, unique=True)
    gender = fields.CharField(max_length=50)
    gender_probability = fields.FloatField()
    age = fields.IntField()
    age_group = fields.CharField(max_length=20)
    country_id = fields.CharField(max_length=2)
    country_name = fields.CharField(max_length=255)
    country_probability = fields.FloatField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "profiles"


class Users(Model):
    id = fields.UUIDField(pk=True)
    github_id = fields.CharField(max_length=255, unique=True)
    username = fields.CharField(max_length=255)
    email = fields.CharField(max_length=255, null=True)
    avatar_url = fields.CharField(max_length=255, null=True)
    role = fields.CharField(max_length=50, default="analyst")
    is_active = fields.BooleanField(default=True)
    last_login_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "users"

class RefreshToken(Model):
    id = fields.UUIDField(pk=True)
    user = fields.ForeignKeyField("models.Users", related_name="refresh_tokens")
    token = fields.CharField(max_length=512, unique=True)
    is_revoked = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField()

    class Meta:
        table = "refresh_tokens"