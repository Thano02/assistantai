#!/usr/bin/env python3
"""
Crée ou promeut un compte superadmin. Non-interactif, utilisable sur Railway.

Usage:
    python scripts/create_admin.py <email> <password>
    python scripts/create_admin.py <email> <password> "Nom Admin"
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, init_db, create_business, get_business_by_email, update_business
from services.auth_service import hash_password


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/create_admin.py <email> <password> [nom]")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else "SuperAdmin"

    init_db()
    db = SessionLocal()
    try:
        existing = get_business_by_email(db, email)
        if existing:
            update_business(db, existing.id,
                            is_superadmin=True,
                            email_verified=True,
                            subscription_paid=True)
            print(f"✅ {email} promu superadmin")
        else:
            business = create_business(
                db,
                name=name,
                owner_email=email,
                password_hash=hash_password(password),
                plan="enterprise",
            )
            update_business(db, business.id,
                            is_superadmin=True,
                            email_verified=True,
                            subscription_paid=True)
            print(f"✅ Compte superadmin créé : {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
