# Confluence Migrationsübersicht

- Space-Key: `CN`
- Space-Name: `Computer & Netzwerk`
- Ziel-Book in BookStack: `Confluence -Computer & Netzwerk`

## Statistik

- Gesamtseiten im Space: **110**
- Bücher (Top-Level): **10**
- Chapter (Ebene 2): **43**
- Seiten (ab Ebene 3): **56**

## Top-Level Übersicht

- FTP Zugang (Chapter: 0, Seiten unterhalb Chapter: 0)
- Volkszähler (Chapter: 25, Seiten unterhalb Chapter: 34)
- Optional Hostname für myFritz (IPv6 only) (Chapter: 0, Seiten unterhalb Chapter: 0)
- Putty (Chapter: 0, Seiten unterhalb Chapter: 0)
- Moved to bookstack (Chapter: 17, Seiten unterhalb Chapter: 22)
- Outlook 365 winmail.dat Problem (Chapter: 0, Seiten unterhalb Chapter: 0)
- RS485/Modbus Stromzähler an NodeRed (Chapter: 0, Seiten unterhalb Chapter: 0)
- CN Migration Testseite mit Bild 2026-02-16 14:33:13 (Chapter: 0, Seiten unterhalb Chapter: 0)
- Anleitungsartikel (Chapter: 1, Seiten unterhalb Chapter: 0)
- Web Cam (Chapter: 0, Seiten unterhalb Chapter: 0)

## Strukturzuordnung

Format: Buch (oberste Ebene) → Chapter (Ebene darunter) → Seite (darunter)

### Buch: FTP Zugang
- _(Keine Chapter)_

### Buch: Volkszähler
- Chapter: Internet Seiten (Quellen)
  - _(Keine Seiten)_
- Chapter: NAS auf Raspberry mounten
  - _(Keine Seiten)_
- Chapter: 14 Sonstiges
  - _(Keine Seiten)_
- Chapter: Raspberry Pi_ WLAN einrichten (Edimax)
  - Seite: WLAN-Konfiguration unter Raspbian
  - Seite: Verbindung herstellen
- Chapter: 11 SQL Konfiguration
  - Seite: 11.1 SQL Befehle eingeben
- Chapter: Können MariaDB-Einstellungen auf dem Synology NAS angepasst werden?
  - Seite: 11.1.2 Kanal löschen (muss noch etwas besseres geben)_
  - Seite: SELECT * FROM `volkszaehler`.`aggregate` WHERE `aggregate`.`channel_id` = 36
  - Seite: 12 WLAN mit dem Raspberry
- Chapter: 9 Root Passwort vergeben (optional)
  - Seite: 10 Passwort ändern (optional)
- Chapter: 6 Kanäle konfigurieren
  - Seite: 8 Admin Account anlegen (Optional)
- Chapter: 4 Demo Kanäle löschen
  - _(Keine Seiten)_
- Chapter: 5 IP Adresse ändern
  - _(Keine Seiten)_
- Chapter: 3 Partition an genutzte Karte anpassen
  - _(Keine Seiten)_
- Chapter: Neue Anleitung mit Raspberry Erweiterung 2017
  - _(Keine Seiten)_
- Chapter: 1 Volkzaehler Image aufspielen
  - Seite: Zu verwendendes Raspberry Image (Stand 24.09.2015), inklusive Daemon für Raspberry Erweiterung
  - Seite: Übersicht der Standard Passwörter
  - Seite: SD Karte mit SD Formater formatieren
- Chapter: Datenbank verschieben
  - _(Keine Seiten)_
- Chapter: Volkszaehler_VirtuelleKanäle
  - _(Keine Seiten)_
- Chapter: Backup Datenbank mit php-myadmin
  - _(Keine Seiten)_
- Chapter: Restore Datenbank
  - _(Keine Seiten)_
- Chapter: Ebusd Mqtt access
  - _(Keine Seiten)_
- Chapter: EBUSD_OPTS="--device=_dev_ttyUSB0 -p 8888 --scanconfig --accesslevel=* --configpath=_home_pi_ebusd_contrib_etc_ebusd_ --mqtthost=192.168.4.212 --mqttport=1883 --mqtttopic=ebusd_%circuit_%name"
  - _(Keine Seiten)_
- Chapter: Installing node-red
  - Seite: MQTT-Broker “Mosquitto” installieren
- Chapter: Middleware 2 Daten auslesen_
  - Seite: Samba Server einrichten
- Chapter: Automatisches Backup installieren
  - Seite: Daten an Volkszähler senden
  - Seite: Hex Kommandos
  - Seite: NA_15_Vaillant_70000_0613_6903_21_19_36_0020266797_0082_048916_N8
  - Seite: NA_52_Vaillant_VR_70_0109_2903_21_19_34_0020184843_0082_012601_??
  - Seite: 71_76_Vaillant_VWZ00_0307_0403
  - Seite: Kommandos
  - Seite: EBus abfragen
  - Seite: 00_05_Vaillant_VR921_0902_5703_21_19_31_0020260962_0938_016911_N8
  - Seite: 03_08_Vaillant_HMU00_0307_0403_21_19_36_0010016421_0001_005612_N9
  - Seite: EBUSD_OPTS="--device=_dev_ttyUSB0 -p 8888 --scanconfig --accesslevel=* --configpath=_home_pi_ebusd_contrib_etc_ebusd_ --mqtthost=192.168.4.212 --mqttport=1883 --mqtttopic=ebusd_%circuit_%name --enablehex --httpport=8889 --htmlpath=_home_pi_ebusd_contrib_
  - Seite: Konfiguration
  - Seite: USB Device und Port unter Linux ermitteln (Ebus Adapter)
  - Seite: Installieren
  - Seite: Automatisch starten (systemd Service Manager)
  - Seite: EBUSD_OPTS="--device=_dev_ttyUSB0 -p 8888 -l _var_log_ebusd.log --scanconfig --accesslevel=* --httpport=8889 --htmlpath=_home_pi_ebusd_contrib_html --configpath=_home_pi_ebusd_contrib_etc_ebusd_ --mqtthost=192.168.4.212 --mqttport=1883 --mqtttopic=ebusd_
  - Seite: Benötigte Pakete installieren
  - Seite: Sourcen laden
  - Seite: Compilieren
  - Seite: Testen
  - Seite: Ebus Daemon installieren
- Chapter: Middleware Daten auslesen_
  - Seite: VZ Virtuellen Kanal über http erzeugen (private)
- Chapter: 16 Shelly über MQTT und NodeRed
  - _(Keine Seiten)_
- Chapter: 15 ESP Easy Sensoren in Volkszähler einbinden
  - _(Keine Seiten)_

### Buch: Optional Hostname für myFritz (IPv6 only)
- _(Keine Chapter)_

### Buch: Putty
- _(Keine Chapter)_

### Buch: Moved to bookstack
- Chapter: Netzwerkkonfiguration
  - _(Keine Seiten)_
- Chapter: Strato Netzlaufwerk verbinden
  - _(Keine Seiten)_
- Chapter: Reverse Proxy auf Diskstation einrichten
  - _(Keine Seiten)_
- Chapter: Domain einrichten
  - _(Keine Seiten)_
- Chapter: Self Hosted Port Mapper mit 6tunnel Einrichten
  - _(Keine Seiten)_
- Chapter: Konfiguration nach IP Adressen Wechsel updaten
  - _(Keine Seiten)_
- Chapter: Nano Editor installieren
  - _(Keine Seiten)_
- Chapter: SynoCommunity-Repository für Paket Quellen hinzufügen
  - _(Keine Seiten)_
- Chapter: Hyper Backup auf Strato
  - _(Keine Seiten)_
- Chapter: SSL Zertifikat erstellen und installieren
  - _(Keine Seiten)_
- Chapter: Joomla Update
  - _(Keine Seiten)_
- Chapter: Bookstack einrichten
  - _(Keine Seiten)_
- Chapter: Portainer Installieren
  - _(Keine Seiten)_
- Chapter: VPN OpenVPN einrichten
  - _(Keine Seiten)_
- Chapter: RepairDatabaseMariaDB10
  - _(Keine Seiten)_
- Chapter: Linux Befehle
  - Seite: crontab - um automatisch Anwendungen zu starten
  - Seite: passwd – Passwort ändern
  - Seite: ps -e – Prozesse anzeigen
  - Seite: df – Speicherplatzbelegung anzeigen
  - Seite: cat – Datei-Inhalt anzeigen
  - Seite: man – Anleitung zum Befehl anzeigen
  - Seite: clear – Terminal räumen
  - Seite: cd – Verzeichnis wechseln
  - Seite: ls – Verzeichnis-Inhalt anzeigen
  - Seite: which – wo ist ein Programm installiert
  - Seite: pwd – wo bin ich
  - Seite: apt-get install Paketname - Pakete von git installieren - (pull)
  - Seite: apt-update - Pakete von git aktualisieren (fetch all)
  - Seite: service
  - Seite: shutdown
  - Seite: ip _ Ifconfig
  - Seite: rm - Files löschen
  - Seite: cp - Dateien Kopieren oder umbenennen
  - Seite: bash - Skripte ausführen
  - Seite: sudo -i
  - Seite: nano
  - Seite: find
- Chapter: nginx Synology Reverse Proxy
  - _(Keine Seiten)_

### Buch: Outlook 365 winmail.dat Problem
- _(Keine Chapter)_

### Buch: RS485/Modbus Stromzähler an NodeRed
- _(Keine Chapter)_

### Buch: CN Migration Testseite mit Bild 2026-02-16 14:33:13
- _(Keine Chapter)_

### Buch: Anleitungsartikel
- Chapter: RS485/MQTT Adapter
  - _(Keine Seiten)_

### Buch: Web Cam
- _(Keine Chapter)_


> Hinweis: Diese Übersicht wird vor jeder Migration erstellt. Bitte erst prüfen, dann bestätigen.
