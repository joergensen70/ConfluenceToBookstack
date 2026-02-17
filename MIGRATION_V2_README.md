# Confluence to BookStack Migration Tool (Legacy)

Hinweis: Diese Datei ist eine historische Beschreibung der alten v2-Variante.
Aktuelle Anleitung und Commands findest du in:
- SCHNELLSTART.md
- REQUIREMENTS.md

**Vollständig überarbeitetes Migrationsskript mit erweiterten Funktionen**

## ✨ Neue Features

### 1. API-Tests
```powershell
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --test-apis
```
- Testet beide APIs (Confluence & BookStack)
- Zeigt Verbindungsstatus und Systeminfo
- **Wird automatisch vor jeder Migration durchgeführt**

### 2. Space-Liste
```powershell
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --list-spaces
```
- Listet alle verfügbaren Confluence Spaces auf
- Zeigt Space-Key, Name und Typ
- Hilft bei der Auswahl der zu migrierenden Spaces

### 3. Struktur-Preview (NEU!)
```powershell
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --preview-structure --spaces AUTO,CN --preview-file preview.md
```
- **Erstellt Markdown-Preview der CompleteStruktur**
- **Zeigt Beispiel-Content für jede Seite**
- **Markiert leere Seiten mit ⚠**
- **Markiert Seiten mit Inhalt mit ✓**
- **MUSS vor der Migration geprüft werden!**

#### Preview-Ausgabe
```markdown
### ✓ Book: Auto
*Beispiel-Inhalt*: Documentation overview Explain the purpose...

#### ⚠ Chapter: Passat
*Beispiel-Inhalt*: (leer)

- ✓ Seite: **Codings**
  - *Content*: Funktion des Regenschließens aktivieren...
- ⚠ Seite: **Handyhalterung**
  - *Content*: (leer)
```

### 4. Vollständige Migration
```powershell
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --spaces AUTO,CN --shelf-name "Confluence Migration" --yes
```
- Migriert alle Spaces in einem Durchlauf
- **Content wird direkt beim Erstellen migriert** (nicht nachträglich)
- Erkennt leere Seiten und lädt fehlenden Content nach
- Bilder und Tabellen werden migriert (HTML-Format)
- Erstellt automatisch Shelf für alle migrierten Books
- Rate-Limiting gegen API-Timeouts

#### Migrations-Features:
- ✓ Hierarchische Struktur: Space → Book → Chapter → Page
- ✓ Content-Validation (erkennt leere Seiten)
- ✓ Automatischer Content-Nachlade (bei fehlenden Daten)
- ✓ Duplikat-Erkennung (existierende Books werden wiederverwendet)
- ✓ Progress-Anzeige mit Status-Icons
- ✓ Retry-Logic für API-Timeouts
- ✓ Rate-Limiting (Delays zwischen Requests)

### 5. Verifikation
```powershell
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --check-only --spaces AUTO,CN
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --verify-ids --spaces AUTO,CN
```
- **Automatische Verifikation nach Migration**
- Vergleicht Strukturshellaus Confluence und BookStack
- Zählt Books, Chapters und Pages
- Meldet Abweichungen in der Anzahl
- Generiert Verifikationsreport

## 📋 Empfohlener Workflow

```powershell
# 1. APIs testen
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --test-apis

# 2. Verfügbare Spaces listen
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --list-spaces

# 3. Struktur-Preview erstellen und PRÜFEN
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --preview-structure --spaces AUTO,CN

# 4. Preview-Datei durchsehen
# → Öffne structure_preview.md
# → Prüfe auf ⚠ (leere Seiten)
# → Prüfe Beispiel-Content

# 5. Migration durchführen
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --spaces AUTO,CN --yes

# 6. Verifikation
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --check-only --spaces AUTO,CN
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --verify-ids --spaces AUTO,CN

# Optional: Dry-Run vorher testen
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --dry-run --spaces AUTO --yes
```

##  Konfiguration (.env)

`CONFLUENCE_SPACE_KEY` ist weiterhin möglich. Für mehrere Spaces nutze `CONFLUENCE_SPACE_KEYS` oder `--spaces`.

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

# Optional
BOOKSTACK_BOOK_PREFIX=
```

## 🔍 Wichtige Änderungen gegenüber v1

| Feature | v1 | v2 |
|---------|----|----|
| API-Tests | Manuell | Automatisch + Kommando |
| Space Konfiguration | In .env | Als Argument (flexibler) |
| Struktur-Preview | Nur Übersicht | Vollständig mit Content-Samples |
| Content-Migration | Nachträglich | Im gleichen Schritt |
| Leere Seiten | Nicht erkannt | Automatisch erkannt + nachgeladen |
| Verifikation | Manuell | Automatisch nach Migration |
| Bilder | Upload nach Page-Erstellung | Im Content migriert |

## 🎯 Status-Icons Legende

- **✓** = Seite hat Inhalt (Text oder Bilder)
- **⚠** = Seite ist leer oder hat keinen erkennbaren Content

## ⚙️ Optionen

### Allgemein
- `--test-apis` - API-Verbindungstests
- `--list-spaces` - Liste Confluence Spaces
- `--preview-structure` - Erstelle Struktur-Preview

### Migration
- `--spaces AUTO,CN` - Zu migrierende Spaces (Komma-getrennt)
- `--shelf-name "Name"` - Name des BookStack Shelfs
- `--yes` - Keine Rückfrage (automatische Bestätigung)
- `--dry-run` - Simulation ohne Änderungen
- `--check-only` - Struktur-Check nach Migration
- `--verify-ids` - Verifikation via Confluence-ID Marker

### Output
- `--preview-file name.md` - Output-Datei für Preview (Standard: migration_overview_<space>.md)

## 🐛 Troubleshooting

### API-Timeouts
Das Skript enthält jetzt:
- Retry-Logik (3 Versuche pro Request)
- Rate-Limiting (Delays zwischen Requests)
- Timeout-Handling

Falls weiterhin Probleme auftreten:
1. BookStack Logs prüfen: `storage/logs/laravel.log`
2. Queue Worker starten: `php artisan queue:work`
3. Cache leeren: `php artisan cache:clear`

### Leere Seiten
- Preview zeigt ⚠ für leere Seiten
- Migration versucht automatisch Content nachzuladen
- Falls immernoch leer: Seite in Confluence prüfen

### Duplikate
- Skript erkennt existierende Books
- Existierende Books werden wiederverwendet (nicht neu erstellt)
- Bei Fehlern: Books manuell löschen vor Migration

## 📊 Migration-Output Beispiel

```
================================================================================
MIGRATION STARTEN
================================================================================

================================================================================
Space 1/2: AUTO
================================================================================

Space Name: Auto

[1/5] Lade Seiten aus AUTO...
  Gefunden: 28 Seiten

[2/5] Analysiere Struktur...
  Top-Level Seiten (Books): 2

[3/5] Erstelle Books und migriere Inhalte...

  [1/2] Book: Passat
      Book erstellt: ID 70
      Chapters: 2
        [1/2] Chapter: Codings ✓ (ID 487)
            Seiten: 2
              [1/2] ✓ DSG Reset VCDS ✓ (ID 1234)
              [2/2] ⚠ Anfahrassistent ✗ (leer)
        [2/2] Chapter: Umbauten ✓ (ID 488)
            Seiten: 5
              [1/5] ✓ Handyhalterung ✓ (ID 1235)
              ...

[4/5] Aktualisiere Shelf 'Confluence Migration'...
  Shelf erstellt: ID 7

[5/5] Space AUTO abgeschlossen!

================================================================================
✓ Migration abgeschlossen: 2 Books migriert
================================================================================
```

## 🎉 Ready to Use!

Das Tool ist vollständig getestet und einsatzbereit. Folgen Sie dem empfohlenen Workflow für beste Ergebnisse!
