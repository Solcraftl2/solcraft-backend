from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
from datetime import datetime, timedelta
import jwt
import hashlib
import smtplib
import psycopg2
from psycopg2.extras import RealDictCursor, DictCursor, register_uuid
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import supabase
import traceback
import logging

# Configurazione logging avanzato
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('solcraft-backend')

# Registra l'adattatore UUID per psycopg2
register_uuid()

# Aggiornamento per trigger deploy con supporto PostgreSQL su Supabase

app = Flask(__name__)
CORS(app)

# Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'your-secret-key')
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')

# PostgreSQL Database Connection
DATABASE_URL = os.environ.get('DATABASE_URL')
POSTGRES_URL = os.environ.get('POSTGRES_URL')
POSTGRES_URL_NON_POOLING = os.environ.get('POSTGRES_URL_NON_POOLING')
supabase_url = os.environ.get('SUPABASE_URL')
supabase_key = os.environ.get('SUPABASE_KEY')

# Logging delle variabili d'ambiente (oscurate per sicurezza)
logger.info(f"DATABASE_URL configurato: {DATABASE_URL[:20] + '...' if DATABASE_URL else 'Non configurato'}")
logger.info(f"POSTGRES_URL configurato: {POSTGRES_URL[:20] + '...' if POSTGRES_URL else 'Non configurato'}")
logger.info(f"POSTGRES_URL_NON_POOLING configurato: {POSTGRES_URL_NON_POOLING[:20] + '...' if POSTGRES_URL_NON_POOLING else 'Non configurato'}")
logger.info(f"SUPABASE_URL configurato: {supabase_url if supabase_url else 'Non configurato'}")
logger.info(f"SUPABASE_KEY configurato: {'Configurato' if supabase_key else 'Non configurato'}")

# Initialize Supabase client
supabase_client = None
if supabase_url and supabase_key:
    try:
        supabase_client = supabase.create_client(supabase_url, supabase_key)
        logger.info(f"Supabase client inizializzato con successo con URL: {supabase_url}")
    except Exception as e:
        logger.error(f"Errore inizializzazione Supabase client: {str(e)}")
        logger.error(traceback.format_exc())

# Helper function to convert UUID to string if needed
def safe_uuid(value):
    """
    Converte un UUID in stringa se necessario.
    Ritorna il valore originale se non è un UUID.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    return value

# Helper function to ensure UUID is valid
def ensure_valid_uuid(value):
    """
    Assicura che il valore sia un UUID valido.
    Se è una stringa, tenta di convertirla in UUID.
    Se è già un UUID, lo ritorna come stringa.
    Se non è valido, solleva ValueError.
    """
    if value is None:
        return None
        
    if isinstance(value, uuid.UUID):
        return str(value)
        
    try:
        # Tenta di convertire in UUID per validare, poi ritorna come stringa
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        logger.error(f"UUID non valido: {value} (tipo: {type(value)})")
        raise ValueError(f"Invalid UUID format: {value}")

# Database connection function with improved SSL handling, connection format, and direct connection
def get_db_connection():
    # Logging dettagliato di ogni tentativo di connessione
    logger.info("Tentativo di connessione al database PostgreSQL...")
    
    try:
        # Priorità alle stringhe di connessione
        connection_string = None
        connection_type = None
        
        # 1. Prima prova con POSTGRES_URL_NON_POOLING (connessione diretta)
        if POSTGRES_URL_NON_POOLING:
            connection_string = POSTGRES_URL_NON_POOLING
            connection_type = "POSTGRES_URL_NON_POOLING (connessione diretta)"
        # 2. Poi prova con POSTGRES_URL (pooler)
        elif POSTGRES_URL:
            connection_string = POSTGRES_URL
            connection_type = "POSTGRES_URL (pooler)"
        # 3. Infine prova con DATABASE_URL
        elif DATABASE_URL:
            connection_string = DATABASE_URL
            connection_type = "DATABASE_URL"
        
        if not connection_string:
            logger.error("Nessuna stringa di connessione disponibile")
            return None
        
        # Modifica il prefisso da postgresql:// a postgres:// se necessario
        if connection_string.startswith('postgresql://'):
            connection_string = 'postgres://' + connection_string[14:]
            logger.info("Prefisso della stringa di connessione modificato da postgresql:// a postgres://")
        
        # Disabilita SSL per test
        if '?' not in connection_string:
            connection_string += "?sslmode=disable"
            logger.info("SSL disabilitato (sslmode=disable) per test")
        elif 'sslmode=' not in connection_string:
            connection_string += "&sslmode=disable"
            logger.info("SSL disabilitato (sslmode=disable) per test")
        else:
            # Sostituisci qualsiasi modalità SSL esistente con 'disable'
            import re
            connection_string = re.sub(r'sslmode=\w+', 'sslmode=disable', connection_string)
            logger.info("Modalità SSL esistente sostituita con 'disable' per test")
            
        logger.info(f"Tentativo di connessione con: {connection_type} - {connection_string[:20]}... (SSL disabilitato)")
        
        # Parametri di connessione espliciti con timeout aumentato
        conn = psycopg2.connect(
            connection_string,
            connect_timeout=60,  # Aumentato a 60 secondi
            application_name="solcraft-backend"  # Nome dell'applicazione per il monitoraggio
        )
        conn.autocommit = True
        logger.info(f"Connessione al database riuscita con {connection_type}")
        return conn
    except Exception as e:
        logger.error(f"Errore connessione al database con {connection_type if 'connection_type' in locals() else 'stringa sconosciuta'}: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Prova con connessione diretta hardcoded come ultima risorsa
        try:
            logger.info("Tentativo di connessione diretta hardcoded come ultima risorsa...")
            direct_conn_string = "postgres://postgres:kCxBrdFOGbqEgtfs@db.zlainxopxrjgfphwjdvk.supabase.co:5432/postgres?sslmode=disable"
            logger.info(f"Tentativo connessione diretta hardcoded: {direct_conn_string[:20]}...")
            conn = psycopg2.connect(
                direct_conn_string,
                connect_timeout=60,
                application_name="solcraft-backend-direct"
            )
            conn.autocommit = True
            logger.info("Connessione diretta hardcoded riuscita")
            return conn
        except Exception as direct_err:
            logger.error(f"Errore connessione diretta hardcoded: {str(direct_err)}")
            logger.error(traceback.format_exc())
        return None

# Sample data for testing
sample_tournaments = [
    {
        "id": "1",
        "name": "Sunday Million",
        "organizer_id": "1",
        "buy_in": 215,
        "total_prize": 1000000,
        "start_date": "2023-06-04T18:00:00Z",
        "end_date": "2023-06-04T23:00:00Z",
        "status": "completed"
    },
    {
        "id": "2",
        "name": "High Roller",
        "organizer_id": "2",
        "buy_in": 1050,
        "total_prize": 500000,
        "start_date": "2023-06-11T20:00:00Z",
        "end_date": "2023-06-11T23:59:00Z",
        "status": "upcoming"
    }
]

# Helper functions
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token(user_id):
    payload = {
        'exp': datetime.utcnow() + timedelta(days=1),
        'iat': datetime.utcnow(),
        'sub': user_id
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def verify_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return payload['sub']
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def send_email(to, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        logger.error(f"Errore invio email: {str(e)}")
        return False

# Routes
@app.route('/')
def home():
    try:
        # Risposta semplificata per l'endpoint radice per evitare errori in ambiente serverless
        return """
        <!DOCTYPE html>
        <html lang="it">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>SolCraft L2 API</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                    color: #333;
                }
                h1 {
                    color: #2c3e50;
                    border-bottom: 2px solid #3498db;
                    padding-bottom: 10px;
                }
                h2 {
                    color: #2980b9;
                }
                code {
                    background-color: #f8f8f8;
                    padding: 2px 5px;
                    border-radius: 3px;
                    font-family: monospace;
                }
                .endpoint {
                    margin-bottom: 20px;
                    padding: 15px;
                    background-color: #f9f9f9;
                    border-left: 4px solid #3498db;
                }
                .method {
                    font-weight: bold;
                    color: #e74c3c;
                }
            </style>
        </head>
        <body>
            <h1>SolCraft L2 API</h1>
            <p>Benvenuto nell'API di SolCraft L2. Questa API fornisce accesso ai dati e alle funzionalità della piattaforma SolCraft L2.</p>
            
            <h2>Endpoint disponibili</h2>
            
            <div class="endpoint">
                <p><span class="method">GET</span> <code>/api</code></p>
                <p>Informazioni generali sull'API e lista degli endpoint disponibili.</p>
            </div>
            
            <div class="endpoint">
                <p><span class="method">GET</span> <code>/api/tournaments</code></p>
                <p>Ottieni la lista di tutti i tornei disponibili.</p>
            </div>
            
            <div class="endpoint">
                <p><span class="method">POST</span> <code>/api/tournaments</code></p>
                <p>Crea un nuovo torneo.</p>
            </div>
            
            <div class="endpoint">
                <p><span class="method">GET</span> <code>/api/tournaments/:id</code></p>
                <p>Ottieni i dettagli di un torneo specifico.</p>
            </div>
            
            <div class="endpoint">
                <p><span class="method">POST</span> <code>/api/users/register</code></p>
                <p>Registra un nuovo utente.</p>
            </div>
            
            <div class="endpoint">
                <p><span class="method">POST</span> <code>/api/users/login</code></p>
                <p>Effettua il login di un utente.</p>
            </div>
            
            <div class="endpoint">
                <p><span class="method">POST</span> <code>/api/investments</code></p>
                <p>Crea un nuovo investimento.</p>
            </div>
            
            <h2>Stato API</h2>
            <p>Versione: 1.0.0</p>
            <p>Stato: Attiva</p>
            
            <footer>
                <p>Per ulteriori informazioni, consulta la <a href="/api">documentazione completa</a>.</p>
            </footer>
        </body>
        </html>
        """
    except Exception as e:
        # Gestione esplicita delle eccezioni per l'endpoint radice
        logger.error(f"Errore endpoint radice: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": "Error in root endpoint",
            "error": str(e)
        }), 500

# Aggiunto endpoint esplicito per /api
@app.route('/api')
def api_info():
    try:
        return jsonify({
            "status": "success",
            "message": "SolCraft API is running",
            "version": "1.0.0",
            "endpoints": [
                {"path": "/api/tournaments", "methods": ["GET", "POST"], "description": "Get all tournaments or create a new one"},
                {"path": "/api/tournaments/:id", "methods": ["GET"], "description": "Get details of a specific tournament"},
                {"path": "/api/users/register", "methods": ["POST"], "description": "Register a new user"},
                {"path": "/api/users/login", "methods": ["POST"], "description": "Login a user"},
                {"path": "/api/investments", "methods": ["POST"], "description": "Create a new investment"},
                {"path": "/api/debug/env", "methods": ["GET"], "description": "Debug endpoint for environment variables"},
                {"path": "/api/debug/connection", "methods": ["GET"], "description": "Debug endpoint for connection details"}
            ]
        })
    except Exception as e:
        logger.error(f"Errore endpoint API info: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": "Error in API info endpoint",
            "error": str(e)
        }), 500

# Endpoint di debug per le variabili d'ambiente
@app.route('/api/debug/env', methods=['GET'])
def debug_env():
    try:
        # Raccogli le variabili d'ambiente rilevanti (oscurando parti sensibili)
        env_vars = {
            "DATABASE_URL": DATABASE_URL[:20] + "..." if DATABASE_URL else None,
            "POSTGRES_URL": POSTGRES_URL[:20] + "..." if POSTGRES_URL else None,
            "POSTGRES_URL_NON_POOLING": POSTGRES_URL_NON_POOLING[:20] + "..." if POSTGRES_URL_NON_POOLING else None,
            "SUPABASE_URL": supabase_url,
            "SUPABASE_KEY": supabase_key[:10] + "..." if supabase_key else None,
            "JWT_SECRET": JWT_SECRET[:5] + "..." if JWT_SECRET else None,
            "SUPABASE_CLIENT_INITIALIZED": supabase_client is not None
        }
        
        # Tenta una connessione di test al database
        conn = get_db_connection()
        db_connection_success = conn is not None
        db_connection_message = "Database connection successful"
        db_connection_details = {}
        
        if conn:
            try:
                # Verifica che la connessione funzioni eseguendo una query semplice
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                
                # Raccogli informazioni sulla connessione
                cur = conn.cursor()
                cur.execute("SELECT current_database(), current_user, version()")
                db_info = cur.fetchone()
                db_connection_details = {
                    "database": db_info[0],
                    "user": db_info[1],
                    "version": db_info[2]
                }
                cur.close()
            except Exception as e:
                db_connection_message = f"Database connection established but query failed: {str(e)}"
                logger.error(f"Errore query di test: {str(e)}")
                logger.error(traceback.format_exc())
            finally:
                conn.close()
        else:
            db_connection_message = "Database connection failed"
        
        # Raccogli informazioni sul server
        server_info = {
            "python_version": os.environ.get("PYTHON_VERSION", "Unknown"),
            "vercel_region": os.environ.get("VERCEL_REGION", "Unknown"),
            "vercel_env": os.environ.get("VERCEL_ENV", "Unknown"),
            "now": datetime.now().isoformat()
        }
        
        return jsonify({
            "status": "success",
            "environment_variables": env_vars,
            "database_connection_test": {
                "success": db_connection_success,
                "message": db_connection_message,
                "details": db_connection_details
            },
            "server_info": server_info
        })
    except Exception as e:
        logger.error(f"Errore endpoint debug: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": "Error in debug endpoint",
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

# Nuovo endpoint di debug per dettagli connessione
@app.route('/api/debug/connection', methods=['GET'])
def debug_connection():
    try:
        # Test di connessione con diverse configurazioni
        results = []
        
        # Test 1: Connessione diretta hardcoded con SSL disabilitato
        try:
            start_time = datetime.now()
            direct_conn_string = "postgres://postgres:kCxBrdFOGbqEgtfs@db.zlainxopxrjgfphwjdvk.supabase.co:5432/postgres?sslmode=disable"
            conn = psycopg2.connect(direct_conn_string, connect_timeout=30)
            conn.autocommit = True
            
            # Verifica che la connessione funzioni
            cur = conn.cursor()
            cur.execute("SELECT current_database(), current_user, version()")
            db_info = cur.fetchone()
            cur.close()
            conn.close()
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            results.append({
                "type": "direct_hardcoded_ssl_disable",
                "success": True,
                "database": db_info[0],
                "user": db_info[1],
                "version": db_info[2],
                "duration_seconds": duration
            })
        except Exception as e:
            results.append({
                "type": "direct_hardcoded_ssl_disable",
                "success": False,
                "error": str(e)
            })
        
        # Test 2: Connessione con POSTGRES_URL_NON_POOLING
        if POSTGRES_URL_NON_POOLING:
            try:
                start_time = datetime.now()
                conn_string = POSTGRES_URL_NON_POOLING
                if conn_string.startswith('postgresql://'):
                    conn_string = 'postgres://' + conn_string[14:]
                
                # Assicurati che SSL sia disabilitato
                if '?' not in conn_string:
                    conn_string += "?sslmode=disable"
                elif 'sslmode=' not in conn_string:
                    conn_string += "&sslmode=disable"
                else:
                    import re
                    conn_string = re.sub(r'sslmode=\w+', 'sslmode=disable', conn_string)
                
                conn = psycopg2.connect(conn_string, connect_timeout=30)
                conn.autocommit = True
                
                # Verifica che la connessione funzioni
                cur = conn.cursor()
                cur.execute("SELECT current_database(), current_user, version()")
                db_info = cur.fetchone()
                cur.close()
                conn.close()
                
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                results.append({
                    "type": "postgres_url_non_pooling",
                    "success": True,
                    "database": db_info[0],
                    "user": db_info[1],
                    "version": db_info[2],
                    "duration_seconds": duration
                })
            except Exception as e:
                results.append({
                    "type": "postgres_url_non_pooling",
                    "success": False,
                    "error": str(e)
                })
        
        # Test 3: Connessione con POSTGRES_URL (pooler)
        if POSTGRES_URL:
            try:
                start_time = datetime.now()
                conn_string = POSTGRES_URL
                if conn_string.startswith('postgresql://'):
                    conn_string = 'postgres://' + conn_string[14:]
                
                # Assicurati che SSL sia disabilitato
                if '?' not in conn_string:
                    conn_string += "?sslmode=disable"
                elif 'sslmode=' not in conn_string:
                    conn_string += "&sslmode=disable"
                else:
                    import re
                    conn_string = re.sub(r'sslmode=\w+', 'sslmode=disable', conn_string)
                
                conn = psycopg2.connect(conn_string, connect_timeout=30)
                conn.autocommit = True
                
                # Verifica che la connessione funzioni
                cur = conn.cursor()
                cur.execute("SELECT current_database(), current_user, version()")
                db_info = cur.fetchone()
                cur.close()
                conn.close()
                
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                results.append({
                    "type": "postgres_url_pooler",
                    "success": True,
                    "database": db_info[0],
                    "user": db_info[1],
                    "version": db_info[2],
                    "duration_seconds": duration
                })
            except Exception as e:
                results.append({
                    "type": "postgres_url_pooler",
                    "success": False,
                    "error": str(e)
                })
        
        # Test 4: Connessione con DATABASE_URL
        if DATABASE_URL:
            try:
                start_time = datetime.now()
                conn_string = DATABASE_URL
                if conn_string.startswith('postgresql://'):
                    conn_string = 'postgres://' + conn_string[14:]
                
                # Assicurati che SSL sia disabilitato
                if '?' not in conn_string:
                    conn_string += "?sslmode=disable"
                elif 'sslmode=' not in conn_string:
                    conn_string += "&sslmode=disable"
                else:
                    import re
                    conn_string = re.sub(r'sslmode=\w+', 'sslmode=disable', conn_string)
                
                conn = psycopg2.connect(conn_string, connect_timeout=30)
                conn.autocommit = True
                
                # Verifica che la connessione funzioni
                cur = conn.cursor()
                cur.execute("SELECT current_database(), current_user, version()")
                db_info = cur.fetchone()
                cur.close()
                conn.close()
                
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                results.append({
                    "type": "database_url",
                    "success": True,
                    "database": db_info[0],
                    "user": db_info[1],
                    "version": db_info[2],
                    "duration_seconds": duration
                })
            except Exception as e:
                results.append({
                    "type": "database_url",
                    "success": False,
                    "error": str(e)
                })
        
        # Test 5: Connessione con get_db_connection
        try:
            start_time = datetime.now()
            conn = get_db_connection()
            
            if conn:
                # Verifica che la connessione funzioni
                cur = conn.cursor()
                cur.execute("SELECT current_database(), current_user, version()")
                db_info = cur.fetchone()
                cur.close()
                conn.close()
                
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                results.append({
                    "type": "get_db_connection",
                    "success": True,
                    "database": db_info[0],
                    "user": db_info[1],
                    "version": db_info[2],
                    "duration_seconds": duration
                })
            else:
                results.append({
                    "type": "get_db_connection",
                    "success": False,
                    "error": "Connection failed"
                })
        except Exception as e:
            results.append({
                "type": "get_db_connection",
                "success": False,
                "error": str(e)
            })
        
        return jsonify({
            "status": "success",
            "connection_tests": results
        })
    except Exception as e:
        logger.error(f"Errore endpoint debug connection: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": "Error in debug connection endpoint",
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

@app.route('/api/tournaments', methods=['GET'])
def get_tournaments():
    try:
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute("SELECT * FROM tournaments")
                tournaments = cur.fetchall()
                cur.close()
                conn.close()
                
                # Converti i dati per la risposta JSON
                tournaments_list = []
                for tournament in tournaments:
                    # Converti UUID a stringa per JSON
                    tournament_dict = dict(tournament)
                    for key, value in tournament_dict.items():
                        if isinstance(value, uuid.UUID):
                            tournament_dict[key] = str(value)
                    tournaments_list.append(tournament_dict)
                
                return jsonify({
                    "status": "success",
                    "data": tournaments_list
                })
            except Exception as e:
                logger.error(f"Errore query tournaments: {str(e)}")
                logger.error(traceback.format_exc())
                conn.close()
                # Fallback ai dati di esempio
                return jsonify({
                    "status": "success",
                    "data": sample_tournaments,
                    "note": "Using sample data due to database connection issue"
                })
        else:
            # Fallback ai dati di esempio
            return jsonify({
                "status": "success",
                "data": sample_tournaments,
                "note": "Using sample data due to database connection issue"
            })
    except Exception as e:
        logger.error(f"Errore endpoint tournaments: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/tournaments/<tournament_id>', methods=['GET'])
def get_tournament(tournament_id):
    try:
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                
                # Verifica se l'ID è un UUID valido
                try:
                    # Tenta di convertire l'ID in UUID per validazione
                    tournament_uuid = str(uuid.UUID(tournament_id))
                    # Se la conversione ha successo, usa l'UUID nella query
                    cur.execute("SELECT * FROM tournaments WHERE id::text = %s", (tournament_uuid,))
                except ValueError:
                    # Se non è un UUID valido, prova come stringa
                    cur.execute("SELECT * FROM tournaments WHERE id::text = %s", (tournament_id,))
                
                tournament = cur.fetchone()
                cur.close()
                conn.close()
                
                if tournament:
                    # Converti UUID a stringa per JSON
                    tournament_dict = dict(tournament)
                    for key, value in tournament_dict.items():
                        if isinstance(value, uuid.UUID):
                            tournament_dict[key] = str(value)
                    
                    return jsonify({
                        "status": "success",
                        "data": tournament_dict
                    })
                else:
                    # Fallback ai dati di esempio se il torneo non è trovato
                    for tournament in sample_tournaments:
                        if str(tournament["id"]) == str(tournament_id):
                            return jsonify({
                                "status": "success",
                                "data": tournament,
                                "note": "Using sample data due to database connection issue"
                            })
                    
                    return jsonify({
                        "status": "error",
                        "message": "Tournament not found"
                    }), 404
            except Exception as e:
                logger.error(f"Errore query tournament: {str(e)}")
                logger.error(traceback.format_exc())
                conn.close()
                # Fallback ai dati di esempio
                for tournament in sample_tournaments:
                    if str(tournament["id"]) == str(tournament_id):
                        return jsonify({
                            "status": "success",
                            "data": tournament,
                            "note": "Using sample data due to database connection issue"
                        })
                
                return jsonify({
                    "status": "error",
                    "message": str(e)
                }), 500
        else:
            # Fallback ai dati di esempio
            for tournament in sample_tournaments:
                if str(tournament["id"]) == str(tournament_id):
                    return jsonify({
                        "status": "success",
                        "data": tournament,
                        "note": "Using sample data due to database connection issue"
                    })
            
            return jsonify({
                "status": "error",
                "message": "Tournament not found"
            }), 404
    except Exception as e:
        logger.error(f"Errore endpoint tournament: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/tournaments', methods=['POST'])
def create_tournament():
    try:
        data = request.json
        
        # Validazione dei dati
        required_fields = ['name', 'buy_in', 'total_prize', 'start_date']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "status": "error",
                    "message": f"Missing required field: {field}"
                }), 400
        
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                
                # Genera un nuovo UUID per il torneo
                tournament_id = str(uuid.uuid4())
                logger.info(f"Nuovo UUID torneo generato: {tournament_id}")
                
                # Adatta i nomi delle colonne alla struttura reale del database
                # Converti organizer_id in stringa se presente
                organizer_id = None
                if data.get('organizer_id'):
                    try:
                        organizer_id = str(uuid.UUID(data.get('organizer_id')))
                        logger.info(f"UUID organizer_id validato: {organizer_id}")
                    except ValueError:
                        logger.error(f"UUID organizer_id non valido: {data.get('organizer_id')}")
                        return jsonify({
                            "status": "error",
                            "message": "Invalid organizer_id format"
                        }), 400
                
                # Gestione del campo end_date obbligatorio
                end_date = data.get('end_date')
                if not end_date:
                    # Se non fornito, imposta end_date a start_date + 3 ore
                    try:
                        start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00'))
                        end_date = (start_date + timedelta(hours=3)).isoformat()
                        logger.info(f"End date generata automaticamente: {end_date}")
                    except (ValueError, TypeError):
                        logger.error(f"Formato data non valido: {data['start_date']}")
                        return jsonify({
                            "status": "error",
                            "message": "Invalid start_date format"
                        }), 400
                
                # Log dei parametri prima dell'esecuzione della query
                logger.info(f"Parametri query INSERT tournaments: id={tournament_id}, name={data['name']}, organizer_id={organizer_id}, end_date={end_date}")
                
                cur.execute("""
                    INSERT INTO tournaments (id, name, buy_in, total_prize, start_date, end_date, status, organizer_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (
                    tournament_id,
                    data['name'],
                    data['buy_in'],
                    data['total_prize'],
                    data['start_date'],
                    end_date,
                    data.get('status', 'upcoming'),
                    organizer_id
                ))
                
                tournament = cur.fetchone()
                cur.close()
                conn.close()
                
                # Converti UUID a stringa per JSON
                tournament_dict = dict(tournament)
                for key, value in tournament_dict.items():
                    if isinstance(value, uuid.UUID):
                        tournament_dict[key] = str(value)
                
                return jsonify({
                    "status": "success",
                    "message": "Tournament created successfully",
                    "data": tournament_dict
                }), 201
            except Exception as e:
                logger.error(f"Errore creazione tournament: {str(e)}")
                logger.error(traceback.format_exc())
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": str(e)
                }), 500
        else:
            return jsonify({
                "status": "error",
                "message": "Database connection error"
            }), 500
    except Exception as e:
        logger.error(f"Errore endpoint create tournament: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/users/register', methods=['POST'])
def register_user():
    try:
        data = request.json
        
        # Validazione dei dati
        required_fields = ['username', 'email', 'password']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "status": "error",
                    "message": f"Missing required field: {field}"
                }), 400
        
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                
                # Verifica se l'utente esiste già
                cur.execute("SELECT * FROM users WHERE email = %s OR username = %s", (data['email'], data['username']))
                existing_user = cur.fetchone()
                
                if existing_user:
                    cur.close()
                    conn.close()
                    return jsonify({
                        "status": "error",
                        "message": "User with this email or username already exists"
                    }), 409
                
                # Genera un nuovo UUID per l'utente
                user_id = str(uuid.uuid4())
                logger.info(f"Nuovo UUID utente generato: {user_id}")
                
                # Hash della password
                password_hash = hash_password(data['password'])
                
                # Inserisci il nuovo utente
                # Log dei parametri prima dell'esecuzione della query
                logger.info(f"Parametri query INSERT users: id={user_id}, username={data['username']}, email={data['email']}")
                
                cur.execute("""
                    INSERT INTO users (id, username, email, password_hash, wallet_address, created_at, is_active, is_verified)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (
                    user_id,
                    data['username'],
                    data['email'],
                    password_hash,
                    data.get('wallet_address'),
                    datetime.now(),
                    True,
                    False
                ))
                
                user = cur.fetchone()
                cur.close()
                conn.close()
                
                # Converti UUID a stringa per JSON
                user_dict = dict(user)
                for key, value in user_dict.items():
                    if isinstance(value, uuid.UUID):
                        user_dict[key] = str(value)
                
                # Genera token JWT
                token = generate_token(user_dict['id'])
                
                return jsonify({
                    "status": "success",
                    "message": "User registered successfully",
                    "data": {
                        "user": user_dict,
                        "token": token
                    }
                }), 201
            except Exception as e:
                logger.error(f"Errore registrazione utente: {str(e)}")
                logger.error(traceback.format_exc())
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": str(e)
                }), 500
        else:
            return jsonify({
                "status": "error",
                "message": "Database connection error"
            }), 500
    except Exception as e:
        logger.error(f"Errore endpoint register: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/users/login', methods=['POST'])
def login_user():
    try:
        data = request.json
        
        # Validazione dei dati
        required_fields = ['email', 'password']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "status": "error",
                    "message": f"Missing required field: {field}"
                }), 400
        
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                
                # Verifica le credenziali
                password_hash = hash_password(data['password'])
                cur.execute("SELECT * FROM users WHERE email = %s AND password_hash = %s", (data['email'], password_hash))
                user = cur.fetchone()
                
                if not user:
                    cur.close()
                    conn.close()
                    return jsonify({
                        "status": "error",
                        "message": "Invalid email or password"
                    }), 401
                
                # Converti UUID a stringa per JSON e per l'aggiornamento
                user_dict = dict(user)
                for key, value in user_dict.items():
                    if isinstance(value, uuid.UUID):
                        user_dict[key] = str(value)
                
                # Aggiorna last_login
                cur.execute("UPDATE users SET last_login = %s WHERE id::text = %s", (datetime.now(), user_dict['id']))
                
                cur.close()
                conn.close()
                
                # Genera token JWT
                token = generate_token(user_dict['id'])
                
                return jsonify({
                    "status": "success",
                    "message": "Login successful",
                    "data": {
                        "user": user_dict,
                        "token": token
                    }
                })
            except Exception as e:
                logger.error(f"Errore login utente: {str(e)}")
                logger.error(traceback.format_exc())
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": str(e)
                }), 500
        else:
            return jsonify({
                "status": "error",
                "message": "Database connection error"
            }), 500
    except Exception as e:
        logger.error(f"Errore endpoint login: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/investments', methods=['POST'])
def create_investment():
    try:
        data = request.json
        
        # Validazione dei dati
        required_fields = ['user_id', 'tournament_id', 'amount']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "status": "error",
                    "message": f"Missing required field: {field}"
                }), 400
        
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                
                # Genera un nuovo UUID per l'investimento
                investment_id = str(uuid.uuid4())
                logger.info(f"Nuovo UUID investimento generato: {investment_id}")
                
                # Converti gli ID in stringhe UUID valide
                try:
                    user_id = str(uuid.UUID(data['user_id']))
                    logger.info(f"UUID user_id validato: {user_id}")
                except (ValueError, TypeError):
                    logger.error(f"UUID user_id non valido: {data['user_id']}")
                    return jsonify({
                        "status": "error",
                        "message": "Invalid user_id format"
                    }), 400
                
                try:
                    tournament_id = str(uuid.UUID(data['tournament_id']))
                    logger.info(f"UUID tournament_id validato: {tournament_id}")
                except (ValueError, TypeError):
                    logger.error(f"UUID tournament_id non valido: {data['tournament_id']}")
                    return jsonify({
                        "status": "error",
                        "message": "Invalid tournament_id format"
                    }), 400
                
                # Log dei parametri prima dell'esecuzione della query
                logger.info(f"Parametri query INSERT investments: id={investment_id}, user_id={user_id}, tournament_id={tournament_id}")
                
                # Inserisci il nuovo investimento
                cur.execute("""
                    INSERT INTO investments (id, user_id, tournament_id, amount, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (
                    investment_id,
                    user_id,
                    tournament_id,
                    data['amount'],
                    data.get('status', 'active'),
                    datetime.now()
                ))
                
                investment = cur.fetchone()
                cur.close()
                conn.close()
                
                # Converti UUID a stringa per JSON
                investment_dict = dict(investment)
                for key, value in investment_dict.items():
                    if isinstance(value, uuid.UUID):
                        investment_dict[key] = str(value)
                
                return jsonify({
                    "status": "success",
                    "message": "Investment created successfully",
                    "data": investment_dict
                }), 201
            except Exception as e:
                logger.error(f"Errore creazione investment: {str(e)}")
                logger.error(traceback.format_exc())
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": str(e)
                }), 500
        else:
            return jsonify({
                "status": "error",
                "message": "Database connection error"
            }), 500
    except Exception as e:
        logger.error(f"Errore endpoint create investment: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 3000)))
