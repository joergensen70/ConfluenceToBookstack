#!/usr/bin/env python3
"""
Launcher für confluence_to_bookstack_migration_v2.py
Enthält automatischen Retry für Windows-Import-Probleme
"""
import subprocess
import sys
import time

def main():
    """Startet das Migrations-Skript mit automatischem Retry"""
    max_attempts = 2
    script = "confluence_to_bookstack_migration_v2.py"
    
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"⚠ Windows-Import-Problem erkannt, wiederhole Versuch ({attempt}/{max_attempts})...", file=sys.stderr)
            time.sleep(10)  # 10 Sekunden Wartezeit für File-Locks (Windows braucht das)
        
        # Starte das Migrations-Skript als Subprozess
        result = subprocess.run(
            [sys.executable, script] + sys.argv[1:],
            capture_output=False
        )
        
        # Bei Erfolg oder letztem Versuch: Exit mit dem Return Code
        if result.returncode == 0 or attempt == max_attempts:
            sys.exit(result.returncode)

if __name__ == "__main__":
    main()
