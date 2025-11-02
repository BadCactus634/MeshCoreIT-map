# -*- coding: utf-8 -*-

import csv
import re
import os
import tempfile
import shutil
import logging
import sys
import json
import time
import traceback
from telegram.constants import ParseMode
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove, Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler, JobQueue

user_operations = {}  # {user_id_str: {'operation': 'add'}
active_users = set() # Set che tiene traccia degli utenti in conversazione

############################################
#                                          #
#              CONFIGURAZIONE              #
#                                          #
############################################

FREQUENCIES = ["433 MHz", "868 MHz"]

# Configurazione file e percorsi
FILE = "shared/dati.csv"
ENCODING = "utf-8"
LOG_STATE_FILE = "log_state.json"

# Limiti di input
MAX_NAME_LENGTH = 18
MAX_DESC_LENGTH = 130
MAX_LINK_LENGTH = 70
MAX_MARKERS_PER_USER = 6
MAX_MARKERS_FOR_SPECIAL_USERS = MAX_MARKERS_PER_USER*2

# Timeout conversazioni
TIMEOUT_SECONDS = 300

# Utenti speciali (da usare come array numerici)
ADMIN_IDS = [1608289624]
SPECIAL_USERS = [1608289624]

# Messaggi del bot
MESSAGES = {
    "start": "👋 <b>Benvenuto!</b> Scegli un'azione:\n\n"
             "➕ Aggiungi marker (massimo 3) - /add\n"
             "✏️ Rinomina marker - /rename\n"
             "🗑️ Elimina marker - /delete\n"
             "📍 Lista marker - /list\n"
             "🛑 Annulla operazione - /abort",
    "unknown_command": "❌ Comando non riconosciuto. Usa /start per iniziare",
    "no_markers": "❌ Non hai ancora aggiunto marker",
    "no_markers_to_rename": "❌ Non hai marker da rinominare",
    "no_markers_to_delete": "❌ Non hai marker da eliminare",
    "err_operation_in_progress": "❌ Hai già un'operazione in corso. Completa prima quella o cancellala con /abort",
    "err_max_markers_reached": f"❌ Hai già {MAX_MARKERS_PER_USER} marker. Elimina uno per aggiungerne un altro",
    "err_invalid_selection": "❌ Selezione non valida. Riprova inviando un valore valido",
    "err_invalid_name": "❌ Nome non valido",
    "err_name_too_long": f"❌ Il nome è troppo lungo. Massimo {MAX_NAME_LENGTH} caratteri",
    "err_desc_too_long": f"❌ La descrizione è troppo lunga. Massimo {MAX_DESC_LENGTH} caratteri",
    "err_link_too_long": f"❌ Il link è troppo lungo. Massimo {MAX_LINK_LENGTH} caratteri",
    "err_invalid_link": "❌ Il link non è valido. Deve iniziare con http:// o https://",
    "err_duplicate_name": "❌ Hai già un marker con questo nome. Inserisci un altro nome",
    "select_freq_kbd": "❌ Seleziona una frequenza valida dalla tastiera",
    "error_generic": "❌ Si è verificato un errore. Segnala il problema a un admin",
    "error_position": "❌ Valore non valido. Invia la posizione o inserisci le coordinate manualmente",
    "error_value": "❌ Valore non valido",
    "err_no_active_operation": "❌ Nessuna operazione in corso",
    "cancelled": "🛑 Operazione annullata",
    "add_lat": "📍 Inserisci la latitudine oppure invia la posizione:",
    "add_lon": "📍 Inserisci la longitudine:",
    "add_name": f"🔤 Inserisci il nome del marker (max {MAX_NAME_LENGTH} caratteri):",
    "enter_description": f"✏️ Inserisci una descrizione (max {MAX_DESC_LENGTH} caratteri):",
    "add_link_ask": "🔗 Vuoi aggiungere un link?",
    "add_link": "🔗 Inserisci il link:",
    "rename_select": "Quale marker vuoi rinominare?\n\n",
    "rename_new_name": "🔤 Inserisci il nuovo nome:",
    "delete_select": "Quale marker vuoi eliminare?\n\n",
    "your_markers": "📍 I tuoi marker:\n\n",
    "select_frequency": "📶 Seleziona la frequenza di utilizzo:",
    "no_markers_left": "Non hai più marker salvati",
    "marker_added": "✅ Marker aggiunto con successo!",
    "marker_deleted": "🗑️ Marker eliminato",
    "name_updated": "✅ Nome aggiornato!",
    "not_authorized": "⛔ Accesso negato",
    "timed_out": "⏳ Sessione scaduta per inattività. Usa /start per ricominciare."
}

# Stati del ConversationHandler
(
    ADD_LAT, ADD_LON, ADD_NAME, ADD_LINK_ASK, 
    ADD_LINK, RENAME_SELECT, RENAME_NEW_NAME, DELETE_SELECT, 
    SELECT_NODE_TYPE, SELECT_FREQUENCY, ENTER_DESCRIPTION
) = range(11)


################################################
#                                              #
#             FUNZIONI DI SERVIZIO             #
#                                              #
################################################

# Handler per timeout della chat
def check_err_operation_in_progress(uid, operation=None):
    """Verifica se l'utente ha un'operazione attiva e non scaduta.
       Se 'operation' è specificata, controlla che sia la stessa."""
    op = user_operations.get(uid)
    if not op:
        return False
    if operation and op['operation'] == operation:
        return False
    return True

async def abort_outside_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in active_users:
        # Se per qualche motivo il conversation handler non ha gestito l'abort
        active_users.discard(user_id)
        await update.message.reply_text(MESSAGES["cancelled"])
    else:
        await update.message.reply_text(MESSAGES["err_no_active_operation"])

def clean_text(text):
    """Pulisce il testo rimuovendo caratteri speciali SENZA limitare la lunghezza"""
    text = text.strip('"\'')  # Rimuove apici all'inizio/fine
    text = re.sub(r'[^\w\s\-.,!?@#&%â‚¬:/\U0001F300-\U0001FAFF]', '', text, flags=re.UNICODE)
    return text

def is_valid_url(url):
    """Verifica se una stringa è un URL valido."""
    return re.match(r'^https?://[^\s]+$', url)

def read_markers():
    """Legge tutti i marker dal file CSV."""
    if not os.path.exists(FILE):
        return []
    
    with open(FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and reader.fieldnames[0].startswith('\ufeff'):
            reader.fieldnames[0] = reader.fieldnames[0].replace('\ufeff', '')
        
        fieldnames = ['lat', 'lon', 'name', 'desc', 'node_type', 'frequency', 'link', 'ID', 'user', 'timestamp']
        markers = []
        
        for row in reader:
            if not row.get('lat') or not row.get('lon') or not row.get('ID'):
                continue
            
            marker = {field: row.get(field, '') for field in fieldnames}
            if not marker['user']:
                marker['user'] = 'anonimo'
                
            markers.append(marker)
        
        return markers

def safe_write_markers(markers):
    """Scrive i marker su file in modo sicuro con file temporaneo."""
    fieldnames = ['lat', 'lon', 'name', 'desc', 'node_type', 'frequency', 'link', 'ID', 'user', 'timestamp']
    
    temp_file = tempfile.NamedTemporaryFile('w', newline='', delete=False, encoding='utf-8-sig')
    with temp_file as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for marker in markers:
            clean_marker = {field: marker.get(field, '') for field in fieldnames}
            writer.writerow(clean_marker)
    
    shutil.move(temp_file.name, FILE)

async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in active_users:
        # L'utente non è in conversazione, quindi lo invitiamo a usare /start
        await update.message.reply_text(
            MESSAGES["start"],
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        # Se vuoi, qui puoi gestire eventuali messaggi durante la conversazione
        pass

# -------------- LOGGING --------------

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Handler per console
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# # Handler per file (opzionale)
# file_handler = logging.FileHandler("bot.log")
# file_handler.setLevel(logging.INFO)
# file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# file_handler.setFormatter(file_formatter)

# Aggiungi handler al logger
logger.addHandler(console_handler)
# logger.addHandler(file_handler)


# ----- Log admin Telegram -----

def load_log_state():
    try:
        with open(LOG_STATE_FILE, 'r') as f:
            return json.load(f).get('enabled', True)
    except:
        return True

def save_log_state(enabled):
    with open(LOG_STATE_FILE, 'w') as f:
        json.dump({'enabled': enabled}, f)

LOG_ENABLED = load_log_state()

# -------------- MENU ADMIN --------------

async def send_log_to_admins(context: ContextTypes.DEFAULT_TYPE, message: str):
    """Invia un messaggio di log a tutti gli admin se i log sono abilitati"""
    global LOG_ENABLED
    if not LOG_ENABLED:
        return
        
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📢 LOG\n\n{message}"
            )
        except Exception as e:
            logging.error(f"Errore invio log all'admin {admin_id}: {e}")

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu di gestione per admin"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text(MESSAGES["not_authorized"])
        return

    # Bottone per invertire lo stato
    log_button = InlineKeyboardButton(
        "🔈 Abilita Log" if not LOG_ENABLED else "🔇 Disabilita Log",
        callback_data="log_on" if not LOG_ENABLED else "log_off"
    )
    
    keyboard = [
        [log_button],
        [InlineKeyboardButton("📊 Statistiche", callback_data="stats")],
        [InlineKeyboardButton("📤 Esporta dati", callback_data="export")]
    ]
    
    await update.message.reply_text(
        f"🛠️ *Menu Admin* - Stato log: {'✅ ON' if LOG_ENABLED else '❌ OFF'}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce tutte le azioni dal menu admin"""
    global LOG_ENABLED
    
    query = update.callback_query
    await query.answer()  # Chiude l'indicatore di caricamento
    
    # Verifica che l'utente sia un admin
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text(MESSAGES["not_authorized"])
        return
    
    # Gestione delle diverse azioni
    if query.data == "log_on":
        LOG_ENABLED = True
        save_log_state(True)  # Salva lo stato su file
        await query.edit_message_text(
            "✅ Log abilitati\n\n"
            "Tutte le azioni degli utenti verranno inviate agli admin",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Torna al menu", callback_data="back_to_menu")]
            ])
        )
        
    elif query.data == "log_off":
        LOG_ENABLED = False
        save_log_state(False)  # Salva lo stato su file
        await query.edit_message_text(
            "❌ Log disabilitati\n\n"
            "Nessuna notifica verrà inviata agli admin",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Torna al menu", callback_data="back_to_menu")]
            ])
        )
        
    elif query.data == "stats":
        await admin_stats(update, context)
        
    elif query.data == "export":
        await admin_export(update, context)
        
    elif query.data == "back_to_menu":
        # Ricrea il menu principale
        keyboard = [
            [InlineKeyboardButton("🔈 Abilita Log" if not LOG_ENABLED else "🔇 Disabilita Log", 
             callback_data="log_off" if LOG_ENABLED else "log_on")],
            [InlineKeyboardButton("📊 Statistiche", callback_data="stats")],
            [InlineKeyboardButton("📤 Esporta dati", callback_data="export")]
        ]
        await query.edit_message_text(
            "🛠️ *Menu Admin* - Stato log: " + ("✅ ON" if LOG_ENABLED else "❌ OFF"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra le statistiche agli admin."""
    query = update.callback_query
    await query.answer()  # Chiude l'indicatore di caricamento
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text(MESSAGES["not_authorized"])
        return

    markers = read_markers()
    total_markers = len(markers)
    
    # Statistiche utenti
    users = {}
    for marker in markers:
        user_id = marker['ID']
        users[user_id] = users.get(user_id, 0) + 1
    
    top_users = sorted(users.items(), key=lambda x: x[1], reverse=True)[:5]
    markers_with_links = sum(1 for m in markers if m.get('link'))

    # Calcola percentuale solo se ci sono marker
    link_percentage = f"{markers_with_links / total_markers:.1%}" if total_markers else "0%"
    
    # Costruisci il messaggio
    stats_message = (
        "📊 <b>Statistiche Admin</b>\n\n"
        f"📍 <b>Marker totali:</b> {total_markers}\n"
        f"👥 <b>Utenti unici:</b> {len(users)}\n"
        f"🔗 <b>Marker con link:</b> {markers_with_links} ({link_percentage})\n\n"
        "🏆 <b>Top contributor:</b>\n"
    )
    
    if top_users:
        for i, (user_id, count) in enumerate(top_users, 1):
            user_info = next((m for m in markers if m['ID'] == user_id), None)
            username = f"@{user_info['user']}" if user_info and user_info.get('user') else f"Utente #{user_id}"
            stats_message += f"{i}. {username}: {count} marker\n"
    else:
        stats_message += "Nessun marker registrato.\n"

    stats_message += (
        f"\n⭐ <b>Utenti speciali:</b> {sum(1 for uid in users if int(uid) in SPECIAL_USERS)}\n"
        f"🔢 <b>Max marker per utente:</b> {MAX_MARKERS_PER_USER} (normali), {MAX_MARKERS_FOR_SPECIAL_USERS} (speciali)"
    )
    
    await query.edit_message_text(
        stats_message, 
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Torna al menu", callback_data="back_to_menu")]
        ])
    )


async def admin_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Esporta tutti i marker in un file CSV."""
    query = update.callback_query
    await query.answer()  # Chiude l'indicatore di caricamento
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text(MESSAGES["not_authorized"])
        return
    
    try:
        with open(FILE, 'rb') as f:
            await context.bot.send_document(
                chat_id=query.from_user.id,
                document=f,
                filename='markers_export.csv'
            )
        await query.edit_message_text(
            "✅ File esportato con successo!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Torna al menu", callback_data="back_to_menu")]
            ])
        )
    except Exception as e:
        logging.error(f"Errore esportazione: {str(e)}")
        await query.edit_message_text(MESSAGES["error_generic"])


#########################################
#                                       #
#            HANDLER COMANDI            #
#                                       #
#########################################

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    await update.message.reply_text(
        MESSAGES["start"],
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove()
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce il comando /help."""
    await start(update, context)

async def abort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    active_users.discard(uid)
    # Pulisci operazioni
    user_operations.pop(uid, None)
    # Pulisci user_data
    context.user_data.clear()
    await update.message.reply_text(MESSAGES["cancelled"], reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce comandi sconosciuti."""
    await update.message.reply_text(
            MESSAGES["unknown_command"],
            reply_markup=ReplyKeyboardRemove()
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, TimeoutError):
        uid = str(update.effective_user.id)
        user_operations.pop(uid, None)
        await update.message.reply_text(
            MESSAGES["timed_out"],
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        logging.error(f"Errore: {context.error}")

#######################################################
#                                                     #
#                  HANDLER OPERAZIONI                 #
#                                                     #
#######################################################

# -------------- AGGIUNTA MARKER --------------

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    active_users.add(uid)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "add"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    # Registra l'operazione
    user_operations[uid] = {'operation': 'add'}
    
    # Inizio operazione add
    markers = read_markers()
    user_markers = [m for m in markers if m['ID'] == uid]

    # Gestione limiti marker
    if int(uid) in ADMIN_IDS:
        max_markers = float('inf')  # Nessun limite per admin
    elif int(uid) in SPECIAL_USERS:
        max_markers = MAX_MARKERS_FOR_SPECIAL_USERS
    else:
        max_markers = MAX_MARKERS_PER_USER

    if len(user_markers) >= max_markers:
        await update.message.reply_text(
            f"Hai già {max_markers if max_markers != float('inf') else '∞'} marker. "
            "Elimina uno per aggiungerne un altro." if max_markers != float('inf') else "Sei un admin, puoi aggiungere tutti i marker che vuoi."
        )
        return ConversationHandler.END
    
    await update.message.reply_text(MESSAGES["add_lat"])
    return ADD_LAT

async def add_lat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce l'inserimento della latitudine."""
    uid = str(update.effective_user.id)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "add"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END
    
    try:
        # Se l'utente ha inviato la posizione
        if update.message.location:
            context.user_data.update({
                'lat': update.message.location.latitude,
                'lon': update.message.location.longitude
            })
            logging.info(f"Posizione ricevuta da {update.effective_user.username or 'anonimo'} (ID: {uid}): {context.user_data['lat']}, {context.user_data['lon']}")
            
            await update.message.reply_text(MESSAGES["add_name"])
            return ADD_NAME
        
        # Se l'utente ha inserito manualmente la latitudine
        try:
            lat = float(update.message.text)
            context.user_data['lat'] = lat
            await update.message.reply_text(MESSAGES["add_lon"])
            return ADD_LON
            
        except ValueError:
            await update.message.reply_text(MESSAGES["error_position"])
            return ADD_LAT
            
    except Exception as e:
        logging.error(f"Errore in add_lat per {uid}: {str(e)}", exc_info=True)
        await update.message.reply_text(MESSAGES["error_generic"])
        user_operations.pop(uid, None)
        return ConversationHandler.END

async def add_lon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce l'inserimento della longitudine."""
    uid = str(update.effective_user.id)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "add"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END
    
    try:
        if 'lat' not in context.user_data:
            await update.message.reply_text(MESSAGES["error_generic"])
            user_operations.pop(uid, None)
            return ConversationHandler.END
            
        lon = float(update.message.text)
        context.user_data['lon'] = lon
        
        logging.info(f"Coordinate complete per {uid}: {context.user_data['lat']}, {context.user_data['lon']}")
        
        await update.message.reply_text(MESSAGES["add_name"])
        return ADD_NAME
        
    except ValueError:
        await update.message.reply_text(MESSAGES["error_value"])
        return ADD_LON
    except Exception as e:
        logging.error(f"Errore in add_lon per {uid}: {str(e)}", exc_info=True)
        await update.message.reply_text(MESSAGES["error_generic"])
        user_operations.pop(uid, None)
        return ConversationHandler.END

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    
    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "add"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    try:
        name = clean_text(update.message.text)
        
        # Controllo lunghezza nome
        if len(name) > MAX_NAME_LENGTH:
            await update.message.reply_text(MESSAGES["err_name_too_long"])
            return ADD_NAME

        # Controllo duplicati
        existing_markers = read_markers()
        user_markers = [m for m in existing_markers if str(m['ID']) == uid]  # Confronta come stringa
        
        if any(m['name'].lower() == name.lower() for m in user_markers):
            await update.message.reply_text(
                MESSAGES["err_duplicate_name"]
            )
            # Rimane nello stesso step, richiede di nuovo il nome
            return ADD_NAME

        # Salva il nome
        context.user_data['name'] = name
        context.user_data['timestamp'] = time.time()  # Aggiorna timestamp
        
        # Salta selezione tipo nodo: imposta default
        context.user_data['node_type'] = "MeshCore"

        # Vai direttamente alla frequenza, crea tastiera
        freq_keyboard = ReplyKeyboardMarkup(
            [[freq] for freq in FREQUENCIES],
            one_time_keyboard=True,
            resize_keyboard=True,
            input_field_placeholder="Seleziona frequenza..."
        )
        
        await update.message.reply_text(
            MESSAGES["select_frequency"],
            reply_markup=freq_keyboard
        )
        return SELECT_FREQUENCY

    except Exception as e:
        logging.error(f"Errore in add_name per {uid}: {str(e)}", exc_info=True)
        await update.message.reply_text(MESSAGES["error_generic"])
        logging.error(traceback.format_exc())
        user_operations.pop(uid, None)
        return ConversationHandler.END

async def select_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "add"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    frequency = update.message.text
    if frequency not in FREQUENCIES:
        await update.message.reply_text(MESSAGES["select_freq_kbd"])
        return SELECT_FREQUENCY
    
    context.user_data['frequency'] = frequency
    
    # Rimuovi la tastiera e passa alla descrizione libera
    await update.message.reply_text(
        MESSAGES["enter_description"],
        reply_markup=ReplyKeyboardRemove()
    )
    return ENTER_DESCRIPTION

async def enter_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce l'inserimento della descrizione."""
    uid = str(update.effective_user.id)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "add"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END
    
    try:
        free_desc = clean_text(update.message.text)
        if len(free_desc) > MAX_DESC_LENGTH:
            await update.message.reply_text(
                MESSAGES["err_desc_too_long"],
                reply_markup=ReplyKeyboardRemove()
            )
            user_operations.pop(uid, None)
            return ConversationHandler.END
        
        context.user_data['desc'] = free_desc
        
        # Crea tastiera per scelta link
        await update.message.reply_text(
            MESSAGES["add_link_ask"],
            reply_markup=ReplyKeyboardMarkup(
                [["Si", "No"]],
                one_time_keyboard=True,
                resize_keyboard=True,
                input_field_placeholder="Vuoi aggiungere un link?"
            )
        )
        return ADD_LINK_ASK
        
    except Exception as e:
        logging.error(f"Errore in enter_description per {uid}: {str(e)}")
        await update.message.reply_text(MESSAGES["error_generic"])
        user_operations.pop(uid, None)
        return ConversationHandler.END

async def add_link_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "add"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    text = update.message.text.lower()

    if text in ["si", "sì"]:
        await update.message.reply_text(
            MESSAGES["add_link"],
            reply_markup=ReplyKeyboardRemove()
        )
        return ADD_LINK
    elif text in ["no", "n"]:
        context.user_data['link'] = ""
        return await finish_add(update, context)
    else:
        # Risposta non valida, rimani nello stesso stato
        await update.message.reply_text(
            "❌ Risposta non valida. Seleziona un'opzione dalla tastiera",
            reply_markup=ReplyKeyboardMarkup(
                [["Si", "No"]],
                one_time_keyboard=True,
                resize_keyboard=True,
                input_field_placeholder="Vuoi aggiungere un link?"
            )
        )
        return ADD_LINK_ASK

async def add_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "add"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    link = update.message.text.strip()

    if len(link) > MAX_LINK_LENGTH:
        await update.message.reply_text(
            MESSAGES["err_link_too_long"],
            reply_markup=ReplyKeyboardRemove()
        )
        return ADD_LINK

    if not is_valid_url(link):
        await update.message.reply_text(
            MESSAGES["err_invalid_link"],
            reply_markup=ReplyKeyboardRemove()
        )
        return ADD_LINK

    context.user_data['link'] = link
    return await finish_add(update, context)

async def finish_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Completa il processo di aggiunta marker."""
    uid = str(update.effective_user.id)
    try:
        marker = context.user_data
        
        # Verifica campi obbligatori
        required_fields = ['lat', 'lon', 'name', 'node_type', 'frequency', 'desc']
        for field in required_fields:
            if field not in marker:
                await update.message.reply_text(
                    f"❌ Manca il campo: {field}",
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END

        # Completa con i campi aggiuntivi
        marker.update({
            'ID': uid,
            'user': update.effective_user.username or "anonimo",
            'link': marker.get('link', ''),
            'timestamp': int(time.time())
        })

        # Salvataggio
        markers = read_markers()
        markers.append(marker)
        safe_write_markers(markers)

        if LOG_ENABLED:  # Solo se i log sono abilitati
            log_message = (
                f"➕ Marker aggiunto\n"
                f"👤 Utente: {update.effective_user.username or 'anonimo'} (ID: {uid})\n"
                f"📍 Nome: {marker['name']}\n"
                f"📶 Frequenza: {marker['frequency']}\n"
            )
            if marker['link']:
                log_message += f"🔗 Link: {marker['link']}\n"
            await send_log_to_admins(context, log_message)

        await update.message.reply_text(
                MESSAGES["marker_added"],
                reply_markup=ReplyKeyboardRemove()
            )
        logger.info(f"Marker aggiunto da {update.effective_user.username or 'anonimo'} (ID: {uid}) - "
            f"Nome: {context.user_data['name']}, Link: {context.user_data.get('link', '')}, "
            f"Frequency: {context.user_data.get('frequency')}, Node Type: {context.user_data.get('node_type')}")
        return ConversationHandler.END

    except Exception as e:
        logging.error(f"Errore in finish_add: {str(e)}")
        await update.message.reply_text(MESSAGES["error_generic"])
        logger.error(f"Errore in finish_add per utente {uid}: {str(e)}", exc_info=True)
        return ConversationHandler.END
    finally:
        user_operations.pop(str(update.effective_user.id), None)
        active_users.discard(uid)

# -------------- RINOMINA MARKER --------------

async def rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    active_users.add(uid)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "rename"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    # Registra l'operazione
    user_operations[uid] = {'operation': 'rename'}
        
    markers = [m for m in read_markers() if m['ID'] == uid]
    if not markers:
        await update.message.reply_text(MESSAGES["no_markers_to_rename"])
        return ConversationHandler.END

    # Salva i marker nel context
    context.user_data['markers'] = markers
        
    msg = MESSAGES["rename_select"] + "\n".join(f"{i+1}. {m['name']}" for i, m in enumerate(markers))
    await update.message.reply_text(msg)
    return RENAME_SELECT

async def rename_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "rename"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    try:
        idx = int(update.message.text.strip()) - 1
        if idx < 0 or idx >= len(context.user_data['markers']):
            raise ValueError
    except:
        await update.message.reply_text(MESSAGES["err_invalid_selection"])
        logger.error(f"Errore in rename_select per utente {uid}: {str(e)}", exc_info=True)
        return RENAME_SELECT
    context.user_data['selected'] = idx
    await update.message.reply_text(MESSAGES["rename_new_name"])
    return RENAME_NEW_NAME

async def rename_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "rename"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    idx = context.user_data['selected']
    new_name = update.message.text.strip().strip('"')

    if not new_name:
        await update.message.reply_text(MESSAGES["err_invalid_name"])
        return RENAME_NEW_NAME

    if len(new_name) > MAX_NAME_LENGTH:
        await update.message.reply_text(MESSAGES["err_name_too_long"])
        return RENAME_NEW_NAME

    if any(m['name'] == new_name for m in read_markers() if m['ID'] == uid):
        await update.message.reply_text(
            MESSAGES["err_duplicate_name"]
        )
        # Rimane nello stesso step, richiede di nuovo il nome
        return RENAME_NEW_NAME

    markers = read_markers()
    count = -1
    old_name = None
    for m in markers:
        if m['ID'] == uid:
            count += 1
            if count == idx:
                old_name = m['name']  # Memorizza il vecchio nome prima di aggiornare
                m['name'] = new_name
                break

    safe_write_markers(markers)

    # Invia log agli admin
    if LOG_ENABLED:
        log_message = f"✏️ Marker rinominato\n"
        log_message += f"👤 Utente: {update.effective_user.username or 'anonimo'} (ID: {uid})\n"
        if old_name:
            log_message += f"📛 Vecchio nome: {old_name}\n"
        log_message += f"🆕 Nuovo nome: {new_name}\n"
        await send_log_to_admins(context, log_message)

    logger.info(f"Marker rinominato da {update.effective_user.username or 'anonimo'} (ID: {uid}) - "
            f"Vecchio nome: {old_name}, Nuovo nome: {new_name}")

    user_operations.pop(uid, None)
    active_users.discard(uid)
    await update.message.reply_text(MESSAGES["name_updated"])
    return ConversationHandler.END

# -------------- ELIMINAZIONE MARKER --------------

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    active_users.add(uid)

    # Controllo se un'altra operazione è in corso 
    if check_err_operation_in_progress(uid, "delete"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    # Registra l'operazione
    user_operations[uid] = {'operation': 'delete'}
        
    markers = [m for m in read_markers() if m['ID'] == uid]
    if not markers:
        await update.message.reply_text(MESSAGES["no_markers_to_delete"])
        return ConversationHandler.END

    # Salva i marker nel context per il controllo
    context.user_data['markers'] = markers
        
    msg = MESSAGES["delete_select"] + "\n".join(f"{i+1}. {m['name']}" for i, m in enumerate(markers))
    await update.message.reply_text(msg)
    return DELETE_SELECT

async def delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    if check_err_operation_in_progress(uid, "delete"):
        await update.message.reply_text(MESSAGES["err_operation_in_progress"])
        return ConversationHandler.END

    try:
        idx = int(update.message.text.strip()) - 1
        if idx < 0 or idx >= len(context.user_data['markers']):
            raise ValueError
    except ValueError:
        await update.message.reply_text(MESSAGES["err_invalid_selection"])
        return DELETE_SELECT

    deleted_marker = context.user_data['markers'][idx]

    # Cancella dal file tutti i marker dell'utente e riscrive senza quello selezionato
    all_markers = read_markers()
    all_markers = [m for i, m in enumerate(all_markers) if not (m['ID'] == uid and m['name'] == deleted_marker['name'])]
    safe_write_markers(all_markers)

    if LOG_ENABLED:
        log_message = f"🗑️ Marker eliminato\n"
        log_message += f"👤 Utente: {update.effective_user.username or 'anonimo'} (ID: {uid})\n"
        log_message += f"📍 Nome: {deleted_marker['name']}\n"
        if deleted_marker['link']:
            log_message += f"🔗 Link: {deleted_marker['link']}\n"
        await send_log_to_admins(context, log_message)

    await update.message.reply_text(MESSAGES["marker_deleted"])

    updated = [m for m in read_markers() if m['ID'] == uid]
    if updated:
        msg = MESSAGES["your_markers"]
        for m in updated:
            msg += f"• {m['name']}"
            if m['link']:
                msg += f" → {m['link']}"
            msg += "\n"
    else:
        msg = MESSAGES["no_markers_left"]
    await update.message.reply_text(msg, disable_web_page_preview=True)
    logger.info(f"Marker eliminato da {update.effective_user.username or 'anonimo'} (ID: {uid}) - Nome: {deleted_marker['name']}, Link: {deleted_marker.get('link', '')}")

    user_operations.pop(uid, None)
    active_users.discard(uid)
    return ConversationHandler.END

# -------------- STAMPA MARKER --------------
async def list_markers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    
    markers = [m for m in read_markers() if m['ID'] == uid]
    if not markers:
        await update.message.reply_text(MESSAGES["no_markers"])
    else:
        msg = MESSAGES["your_markers"]
        for m in markers:
            msg += f"• {m['name']}"
            if m['link']:
                msg += f" → {m['link']}"
            msg += "\n"
        await update.message.reply_text(msg, disable_web_page_preview=True)



############################################
#                                          #
#                   MAIN                   #
#                                          #
############################################

if __name__ == '__main__':
    # Crea l'applicazione
    token = os.getenv("BOT_TOKEN")
    # app = ApplicationBuilder().token(token).build()
    app = (
        ApplicationBuilder()
        .token(token)
        .read_timeout(30)
        .write_timeout(30)
        .concurrent_updates(True)
        .job_queue(JobQueue())  # <-- Aggiungi questa linea
        .build()
    )

    # Configura i ConversationHandler
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add)],
        states={
            ADD_LAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_lat),
                MessageHandler(filters.LOCATION, add_lat),
            ],
            ADD_LON: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_lon)],
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            SELECT_FREQUENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_frequency)],
            ENTER_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_description)],
            ADD_LINK_ASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_link_ask)],
            ADD_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_link)],
        },
        fallbacks=[CommandHandler("abort", abort)],
        conversation_timeout=TIMEOUT_SECONDS,
        per_user=True
    )

    rename_conv = ConversationHandler(
        entry_points=[CommandHandler("rename", rename)],
        states={
            RENAME_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rename_select)],
            RENAME_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, rename_new_name)],
        },
        fallbacks=[CommandHandler("abort", abort)],
        conversation_timeout=TIMEOUT_SECONDS,
        per_user=True
    )

    delete_conv = ConversationHandler(
        entry_points=[CommandHandler("delete", delete)],
        states={
            DELETE_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_select)],
        },
        fallbacks=[CommandHandler("abort", abort)],
        conversation_timeout=TIMEOUT_SECONDS,
        per_user=True
    )

    # Registra gli handler
    app.add_handler(CallbackQueryHandler(
        admin_button_handler, 
        pattern="^(log_on|log_off|stats|export|back_to_menu)$"
    ))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help))    
    app.add_handler(CommandHandler("list", list_markers))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("admin", admin_menu))
    app.add_handler(CommandHandler("export", admin_export))

    # ConversationHandler
    app.add_handler(add_conv)
    app.add_handler(rename_conv)
    app.add_handler(delete_conv)

    # Abort "globale" SOLO se non in conversazione
    app.add_handler(CommandHandler("abort", abort_outside_conversation))

    # Il resto dei comandi sconosciuti
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Fallback messaggi testuali fuori conversazioni
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))
    
    app.add_error_handler(error_handler)

    # Avvia il bot
    app.run_polling()