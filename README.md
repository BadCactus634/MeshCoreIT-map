# 🌍 Mappa Interattiva Nodi MeshCore Italiani

[![Licenza](https://img.shields.io/badge/Licenza-MIT-green.svg)](LICENSE)
[![Versione](https://img.shields.io/badge/Versione-3.1.0-blue.svg)](https://github.com/BadCactus634/LoRaBS-map)

Mappa nazionale dei nodi **MeshCore** in Italia. Questo progetto permette di visualizzare su mappa tutti i nodi registrati, filtrare per frequenza, cercare singoli nodi e accedere a statistiche amministrative.

## Funzionalità principali

- Visualizzazione dei nodi su mappa interattiva con clustering
- Filtri per frequenza e altri parametri dei nodi
- Ricerca rapida dei nodi per nome
- Statistiche per gli admin:
  - Numero totale di marker
  - Utenti unici
  - Marker con link
  - Top contributor
  - Utenti speciali
- Popup dettagliati per ogni nodo con link e informazioni utente


## Struttura del progetto
```bash
meshcore-it-map/
├── shared/
    └── dati.csv # File CSV con i nodi condiviso tra bot e web
├── web/ # Codice frontend
├── bot/
├── Dockerfile.web
├── Dockerfile.bot
└── docker-compose.yml

```

## Integrazione Bot Telegram
Il codice include un bot Telegram per inserire i nodi nella mappa con funzionalità di aggiunta, modifica e rimozione marker. Ogni utente normale può inserire al massimo 6 marker.

### Funzionalità principali

- ✅ Aggiungi nuovi marker con coordinate, nome, descrizione e link
- ✏️ Rinomina marker esistenti
- 🗑️ Elimina marker
- 📍 Visualizza la lista dei tuoi marker
- 📊 Statistiche e comandi per admin
- 🔒 Controllo degli accessi e limiti per utente


## Tecnologie utilizzate

- **Frontend**
  - HTML/CSS/JS
  - [Leaflet.js](https://leafletjs.com/) per mappe interattive
  - [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) per il clustering dei marker
- **Backend**
  - Python 3
  - [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) per il bot Telegram
- **Docker**
  - Contenitori separati per `web` e `bot` con volumi condivisi

---

## Installazione e avvio

### Con Docker Compose

```bash
git clone https://github.com/BadCactus634/MeshCoreIT-map.git
cd MeshCoreIT-map
docker compose build
docker compose up -d
```

## Configurazione

Bot Telegram: impostare BOT_TOKEN come variabile d'ambiente.

Admin: definire gli ID degli admin in ADMIN_IDS.

Utenti speciali: definire gli ID in SPECIAL_USERS.

File CSV nodi: /shared/dati.csv contiene tutti i nodi registrati.



