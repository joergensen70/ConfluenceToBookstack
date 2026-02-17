# Confluence to BookStack Migration - Requirements

## Purpose
Migrate Confluence Cloud spaces into BookStack while preserving structure, content, and images, and provide reliable verification.

## Core Requirements
- Confluence API connectivity check command.
- BookStack API connectivity check command.
- Ability to list all Confluence space keys.
- Command to generate a structure preview as Markdown with content samples.
- Migration that transfers structure and content in one run.
- Post-migration verification of completeness and structure.
- Images and tables must be preserved.
- Deterministic verification using Confluence ID markers.

## Key Commands

### 1) Test APIs
```
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --test-apis
```

### 2) List all Confluence spaces
```
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --list-spaces
```

### 3) Preview structure (Markdown)
```
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --preview-structure --spaces CN
```
Optional custom file:
```
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --preview-structure --spaces CN --preview-file my_preview.md
```

### 4) Migrate all spaces in one command
Option A (explicit list):
```
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --spaces SPACE1,SPACE2,SPACE3 --yes
```

Option B (from .env):
```
CONFLUENCE_SPACE_KEYS=SPACE1,SPACE2,SPACE3
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --yes
```

### 5) Verify structure
```
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --check-only --spaces CN
```

### 6) Verify using Confluence ID markers (most reliable)
```
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --verify-ids --spaces CN
```
Report file:
```
confluence_id_verify_report.json
```

### 7) Cleanup duplicates (if needed)
```
& .\.venv\Scripts\python.exe .\confluence_to_bookstack_migration.py --cleanup-duplicates --shelf-name "Confluence Migration (isolated)" --yes
```
Report file:
```
duplicate_cleanup_report.json
```

## Dependencies
- Python 3.10+
- requests

Install via:
```
.\install.ps1
```

## Notes
- The migration adds a small footer line with the Confluence page ID to make verification deterministic.
- External images may fail with 422 if the remote host blocks downloads or if BookStack rejects the upload.
