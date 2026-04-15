from tortoise.models import Model
from tortoise import fields

class Profile(Model):
    id = fields.UUIDField(pk=True)
    name = fields.CharField(max_length=255, unique=True)
    gender = fields.CharField(max_length=50)
    gender_probability = fields.FloatField()
    sample_size = fields.IntField()
    age = fields.IntField()
    age_group = fields.CharField(max_length=20)
    country_id = fields.CharField(max_length=10)
    country_probability = fields.FloatField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "profiles"