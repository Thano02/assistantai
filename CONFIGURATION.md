# Configuration — Robot RDV

Guide complet pour configurer et lancer le robot vocal de réservation.

---

## 1. Prérequis

- Python 3.11+
- Un compte Twilio (https://twilio.com)
- Un compte OpenAI avec accès GPT-4o (https://platform.openai.com)
- Un compte ElevenLabs (https://elevenlabs.io)
- *(Optionnel)* Un projet Google Cloud pour Google Calendar

---

## 2. Installation locale

```bash
# Cloner / ouvrir le dossier du projet
cd robot-rdv

# Créer l'environnement virtuel
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# Installer les dépendances
pip install -r requirements.txt

# Copier le fichier d'environnement
cp .env.example .env
```

---

## 3. Obtenir les clés API

### Twilio
1. Créer un compte sur https://console.twilio.com
2. Acheter un numéro de téléphone français (+33...)
   - Dans la console : **Phone Numbers → Buy a number → France → Voice**
3. Copier **Account SID** et **Auth Token** depuis le dashboard principal
4. Renseigner dans `.env` :
   ```
   TWILIO_ACCOUNT_SID=ACxxxxxxxx
   TWILIO_AUTH_TOKEN=xxxxxxxx
   TWILIO_PHONE_NUMBER=+33XXXXXXXXX
   ```

### OpenAI
1. Aller sur https://platform.openai.com/api-keys
2. Créer une clé API
3. Renseigner dans `.env` :
   ```
   OPENAI_API_KEY=sk-xxxxxxxx
   ```

### ElevenLabs
1. Créer un compte sur https://elevenlabs.io
2. Aller dans **Profile → API Key** pour copier la clé
3. Choisir une voix française :
   - Aller dans **Voice Lab** ou **Voice Library**
   - Rechercher des voix françaises (ex: "Charlotte", "Freya", "Callum")
   - Copier le **Voice ID** depuis l'URL ou les paramètres de la voix
4. Renseigner dans `.env` :
   ```
   ELEVENLABS_API_KEY=xxxxxxxx
   ELEVENLABS_VOICE_ID=xxxxxxxx
   ```

   > **Conseil** : La voix `pNInz6obpgDQGcFmaJgB` (Adam) supporte le français avec `eleven_multilingual_v2`. Pour une voix féminine française naturelle, utilisez la Voice Library et filtrez par langue FR.

---

## 4. Configurer votre commerce

Modifier le fichier `business_config.json` :

```json
{
  "name": "Votre Salon",
  "address": "Votre adresse complète",
  "phone": "+33XXXXXXXXX",
  "timezone": "Europe/Paris",
  "services": [
    { "name": "Coupe homme", "duration": 30, "price": 25 }
  ],
  "working_hours": {
    "monday":    { "open": "09:00", "close": "19:00" },
    "tuesday":   { "open": "09:00", "close": "19:00" },
    "sunday":    null
  },
  "slot_interval_minutes": 15
}
```

- `duration` : durée du service en **minutes**
- `slot_interval_minutes` : intervalle entre créneaux (15 ou 30 recommandé)
- `null` pour les jours fermés

---

## 5. Exposition publique (Twilio a besoin d'une URL HTTPS)

### En développement : ngrok

```bash
# Installer ngrok : https://ngrok.com/download
ngrok http 8000
```

ngrok affiche une URL du type `https://abc123.ngrok-free.app` — copier cette URL dans `.env` :
```
BASE_URL=https://abc123.ngrok-free.app
```

### En production : Railway

1. Créer un projet Railway depuis https://railway.app
2. Connecter votre repo GitHub ou déployer via CLI :
   ```bash
   npm install -g @railway/cli
   railway login
   railway up
   ```
3. Ajouter les variables d'environnement dans l'interface Railway
4. Railway vous donne une URL publique (ex: `https://robot-rdv.up.railway.app`)
5. Mettre à jour `BASE_URL` avec cette URL

---

## 6. Configurer Twilio pour les appels

### Webhook appel vocal
1. Dans la console Twilio : **Phone Numbers → Manage → Active numbers**
2. Cliquer sur votre numéro
3. Dans **Voice & Fax** :
   - **A call comes in** → Webhook → `https://VOTRE_URL/voice/incoming`
   - Méthode : **POST**
   - **Call status changes** → `https://VOTRE_URL/voice/end`

### Webhook SMS entrant
1. Toujours sur la page du numéro
2. Dans **Messaging** :
   - **A message comes in** → Webhook → `https://VOTRE_URL/sms/incoming`
   - Méthode : **POST**

---

## 7. Google Calendar (optionnel)

Pour synchroniser les RDV avec un agenda Google :

### Créer les credentials
1. Aller sur https://console.cloud.google.com
2. Créer un projet (ou en sélectionner un existant)
3. Activer l'API **Google Calendar API**
4. Créer des identifiants **OAuth 2.0** (type : Desktop App)
5. Télécharger le fichier JSON → le renommer `credentials.json` et le placer à la racine du projet

### Configurer le calendrier cible
1. Ouvrir Google Calendar
2. Aller dans les paramètres du calendrier souhaité
3. Copier l'**ID du calendrier** (ressemble à `xxx@gmail.com` ou `xxx@group.calendar.google.com`)
4. Renseigner dans `.env` :
   ```
   GOOGLE_CALENDAR_ID=votre-calendrier@gmail.com
   GOOGLE_CREDENTIALS_FILE=credentials.json
   ```

### Première authentification
Au premier lancement, une fenêtre s'ouvrira pour autoriser l'accès. Un fichier `token.pickle` sera créé pour les lancements suivants.

---

## 8. Lancer le serveur

```bash
# Variables d'environnement chargées depuis .env
python main.py

# Ou avec uvicorn directement
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Le serveur démarre sur `http://localhost:8000`.

Documentation API interactive : `http://localhost:8000/docs`

---

## 9. Clé admin pour l'API

Ajouter dans `.env` :
```
ADMIN_API_KEY=votre_cle_secrete_ici
```

Accès à l'API admin (voir réservations, stats) :
```bash
# Réservations du jour
curl -H "x-api-key: votre_cle" https://VOTRE_URL/admin/reservations/today

# Statistiques
curl -H "x-api-key: votre_cle" https://VOTRE_URL/admin/stats
```

---

## 10. Architecture des fichiers

```
robot-rdv/
├── main.py                    # Point d'entrée FastAPI
├── config.py                  # Variables d'environnement
├── database.py                # Modèles SQLAlchemy + CRUD
├── business_config.json       # Configuration du commerce ← À MODIFIER
├── requirements.txt
├── Dockerfile
├── .env                       # Variables secrètes ← À CRÉER
├── services/
│   ├── ai_service.py          # GPT-4o + gestion conversation
│   ├── tts_service.py         # ElevenLabs text-to-speech
│   ├── sms_service.py         # Twilio SMS (confirmations + rappels)
│   ├── slots_service.py       # Calcul des créneaux disponibles
│   ├── calendar_service.py    # Google Calendar (optionnel)
│   └── scheduler_service.py   # Tâches automatiques (rappels SMS)
├── routers/
│   ├── voice.py               # Webhooks appels vocaux Twilio
│   ├── sms_webhook.py         # Webhook SMS entrant (ANNULER)
│   └── admin.py               # API d'administration
└── static/
    └── audio/                 # Fichiers audio générés (ElevenLabs)
```

---

## 11. Flux d'un appel

```
Client appelle le numéro Twilio
        ↓
Twilio → POST /voice/incoming
        ↓
Identification client (DB) → Message d'accueil personnalisé (ElevenLabs)
        ↓
Twilio joue l'audio + attend la parole (<Gather speech>)
        ↓
Client parle → Twilio transcrit (Google STT, fr-FR)
        ↓
POST /voice/process avec SpeechResult
        ↓
GPT-4o analyse + appelle les outils nécessaires :
  - get_client_info → historique client
  - check_available_slots → créneaux libres
  - create_reservation / modify / cancel
  - end_call → fin de conversation
        ↓
ElevenLabs génère l'audio de la réponse
        ↓
Twilio joue + attend la prochaine parole
        ↓ (quand end_call)
SMS de confirmation envoyé automatiquement
Raccrocher
```

---

## 12. SMS automatiques

| Événement | SMS envoyé |
|-----------|-----------|
| Réservation créée | Confirmation avec date, service, adresse |
| Réservation modifiée | Nouvelle confirmation |
| 24h avant le RDV | Rappel avec option d'annulation |
| Annulation | Confirmation d'annulation |

Pour annuler par SMS, le client répond :
- `ANNULER 42` → annule la réservation #42
- `ANNULER` → annule la prochaine réservation
- `MES RDV` → liste ses prochains rendez-vous

---

## 13. Outlook / Hotmail

Pour la plupart des petits commerces, **Google Calendar est recommandé**.

Si votre client utilise Outlook :
1. Créer une app Azure sur https://portal.azure.com
2. Activer **Microsoft Graph API** avec `Calendars.ReadWrite`
3. Utiliser la bibliothèque `O365` Python au lieu de `google-api-python-client`

Une implémentation Outlook peut être ajoutée dans `services/calendar_service.py` en suivant la même interface (`create_calendar_event`, `delete_calendar_event`, `update_calendar_event`).

---

## 14. Variables d'environnement — récapitulatif

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `TWILIO_ACCOUNT_SID` | ✅ | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | ✅ | Twilio Auth Token |
| `TWILIO_PHONE_NUMBER` | ✅ | Numéro Twilio au format E.164 |
| `OPENAI_API_KEY` | ✅ | Clé API OpenAI |
| `ELEVENLABS_API_KEY` | ✅ | Clé API ElevenLabs |
| `ELEVENLABS_VOICE_ID` | ✅ | ID de la voix ElevenLabs |
| `BASE_URL` | ✅ | URL publique du serveur (ngrok ou Railway) |
| `DATABASE_URL` | ✅ | SQLite ou PostgreSQL |
| `TIMEZONE` | ✅ | Ex: `Europe/Paris` |
| `ADMIN_API_KEY` | ✅ | Clé secrète pour l'API admin |
| `GOOGLE_CALENDAR_ID` | ❌ | ID calendrier Google |
| `GOOGLE_CREDENTIALS_FILE` | ❌ | Chemin vers credentials.json |
