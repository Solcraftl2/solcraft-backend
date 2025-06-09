from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
from datetime import datetime, timedelta
import jwt
import hashlib
import smtplib
import psycopg2
from psycopg2.extras import RealDictCursor
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import supabase
import traceback
import logging

# Configurazione logging avanzato
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('solcraft-backend')

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

# Initialize database tables if they don't exist
def initialize_database():
    logger.info("Inizializzazione database...")
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            # Create users table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    wallet_address VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create tournaments table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS tournaments (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    organizer VARCHAR(100) NOT NULL,
                    buy_in NUMERIC NOT NULL,
                    prize_pool NUMERIC NOT NULL,
                    start_date TIMESTAMP NOT NULL,
                    end_date TIMESTAMP,
                    status VARCHAR(50) DEFAULT 'upcoming',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create investments table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS investments (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    tournament_id INTEGER REFERENCES tournaments(id),
                    amount NUMERIC NOT NULL,
                    share_percentage NUMERIC NOT NULL,
                    status VARCHAR(50) DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create organizers table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS organizers (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    wallet_address VARCHAR(255),
                    verified BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cur.close()
            logger.info("Database inizializzato con successo")
        except Exception as e:
            logger.error(f"Errore inizializzazione database: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            conn.close()
    else:
        logger.error("Impossibile inizializzare il database: connessione fallita")

# Initialize database on startup
logger.info("Avvio inizializzazione database...")
initialize_database()

# Sample data for testing
sample_tournaments = [
    {
        "id": 1,
        "name": "Sunday Million",
        "organizer": "PokerPro",
        "buy_in": 215,
        "prize_pool": 1000000,
        "start_date": "2023-06-04T18:00:00Z",
        "status": "completed"
    },
    {
        "id": 2,
        "name": "High Roller",
        "organizer": "CryptoPoker",
        "buy_in": 1050,
        "prize_pool": 500000,
        "start_date": "2023-06-11T20:00:00Z",
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
        return jsonify({
            "status": "success",
            "message": "SolCraft API is running",
            "version": "1.0.0"
        })
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
            direct_conn_string = "postgres://postgres:kCxBrdFOGbqEgtfs@db.zlainxopxrjgfphwjdvk.supabase.co:5432/postgres?sslmode=disable"
            start_time = datetime.now()
            conn = psycopg2.connect(
                direct_conn_string,
                connect_timeout=30,
                application_name="solcraft-test-direct-disable"
            )
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # Test query
            cur = conn.cursor()
            cur.execute("SELECT current_database(), current_user, version()")
            db_info = cur.fetchone()
            cur.close()
            conn.close()
            
            results.append({
                "type": "direct_hardcoded_ssl_disable",
                "success": True,
                "duration_seconds": duration,
                "database": db_info[0],
                "user": db_info[1],
                "version": db_info[2]
            })
        except Exception as e:
            results.append({
                "type": "direct_hardcoded_ssl_disable",
                "success": False,
                "error": str(e)
            })
        
        # Test 2: Connessione diretta hardcoded con SSL allow
        try:
            direct_conn_string = "postgres://postgres:kCxBrdFOGbqEgtfs@db.zlainxopxrjgfphwjdvk.supabase.co:5432/postgres?sslmode=allow"
            start_time = datetime.now()
            conn = psycopg2.connect(
                direct_conn_string,
                connect_timeout=30,
                application_name="solcraft-test-direct-allow"
            )
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # Test query
            cur = conn.cursor()
            cur.execute("SELECT current_database(), current_user, version()")
            db_info = cur.fetchone()
            cur.close()
            conn.close()
            
            results.append({
                "type": "direct_hardcoded_ssl_allow",
                "success": True,
                "duration_seconds": duration,
                "database": db_info[0],
                "user": db_info[1],
                "version": db_info[2]
            })
        except Exception as e:
            results.append({
                "type": "direct_hardcoded_ssl_allow",
                "success": False,
                "error": str(e)
            })
        
        # Test 3: Connessione con POSTGRES_URL_NON_POOLING
        if POSTGRES_URL_NON_POOLING:
            try:
                start_time = datetime.now()
                conn = psycopg2.connect(
                    POSTGRES_URL_NON_POOLING,
                    connect_timeout=30,
                    application_name="solcraft-test-non-pooling"
                )
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                # Test query
                cur = conn.cursor()
                cur.execute("SELECT current_database(), current_user, version()")
                db_info = cur.fetchone()
                cur.close()
                conn.close()
                
                results.append({
                    "type": "postgres_url_non_pooling",
                    "success": True,
                    "duration_seconds": duration,
                    "database": db_info[0],
                    "user": db_info[1],
                    "version": db_info[2]
                })
            except Exception as e:
                results.append({
                    "type": "postgres_url_non_pooling",
                    "success": False,
                    "error": str(e)
                })
        
        # Test 4: Connessione con POSTGRES_URL
        if POSTGRES_URL:
            try:
                start_time = datetime.now()
                conn = psycopg2.connect(
                    POSTGRES_URL,
                    connect_timeout=30,
                    application_name="solcraft-test-pooling"
                )
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                # Test query
                cur = conn.cursor()
                cur.execute("SELECT current_database(), current_user, version()")
                db_info = cur.fetchone()
                cur.close()
                conn.close()
                
                results.append({
                    "type": "postgres_url_pooling",
                    "success": True,
                    "duration_seconds": duration,
                    "database": db_info[0],
                    "user": db_info[1],
                    "version": db_info[2]
                })
            except Exception as e:
                results.append({
                    "type": "postgres_url_pooling",
                    "success": False,
                    "error": str(e)
                })
        
        # Test 5: Connessione con DATABASE_URL
        if DATABASE_URL:
            try:
                start_time = datetime.now()
                conn = psycopg2.connect(
                    DATABASE_URL,
                    connect_timeout=30,
                    application_name="solcraft-test-database-url"
                )
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                # Test query
                cur = conn.cursor()
                cur.execute("SELECT current_database(), current_user, version()")
                db_info = cur.fetchone()
                cur.close()
                conn.close()
                
                results.append({
                    "type": "database_url",
                    "success": True,
                    "duration_seconds": duration,
                    "database": db_info[0],
                    "user": db_info[1],
                    "version": db_info[2]
                })
            except Exception as e:
                results.append({
                    "type": "database_url",
                    "success": False,
                    "error": str(e)
                })
        
        return jsonify({
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "connection_tests": results,
            "environment": {
                "vercel_region": os.environ.get("VERCEL_REGION", "Unknown"),
                "vercel_env": os.environ.get("VERCEL_ENV", "Unknown")
            }
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
    logger.info("Richiesta GET /api/tournaments")
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM tournaments ORDER BY start_date DESC")
            tournaments = cur.fetchall()
            cur.close()
            conn.close()
            logger.info(f"GET /api/tournaments: restituiti {len(tournaments)} tornei dal database")
            return jsonify({
                "status": "success",
                "data": tournaments
            })
        except Exception as e:
            logger.error(f"Errore GET /api/tournaments: {str(e)}")
            logger.error(traceback.format_exc())
            conn.close()
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    else:
        # Fallback to sample data if database connection fails
        logger.warning("GET /api/tournaments: connessione al database fallita, utilizzo dati di esempio")
        return jsonify({
            "status": "success",
            "data": sample_tournaments,
            "note": "Using sample data due to database connection issue"
        })

@app.route('/api/tournaments/<int:tournament_id>', methods=['GET'])
def get_tournament(tournament_id):
    logger.info(f"Richiesta GET /api/tournaments/{tournament_id}")
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM tournaments WHERE id = %s", (tournament_id,))
            tournament = cur.fetchone()
            
            if tournament:
                # Get investments for this tournament
                cur.execute("""
                    SELECT i.*, u.username 
                    FROM investments i 
                    JOIN users u ON i.user_id = u.id 
                    WHERE i.tournament_id = %s
                """, (tournament_id,))
                investments = cur.fetchall()
                tournament['investments'] = investments
                
                cur.close()
                conn.close()
                logger.info(f"GET /api/tournaments/{tournament_id}: torneo trovato con {len(tournament.get('investments', [])) if tournament.get('investments') else 0} investimenti")
                return jsonify({
                    "status": "success",
                    "data": tournament
                })
            else:
                cur.close()
                conn.close()
                logger.warning(f"GET /api/tournaments/{tournament_id}: torneo non trovato")
                return jsonify({
                    "status": "error",
                    "message": "Tournament not found"
                }), 404
        except Exception as e:
            logger.error(f"Errore GET /api/tournaments/{tournament_id}: {str(e)}")
            logger.error(traceback.format_exc())
            conn.close()
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    else:
        # Fallback to sample data
        logger.warning(f"GET /api/tournaments/{tournament_id}: connessione al database fallita, utilizzo dati di esempio")
        tournament = next((t for t in sample_tournaments if t["id"] == tournament_id), None)
        if tournament:
            return jsonify({
                "status": "success",
                "data": tournament,
                "note": "Using sample data due to database connection issue"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Tournament not found"
            }), 404

@app.route('/api/tournaments', methods=['POST'])
def create_tournament():
    logger.info("Richiesta POST /api/tournaments")
    data = request.json
    required_fields = ['name', 'organizer', 'buy_in', 'prize_pool', 'start_date']
    
    for field in required_fields:
        if field not in data:
            logger.warning(f"POST /api/tournaments: campo richiesto mancante: {field}")
            return jsonify({
                "status": "error",
                "message": f"Missing required field: {field}"
            }), 400
    
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                INSERT INTO tournaments (name, organizer, buy_in, prize_pool, start_date, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                data['name'],
                data['organizer'],
                data['buy_in'],
                data['prize_pool'],
                data['start_date'],
                data.get('status', 'upcoming')
            ))
            
            new_tournament = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
            
            logger.info(f"POST /api/tournaments: torneo creato con successo, ID: {new_tournament['id']}")
            return jsonify({
                "status": "success",
                "message": "Tournament created successfully",
                "data": new_tournament
            }), 201
        except Exception as e:
            logger.error(f"Errore POST /api/tournaments: {str(e)}")
            logger.error(traceback.format_exc())
            conn.close()
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    else:
        logger.error("POST /api/tournaments: connessione al database fallita")
        return jsonify({
            "status": "error",
            "message": "Database connection error"
        }), 500

@app.route('/api/investments', methods=['POST'])
def create_investment():
    logger.info("Richiesta POST /api/investments")
    data = request.json
    required_fields = ['user_id', 'tournament_id', 'amount', 'share_percentage']
    
    for field in required_fields:
        if field not in data:
            logger.warning(f"POST /api/investments: campo richiesto mancante: {field}")
            return jsonify({
                "status": "error",
                "message": f"Missing required field: {field}"
            }), 400
    
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Check if tournament exists
            cur.execute("SELECT * FROM tournaments WHERE id = %s", (data['tournament_id'],))
            tournament = cur.fetchone()
            
            if not tournament:
                cur.close()
                conn.close()
                logger.warning(f"POST /api/investments: torneo non trovato, ID: {data['tournament_id']}")
                return jsonify({
                    "status": "error",
                    "message": "Tournament not found"
                }), 404
            
            # Check if user exists
            cur.execute("SELECT * FROM users WHERE id = %s", (data['user_id'],))
            user = cur.fetchone()
            
            if not user:
                cur.close()
                conn.close()
                logger.warning(f"POST /api/investments: utente non trovato, ID: {data['user_id']}")
                return jsonify({
                    "status": "error",
                    "message": "User not found"
                }), 404
            
            # Create investment
            cur.execute("""
                INSERT INTO investments (user_id, tournament_id, amount, share_percentage, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            """, (
                data['user_id'],
                data['tournament_id'],
                data['amount'],
                data['share_percentage'],
                data.get('status', 'active')
            ))
            
            new_investment = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
            
            logger.info(f"POST /api/investments: investimento creato con successo, ID: {new_investment['id']}")
            return jsonify({
                "status": "success",
                "message": "Investment created successfully",
                "data": new_investment
            }), 201
        except Exception as e:
            logger.error(f"Errore POST /api/investments: {str(e)}")
            logger.error(traceback.format_exc())
            conn.close()
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    else:
        logger.error("POST /api/investments: connessione al database fallita")
        return jsonify({
            "status": "error",
            "message": "Database connection error"
        }), 500

@app.route('/api/users/register', methods=['POST'])
def register_user():
    logger.info("Richiesta POST /api/users/register")
    data = request.json
    required_fields = ['username', 'email', 'password']
    
    for field in required_fields:
        if field not in data:
            logger.warning(f"POST /api/users/register: campo richiesto mancante: {field}")
            return jsonify({
                "status": "error",
                "message": f"Missing required field: {field}"
            }), 400
    
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Check if username already exists
            cur.execute("SELECT * FROM users WHERE username = %s", (data['username'],))
            if cur.fetchone():
                cur.close()
                conn.close()
                logger.warning(f"POST /api/users/register: username già esistente: {data['username']}")
                return jsonify({
                    "status": "error",
                    "message": "Username already exists"
                }), 400
            
            # Check if email already exists
            cur.execute("SELECT * FROM users WHERE email = %s", (data['email'],))
            if cur.fetchone():
                cur.close()
                conn.close()
                logger.warning(f"POST /api/users/register: email già esistente: {data['email']}")
                return jsonify({
                    "status": "error",
                    "message": "Email already exists"
                }), 400
            
            # Create user
            password_hash = hash_password(data['password'])
            cur.execute("""
                INSERT INTO users (username, email, password_hash, wallet_address)
                VALUES (%s, %s, %s, %s)
                RETURNING id, username, email, wallet_address, created_at
            """, (
                data['username'],
                data['email'],
                password_hash,
                data.get('wallet_address')
            ))
            
            new_user = cur.fetchone()
            conn.commit()
            
            # Generate token
            token = generate_token(new_user['id'])
            
            cur.close()
            conn.close()
            
            logger.info(f"POST /api/users/register: utente registrato con successo, ID: {new_user['id']}")
            return jsonify({
                "status": "success",
                "message": "User registered successfully",
                "data": {
                    "user": new_user,
                    "token": token
                }
            }), 201
        except Exception as e:
            logger.error(f"Errore POST /api/users/register: {str(e)}")
            logger.error(traceback.format_exc())
            conn.close()
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    else:
        logger.error("POST /api/users/register: connessione al database fallita")
        return jsonify({
            "status": "error",
            "message": "Database connection error"
        }), 500

@app.route('/api/users/login', methods=['POST'])
def login_user():
    logger.info("Richiesta POST /api/users/login")
    data = request.json
    required_fields = ['email', 'password']
    
    for field in required_fields:
        if field not in data:
            logger.warning(f"POST /api/users/login: campo richiesto mancante: {field}")
            return jsonify({
                "status": "error",
                "message": f"Missing required field: {field}"
            }), 400
    
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Check if user exists
            cur.execute("SELECT * FROM users WHERE email = %s", (data['email'],))
            user = cur.fetchone()
            
            if not user:
                cur.close()
                conn.close()
                logger.warning(f"POST /api/users/login: email non trovata: {data['email']}")
                return jsonify({
                    "status": "error",
                    "message": "Invalid email or password"
                }), 401
            
            # Check password
            password_hash = hash_password(data['password'])
            if password_hash != user['password_hash']:
                cur.close()
                conn.close()
                logger.warning(f"POST /api/users/login: password errata per email: {data['email']}")
                return jsonify({
                    "status": "error",
                    "message": "Invalid email or password"
                }), 401
            
            # Generate token
            token = generate_token(user['id'])
            
            cur.close()
            conn.close()
            
            logger.info(f"POST /api/users/login: login riuscito, ID utente: {user['id']}")
            return jsonify({
                "status": "success",
                "message": "Login successful",
                "data": {
                    "user": {
                        "id": user['id'],
                        "username": user['username'],
                        "email": user['email'],
                        "wallet_address": user['wallet_address'],
                        "created_at": user['created_at']
                    },
                    "token": token
                }
            })
        except Exception as e:
            logger.error(f"Errore POST /api/users/login: {str(e)}")
            logger.error(traceback.format_exc())
            conn.close()
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    else:
        logger.error("POST /api/users/login: connessione al database fallita")
        return jsonify({
            "status": "error",
            "message": "Database connection error"
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
