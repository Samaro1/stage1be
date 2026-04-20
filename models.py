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

# id                     UUID v7            Primary key
# name                   VARCHAR + UNIQUE   Person's full name
# gender                 VARCHAR            "male" or "female"
# gender_probability     FLOAT              Confidence score
# age                    INT                Exact age
# age_group              VARCHAR            child, teenager, adult, senior
# country_id             VARCHAR(2)         ISO code (NG, BJ, etc.)
# country_name           VARCHAR            Full country name
# country_probability    FLOAT              Confidence score
# created_at             TIMESTAMP          Auto-generated