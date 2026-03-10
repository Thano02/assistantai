#!/usr/bin/env python3
"""
CLI script to promote an existing account to super admin.

Usage:
    python scripts/create_superadmin.py admin@example.com
    python scripts/create_superadmin.py admin@example.com --revoke
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, get_business_by_email, update_business, init_db


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/create_superadmin.py <email> [--revoke]")
        sys.exit(1)

    email = sys.argv[1]
    revoke = "--revoke" in sys.argv

    init_db()
    db = SessionLocal()
    try:
        business = get_business_by_email(db, email)
        if not business:
            print(f"❌ No account found with email: {email}")
            sys.exit(1)

        new_value = not revoke
        update_business(db, business.id, is_superadmin=new_value)

        action = "revoked from" if revoke else "granted to"
        print(f"✅ Super admin access {action}: {business.name} ({email})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
