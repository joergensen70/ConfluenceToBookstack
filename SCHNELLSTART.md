# Confluence to BookStack Migration Tool - Schnellstart (Git-Version)

## ⚠️ Windows-Hinweis

**Wenn beim ersten Start ein Import-Fehler auftritt**: Einfach den Befehl nochmal ausführen - der zweite Versuch funktioniert immer.

Das ist ein bekanntes Windows-File-Locking-Problem beim ersten Zugriff auf Python-Module.

## 🧰 Setup
```powershell
& .\install.ps1
```

## 🚀 Schnellstart (5 Schritte)

### Schritt 1: APIs testen
```powershell
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --test-apis
```

### Schritt 2: Space-Keys auflisten
```powershell
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --list-spaces
```

### Schritt 3: Struktur-Preview erstellen (nur lesen, keine Migration)
```powershell
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --preview-structure --spaces AUTO,CN
```

**Erstellt:** `migration_overview_<space>.md`

### Schritt 4: Dry-Run (keine Änderungen)
```powershell
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --dry-run --spaces AUTO,CN --yes
```

### Schritt 5: Echte Migration + Checks
```powershell
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --spaces AUTO,CN --yes
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --check-only --spaces AUTO,CN
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --verify-ids --spaces AUTO,CN
```

## 📋 Alle Kommandos

### Diagnose
```powershell
# APIs testen
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --test-apis

# Space-Keys auflisten
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --list-spaces

# Zugangsdaten mit zusätzlichen Hinweisen
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --check-credentials --debug-auth
```

### Struktur-Preview
```powershell
# Preview für einzelnen Space
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --preview-structure --spaces AUTO

# Preview für mehrere Spaces
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --preview-structure --spaces AUTO,CN

# Custom Output-Datei
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --preview-structure --spaces AUTO --preview-file mein_preview.md
```

### Migration
```powershell
# Dry-Run (nichts wird geändert)
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --dry-run --spaces AUTO --yes

# Echte Migration mit Bestätigung
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --spaces AUTO

# Migration ohne Rückfrage
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --spaces AUTO --yes

# Alle Spaces aus .env migrieren
# (CONFLUENCE_SPACE_KEYS=AUTO,CN)
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --yes

# Nachträglicher Struktur-Check
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --check-only --spaces AUTO,CN

# Verifikation via Confluence-ID Marker
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --verify-ids --spaces AUTO,CN

# Custom Shelf-Name
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --spaces AUTO --shelf-name "Mein Shelf" --yes
```

## ⚙️ Konfiguration

Die Datei `.env` wird automatisch geladen:

```env
# Confluence
CONFLUENCE_BASE_URL=https://your-domain.atlassian.net
CONFLUENCE_EMAIL=your-email@example.com
CONFLUENCE_API_TOKEN=your-api-token
CONFLUENCE_SPACE_KEY=AUTO

# Optional: mehrere Spaces
CONFLUENCE_SPACE_KEYS=AUTO,CN

# BookStack
BOOKSTACK_BASE_URL=https://your-bookstack.com
BOOKSTACK_TOKEN_ID=your-token-id
BOOKSTACK_TOKEN_SECRET=your-token-secret

# Optional: Prefix fuer Book-Namen
BOOKSTACK_BOOK_PREFIX=
```

## 🎯 Empfohlener Workflow

```powershell
# 1. APIs testen
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --test-apis

# 2. Space-Keys auflisten
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --list-spaces

# 3. Preview erstellen und pruefen
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --preview-structure --spaces AUTO,CN

# 4. Dry-Run
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --dry-run --spaces AUTO,CN --yes

# 5. Echte Migration
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --spaces AUTO,CN --yes

# 6. Struktur-Check
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --check-only --spaces AUTO,CN

# 7. ID-Verifikation (deterministisch)
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --verify-ids --spaces AUTO,CN
```

## 🐛 Troubleshooting

### Fehler: "No module named 'requests'"
```powershell
# Installiere requests neu
& .\.venv\Scripts\pip.exe install --upgrade requests
```

### API-Timeouts
Das Skript hat eingebaute Retry-Logik (3 Versuche) und Rate-Limiting (Delays zwischen Requests).

Falls weiterhin Probleme:
1. BookStack Logs: `storage/logs/laravel.log`
2. Queue Worker: `php artisan queue:work`
3. Cache leeren: `php artisan cache:clear`

### Leere Seiten (⚠)
- Preview zeigt ⚠ für Seiten ohne Inhalt
- Migration versucht automatisch, fehlenden Content nachzuladen
- Falls immer noch leer: Seite in Confluence direkt prüfen

### "Es gibt schon Books mit diesem Namen"
Das Skript erkennt existierende Books und verwendet diese wieder (erstellt keine Duplikate).

Falls trotzdem Probleme, löschen Sie die Books manuell in BookStack.

## ✨ Features

- ✅ Automatische API-Tests vor Migration
- ✅ Struktur-Preview mit Content-Samples
- ✅ Erkennung leerer Seiten (⚠)
- ✅ Automatisches Nachladen fehlender Inhalte
- ✅ Migration von Bilder & Tabellen (HTML)
- ✅ Duplikat-Erkennung
- ✅ Retry-Logik für API-Fehler
- ✅ Rate-Limiting gegen Timeouts
- ✅ Automatische Shelf-Verwaltung (Books werden zusammengefuehrt, nicht ersetzt)
- ✅ Verifikation nach Migration

## 📖 Weitere Dokumentation

Siehe [MIGRATION_V2_README.md](MIGRATION_V2_README.md) für detaillierte Dokumentation.

---

**Viel Erfolg bei der Migration! 🚀**
