# Discord Security & Moderation Bot

Ein vollständiges Produktionssystem für Discord-Sicherheit, Moderation und Analyse.

## Features

- **Eigene KI-Moderation** — kein OpenAI, kein Gemini, keine externe API
- **Dynamisches Trust-System** (0–100) pro Benutzer
- **Risiko-Scoring** (0–100) mit detaillierter Begründung
- **Automatische Moderation** in 4 Stufen (Warnung → Timeout → Timeout++ → Perma-Mute)
- **Vollständige REST API** für Bubble-Integration
- **PostgreSQL** Datenbank mit 16 Tabellen
- **Slash Commands** für Mods und Admins
- **Railway** sofort deploybar

---

## Schnellstart

### 1. Bot auf Discord erstellen

1. Gehe zu https://discord.com/developers/applications
2. Erstelle eine neue Application → Bot → Token kopieren
3. Unter „Privileged Gateway Intents": **alle 3 aktivieren**
4. Bot einladen: `https://discord.com/oauth2/authorize?client_id=DEINE_CLIENT_ID&permissions=8&scope=bot%20applications.commands`

### 2. Lokal ausführen

```bash
cp .env.example .env
# .env ausfüllen (DISCORD_TOKEN, DATABASE_URL, etc.)

pip install -r requirements.txt
python main.py
```

### 3. Mit Docker

```bash
docker build -t discord-bot .
docker run --env-file .env discord-bot
```

---

## Railway Deployment

### Schritt 1: Railway Projekt erstellen

1. https://railway.app → New Project → Deploy from GitHub Repo
2. Dieses Repository verbinden

### Schritt 2: PostgreSQL hinzufügen

1. Im Railway-Projekt: **+ Add Plugin** → **PostgreSQL**
2. Railway setzt `DATABASE_URL` automatisch als Variable

### Schritt 3: Umgebungsvariablen setzen

Im Railway-Dashboard unter **Variables** folgendes eintragen:

| Variable | Wert | Pflicht |
|---|---|---|
| `DISCORD_TOKEN` | Dein Bot-Token | ✅ |
| `DATABASE_URL` | Automatisch von Railway (asyncpg) | ✅ |
| `API_SECRET_KEY` | Mindestens 32 Zeichen, zufällig | ✅ |
| `ADMIN_ROLE_ID` | `1514289625131258048` | ✅ |
| `WHITELIST_ROLE_ID` | `152326964767844359` | ✅ |
| `LOG_CHANNEL_ID` | ID des Log-Kanals | Empfohlen |
| `ALERT_CHANNEL_ID` | ID des Admin-Alert-Kanals | Empfohlen |
| `ALLOWED_ORIGINS` | Deine Bubble-Domain | Empfohlen |
| `PORT` | Automatisch von Railway | — |

> **Wichtig bei Railway:** Die `DATABASE_URL` die Railway bereitstellt ist im `postgresql://` Format.
> Der Bot benötigt `postgresql+asyncpg://`. Railway setzt die Variable automatisch — 
> du musst nichts ändern, da der Code Railway's Variable automatisch konvertiert.
> Füge also zusätzlich eine Variable `DATABASE_URL` mit dem asyncpg-Prefix ein.

### Schritt 4: Deploy

Railway deployt automatisch bei jedem Push. Der Bot startet sofort.

---

## Bubble API-Integration

### Basis-URL
```
https://deine-railway-domain.up.railway.app/api
```

### Authentifizierung

**1. Login (Token erhalten):**
```
POST /api/auth/login
Content-Type: application/json

{
  "guild_id": 123456789,
  "user_id": 987654321,
  "password": "dein_passwort"
}
```

Response:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**2. Token verwenden:**
Alle weiteren Requests brauchen den Header:
```
Authorization: Bearer eyJ...
```

### Moderator registrieren (einmalig)
```
POST /api/auth/register
Content-Type: application/json

{
  "guild_id": 123456789,
  "user_id": 987654321,
  "username": "AdminName",
  "password": "sicheres_passwort",
  "is_admin": true,
  "secret_key": "DEIN_API_SECRET_KEY_AUS_ENV"
}
```

---

## API-Endpunkte

### Dashboard
| Method | Endpoint | Beschreibung |
|---|---|---|
| GET | `/api/dashboard?guild_id=...` | Vollständige Dashboard-Übersicht |
| GET | `/api/stats?guild_id=...&period=24h` | Statistiken (1h/24h/7d/30d) |
| POST | `/api/settings?guild_id=...` | Einstellungen aktualisieren |

### Benutzer
| Method | Endpoint | Beschreibung |
|---|---|---|
| GET | `/api/users?guild_id=...` | Alle Benutzer |
| GET | `/api/users/{user_id}?guild_id=...` | Einzelner Benutzer |
| PATCH | `/api/users/{user_id}?guild_id=...` | Benutzer bearbeiten |
| GET | `/api/users/trust?guild_id=...` | Trust-Scores |
| GET | `/api/users/risk?guild_id=...` | Risiko-Scores |

### Logs & Moderation
| Method | Endpoint | Beschreibung |
|---|---|---|
| GET | `/api/logs?guild_id=...` | Audit-Logs |
| GET | `/api/warnings?guild_id=...` | Verwarnungen |
| POST | `/api/warnings` | Verwarnung erstellen |
| DELETE | `/api/warnings/{id}?guild_id=...` | Verwarnung löschen |
| GET | `/api/timeouts?guild_id=...` | Timeouts |
| POST | `/api/timeouts` | Timeout setzen |
| POST | `/api/ban` | Ban |
| POST | `/api/unban` | Unban |

### Serverinfo
| Method | Endpoint | Beschreibung |
|---|---|---|
| GET | `/api/server?guild_id=...` | Serverdetails |
| GET | `/api/channels?guild_id=...` | Kanalstatistiken |
| GET | `/api/voice?guild_id=...` | Voice-Statistiken |
| GET | `/api/activity?guild_id=...&days=7` | Aktivitätsheatmap |

### Interaktive Dokumentation
```
https://deine-railway-domain.up.railway.app/api/docs
```

---

## Slash Commands

| Command | Beschreibung | Berechtigung |
|---|---|---|
| `/warn @user [grund]` | Verwarnt einen Benutzer | Admin-Rolle |
| `/unwarn [id]` | Entfernt eine Verwarnung | Admin-Rolle |
| `/timeout @user [min] [grund]` | Setzt Timeout | Admin-Rolle |
| `/ban @user [grund]` | Bannt Benutzer | Admin-Rolle |
| `/unban [user_id] [grund]` | Entbannt Benutzer | Admin-Rolle |
| `/history @user` | Moderationshistorie | Admin-Rolle |
| `/trust @user` | Trust-Score anzeigen | Jeder (eigener), Admin (andere) |
| `/risk @user` | Risiko-Score anzeigen | Admin-Rolle |
| `/userstats @user` | Benutzerstatistiken | Jeder (eigene), Admin (andere) |
| `/serverstats` | Serverstatistiken | Admin-Rolle |
| `/scan [text]` | KI-Analyse Text | Admin-Rolle |
| `/logs [limit]` | Audit-Logs | Admin-Rolle |
| `/settings` | Server-Einstellungen | Admin-Rolle |
| `/announce #kanal [nachricht]` | Ankündigung senden | Admin-Rolle |
| `/reload` | Cogs neu laden | Admin-Rolle |
| `/backup` | Backup-Info | Admin-Rolle |
| `/dashboard` | Dashboard-Link | Admin-Rolle |

---

## KI-Moderationssystem

### Erkannte Verstöße
- Spam / Flood
- Caps-Lock-Missbrauch
- Emoji-Spam
- Zeichen-Spam
- Toxische Sprache & Beleidigungen
- Diskriminierung
- Scam-Muster
- Phishing-Links
- Discord-Einladungen (unerlaubt)
- Mass Pings (@everyone/@here)
- Raid-Erkennung (Mass-Joins)
- Neue Accounts
- Verhaltensänderungen / Muster

### Aktionsstufen

| Stufe | Risiko | Aktion |
|---|---|---|
| 0 | < 15 | Keine Aktion |
| 1 | 15–34 | Warnung (DM) |
| 2 | 35–59 | Nachricht löschen + 10 Min Timeout |
| 3 | 60–79 | 1 Std Timeout + Mod-Benachrichtigung |
| 4 | ≥ 80 | **Permanent Mute** (28 Tage Discord-Timeout) + Admin-Benachrichtigung |

> **Stufe 4 = Perma-Mute:** Der Benutzer wird auf 28 Tage gemutet und ein Admin mit der Rolle `1514289625131258048` wird benachrichtigt. Nur ein Admin kann die Situation prüfen und den Mute manuell aufheben.

### Trust-Score
- **Startwert:** 100
- **Steigt:** langsam bei jeder sauberen Nachricht (+0.05)
- **Fällt:** bei Verstößen, Verwarnungen, Timeouts, Perma-Mute
- **Beeinflusst:** KI-Risikoberechnung (niedriger Trust → höheres Risiko)

### Geschützte Rollen
| Rolle | ID | Verhalten |
|---|---|---|
| Admin | `1514289625131258048` | Komplett ausgenommen |
| Whitelist | `152326964767844359` | Komplett ausgenommen |

---

## Datenbankstruktur

16 Tabellen:
- `guilds` — Server
- `users` — Benutzer mit Trust/Risk-Scores
- `channels` — Kanäle mit Statistiken
- `messages` — Alle Nachrichten
- `warnings` — Verwarnungen
- `timeouts` — Timeouts
- `bans` — Bans
- `voice_sessions` — Voice-Aktivität
- `ai_analyses` — KI-Analysen
- `risk_records` — Risikoverlauf
- `audit_logs` — Alle Aktionen
- `server_stats` — Aggregierte Statistiken
- `dashboard_settings` — Konfiguration pro Server
- `moderators` — API-Benutzer (Bubble)

---

## Sicherheitshinweise

- `API_SECRET_KEY` muss mindestens 32 Zeichen lang sein und zufällig generiert werden
- Setze `ALLOWED_ORIGINS` auf deine Bubble-Domain in Produktion
- JWT-Tokens laufen nach 24 Stunden ab
- Moderator-Passwörter werden mit bcrypt gehasht gespeichert
- Bot-Token niemals in Code oder Logs

---

## Lokale Entwicklung

```bash
# Python 3.12+ erforderlich
pip install -r requirements.txt

# PostgreSQL lokal starten (oder Docker)
docker run -d -e POSTGRES_PASSWORD=pass -e POSTGRES_DB=discordbot -p 5432:5432 postgres:16

# .env konfigurieren
cp .env.example .env
# DATABASE_URL=postgresql+asyncpg://postgres:pass@localhost:5432/discordbot

python main.py
```

API-Dokumentation: http://localhost:8000/api/docs
