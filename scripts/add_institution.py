"""Create an institution and print its random API key exactly once."""
import argparse
import hashlib
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Institution display name")
    parser.add_argument("--code", required=True, help="Short institution code (stored uppercase)")
    args = parser.parse_args()
    name = args.name.strip()
    code = args.code.strip().upper()
    if not name or len(name) > 200:
        parser.error("--name must contain 1 to 200 characters")
    if not re.fullmatch(r"[A-Z0-9_-]{2,40}", code):
        parser.error("--code must be 2-40 letters, digits, '_' or '-'")

    from sqlalchemy.exc import IntegrityError
    from app.db.database import SessionLocal, init_dev_db
    from app.models.models import Institution

    init_dev_db()
    key = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        db.add(Institution(name=name, code=code,
                           api_key_hash=hashlib.sha256(key.encode("utf-8")).hexdigest()))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SystemExit("Institution code or generated key already exists; no key was issued.") from exc
    finally:
        db.close()
    print(f"Institution created: {name} ({code})")
    print("API key (shown once; store securely):")
    print(key)


if __name__ == "__main__":
    main()
