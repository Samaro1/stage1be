import csv
import io
import logging
import time
from typing import Dict, Any
from models import Profile
from uuid6 import uuid7

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1000

VALID_GENDERS = {"male", "female"}

EXPECTED_COLUMNS = {
    "name",
    "gender",
    "gender_probability",
    "age",
    "age_group",
    "country_id",
    "country_name",
    "country_probability",
}

VALID_AGE_GROUPS = {"child", "teenager", "adult", "senior"}


def _derive_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    elif age <= 19:
        return "teenager"
    elif age <= 59:
        return "adult"
    return "senior"


def _validate_row(row: dict) -> tuple[dict | None, str | None]:
    """
    Validate and coerce a raw CSV row dict.
    Returns (cleaned_data, None) on success or (None, reason_key) on failure.
    """

    # Required string fields
    name = row.get("name", "").strip().lower()
    gender = row.get("gender", "").strip().lower()
    age_group = row.get("age_group", "").strip().lower()
    country_id = row.get("country_id", "").strip().upper()
    country_name = row.get("country_name", "").strip()

    if not name or not gender or not age_group or not country_id or not country_name:
        return None, "missing_fields"

    # Gender
    if gender not in VALID_GENDERS:
        return None, "invalid_gender"

    # Age
    try:
        age = int(row.get("age", "").strip())
        if age < 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return None, "invalid_age"

    # Age group
    # Accept what's in the CSV if valid, otherwise derive it from age.
    # This tolerates minor inconsistencies in the file.
    if age_group not in VALID_AGE_GROUPS:
        age_group = _derive_age_group(age)

    #Probabilities
    try:
        gender_probability = float(row.get("gender_probability", "").strip())
        if not 0.0 <= gender_probability <= 1.0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return None, "invalid_gender_probability"

    try:
        country_probability = float(row.get("country_probability", "").strip())
        if not 0.0 <= country_probability <= 1.0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return None, "invalid_country_probability"

    return {
        "name": name,
        "gender": gender,
        "gender_probability": gender_probability,
        "age": age,
        "age_group": age_group,
        "country_id": country_id,
        "country_name": country_name,
        "country_probability": country_probability,
    }, None


async def ingest_csv(file) -> Dict[str, Any]:
    """
    Stream-parse a CSV upload and bulk-insert profiles in chunks.

    Expected columns:
        name, gender, gender_probability, age, age_group,
        country_id, country_name, country_probability

    A single bad row never fails the entire upload.
    Already-inserted rows are kept if processing fails midway.
    """

    start_time = time.perf_counter()

    def _response(payload: dict[str, Any]) -> dict[str, Any]:
        payload["duration_seconds"] = round(time.perf_counter() - start_time, 3)
        if payload.get("status") == "success":
            logger.info(
                "CSV upload completed: total_rows=%d inserted=%d skipped=%d duration=%.3f seconds",
                payload.get("total_rows", 0),
                payload.get("inserted", 0),
                payload.get("skipped", 0),
                payload["duration_seconds"],
            )
        else:
            logger.warning(
                "CSV upload failed: %s duration=%.3f seconds",
                payload.get("message"),
                payload["duration_seconds"],
            )
        return payload

    total_rows = 0
    inserted = 0
    skipped = 0

    reasons: dict[str, int] = {
        "duplicate_name": 0,
        "missing_fields": 0,
        "malformed_row": 0,
        "invalid_age": 0,
        "invalid_gender": 0,
        "invalid_gender_probability": 0,
        "invalid_country_probability": 0,
    }

    # Read bytes once and decode.
    #    ~20-80 MB for 500k rows — acceptable.
    #   ORM objects are only created for valid rows
    content = await file.read()
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        decoded = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(decoded))

    # Validate headers exist before processing any rows.
    if reader.fieldnames is None:
        return _response({
            "status": "error",
            "message": "CSV file is empty or missing headers",
        })

    actual_columns = {col.strip().lower() for col in reader.fieldnames}
    missing_columns = EXPECTED_COLUMNS - actual_columns
    if missing_columns:
        return _response({
            "status": "error",
            "message": f"Missing required columns: {', '.join(sorted(missing_columns))}",
        })

    # 3. Pre-load all existing names into a set for duplicate checks, else every row would require a DB query.
    existing_names = set(
        await Profile.all().values_list("name", flat=True)
    )

    # Tracks names added during this upload to catch intra-file duplicates
    seen_in_file: set[str] = set()

    batch: list[Profile] = []

    # 4. Parse, validate, and chunk-insert.
    for raw_row in reader:
        total_rows += 1

        # Normalise keys in case there's extra whitespace in the header
        row = {k.strip().lower(): v for k, v in raw_row.items() if k}

        # Structural check — DictReader sets missing values to None
        if any(v is None for v in row.values()):
            skipped += 1
            reasons["malformed_row"] += 1
            continue

        data, reason = _validate_row(row)
        if reason:
            skipped += 1
            reasons[reason] += 1
            continue

        assert data is not None

        name = data["name"]  # already normalised inside _validate_row

        # Duplicate check — DB + intra-file
        if name in existing_names or name in seen_in_file:
            skipped += 1
            reasons["duplicate_name"] += 1
            continue

        seen_in_file.add(name)

        batch.append(
            Profile(
                id=uuid7(),
                name=name,
                gender=data["gender"],
                gender_probability=data["gender_probability"],
                age=data["age"],
                age_group=data["age_group"],
                country_id=data["country_id"],
                country_name=data["country_name"],
                country_probability=data["country_probability"],
            )
        )

        if len(batch) >= CHUNK_SIZE:
            count = await _flush_batch(batch, reasons)
            inserted += count
            skipped += len(batch) - count
            batch.clear()

    # Flush remainder
    if batch:
        count = await _flush_batch(batch, reasons)
        inserted += count
        skipped += len(batch) - count

    return _response({
        "status": "success",
        "total_rows": total_rows,
        "inserted": inserted,
        "skipped": skipped,
        "reasons": {k: v for k, v in reasons.items() if v > 0},
    })


async def _flush_batch(batch: list[Profile], reasons: dict) -> int:
    """
    Attempt bulk_create for the batch.
    Falls back to individual inserts if bulk fails (e.g. concurrent duplicate).
    Returns the number of successfully inserted rows.
    """
    try:
        await Profile.bulk_create(batch, ignore_conflicts=True)
        return len(batch)
    except TypeError:
        # Tortoise version doesn't support ignore_conflicts, fall back
        pass
    except Exception:
        pass

    # Fallback: one-by-one so a single conflict doesn't lose the whole chunk
    success = 0
    for profile in batch:
        try:
            await Profile.create(
                id=profile.id,
                name=profile.name,
                gender=profile.gender,
                gender_probability=profile.gender_probability,
                age=profile.age,
                age_group=profile.age_group,
                country_id=profile.country_id,
                country_name=profile.country_name,
                country_probability=profile.country_probability,
            )
            success += 1
        except Exception:
            reasons["duplicate_name"] += 1

    return success