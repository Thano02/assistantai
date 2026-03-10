#!/usr/bin/env python3
"""
Script de configuration initiale de la base de données.
Crée les tables et un compte superadmin.

Usage:
    python scripts/setup_db.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, init_db, create_business, get_business_by_email, update_business
from services.auth_service import hash_password


def main():
    print("=== AssistantAI — Setup base de données ===\n")

    # 1. Créer les tables
    print("1. Initialisation des tables SQLite...")
    init_db()
    print("   ✅ Tables créées (robot_rdv.db)\n")

    # 2. Infos du compte admin
    print("2. Création du compte superadmin")
    email = input("   Email admin : ").strip()
    if not email:
        print("   ❌ Email requis")
        sys.exit(1)

    password = input("   Mot de passe (min 8 car.) : ").strip()
    if len(password) < 8:
        print("   ❌ Mot de passe trop court")
        sys.exit(1)

    business_name = input("   Nom du commerce : ").strip() or "Mon Commerce"

    # 3. Créer ou récupérer le compte
    db = SessionLocal()
    try:
        existing = get_business_by_email(db, email)
        if existing:
            print(f"\n   ℹ️  Compte existant trouvé : {existing.name}")
            update_business(db, existing.id,
                            is_superadmin=True,
                            email_verified=True,
                            plan="enterprise")
            print("   ✅ Promu superadmin + email vérifié\n")
        else:
            business = create_business(
                db,
                name=business_name,
                owner_email=email,
                password_hash=hash_password(password),
                plan="enterprise",
            )
            update_business(db, business.id,
                            is_superadmin=True,
                            email_verified=True)
            print(f"\n   ✅ Compte créé : {business.name} (id={business.id})")
            print("   ✅ Superadmin activé + email vérifié\n")
    finally:
        db.close()

    print("=== Setup terminé ===")
    print("\nDémarrer l'app :")
    print("   python main.py")
    print("\nOuvrir dans le navigateur :")
    print("   http://localhost:8000")
    print(f"   Login : {email}")
