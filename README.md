# MeshCoreIT-map

Mappa nazionale dei nodi **MeshCore** in Italia. Questo progetto permette di visualizzare su mappa tutti i nodi registrati, filtrare per frequenza, cercare singoli nodi e accedere a statistiche amministrative.

---

## Funzionalità principali

- Visualizzazione dei nodi su mappa interattiva con clustering.
- Filtri per frequenza e altri parametri dei nodi.
- Ricerca rapida dei nodi per nome.
- Statistiche per gli admin:
  - Numero totale di marker
  - Utenti unici
  - Marker con link
  - Top contributor
  - Utenti speciali
- Aggiornamento automatico dei dati.
- Popup dettagliati per ogni nodo con link e informazioni utente.

---

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

## Struttura del progetto
```bash
├── Dockerfile.web # Dockerfile per il servizio web
├── Dockerfile.bot # Dockerfile per il bot Telegram
├── docker-compose.yml # Compose file per sviluppo locale / deploy
├── shared/ # Dati condivisi tra bot e web
│ └── dati.csv # File CSV con i nodi
├── web/ # Codice frontend
└── bot/ # Codice bot Telegram
```

---

## Installazione e avvio

### Con Docker Compose

```bash
git clone https://github.com/<tuo-username>/MeshCoreIT-map.git
cd MeshCoreIT-map
docker compose build
docker compose up -d
```

## Configurazione

Bot Telegram: impostare BOT_TOKEN come variabile d'ambiente.

Admin: definire gli ID degli admin in ADMIN_IDS.

Utenti speciali: definire gli ID in SPECIAL_USERS.

File CSV nodi: /shared/dati.csv contiene tutti i nodi registrati.

