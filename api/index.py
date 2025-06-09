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
supabase_url = os.environ.get('SUPABASE_URL')
supabase_key = os.environ.get('SUPABASE_KEY')

# Initialize Supabase client
supabase_client = None
if supabase_url and supabase_key:
    try:
        supabase_client = supabase.create_client(supabase_url, supabase_key)
        print(f"Supabase client initialized successfully with URL: {supabase_url}")
    except Exception as e:
        print(f"Supabase client initialization error: {str(e)}")

# Database connection function with improved SSL handling and connection format
def get_db_connection():
    try:
        # Prova prima con DATABASE_URL
        connection_string = DATABASE_URL
        # Se DATABASE_URL non è disponibile, prova con POSTGRES_URL
        if not connection_string:
            connection_string = POSTGRES_URL
            
        if not connection_string:
            print("No database connection string available")
            return None
        
        # Modifica il prefisso da postgresql:// a postgres:// se necessario
        if connection_string and connection_string.startswith('postgresql://'):
            connection_string = 'postgres://' + connection_string[14:]
            print("Modified connection string prefix from postgresql:// to postgres://")
        
        # Modifica la modalità SSL a 'allow' se non già specificata
        if '?' not in connection_string:
            connection_string += "?sslmode=allow"
        elif 'sslmode=' not in connection_string:
            connection_string += "&sslmode=allow"
        else:
            # Sostituisci qualsiasi modalità SSL esistente con 'allow'
            import re
            connection_string = re.sub(r'sslmode=\w+', 'sslmode=allow', connection_string)
            
        print(f"Attempting to connect with: {connection_string[:20]}... (SSL mode: allow)")
        
        # Parametri di connessione espliciti con timeout aumentato
        conn = psycopg2.connect(
            connection_string,
            connect_timeout=30,  # Aumentato a 30 secondi
            application_name="solcraft-backend"  # Nome dell'applicazione per il monitoraggio
        )
        conn.autocommit = True
        print("Database connection successful")
        return conn
    except Exception as e:
        print(f"Database connection error: {str(e)}")
        # Prova con connessione diretta se il pooler fallisce
        try:
            # Se stiamo usando il pooler e fallisce, prova con connessione diretta
            if "pooler" in connection_string:
                direct_conn_string = f"postgres://postgres:kCxBrdFOGbqEgtfs@db.zlainxopxrjgfphwjdvk.supabase.co:5432/postgres?sslmode=allow"
                print(f"Attempting direct connection: {direct_conn_string[:20]}...")
                conn = psycopg2.connect(
                    direct_conn_string,
                    connect_timeout=30,
                    application_name="solcraft-backend-direct"
                )
                conn.autocommit = True
                print("Direct database connection successful")
                return conn
        except Exception as direct_err:
            print(f"Direct database connection error: {str(direct_err)}")
        return None

# Initialize database tables if they don't exist
def initialize_database():
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
            print("Database initialized successfully")
        except Exception as e:
            print(f"Database initialization error: {str(e)}")
        finally:
            conn.close()

# Initialize database on startup
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
        print(f"Email error: {str(e)}")
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
                {"path": "/api/debug/env", "methods": ["GET"], "description": "Debug endpoint for environment variables"}
            ]
        })
    except Exception as e:
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
            "SUPABASE_URL": supabase_url,
            "SUPABASE_KEY": supabase_key[:10] + "..." if supabase_key else None,
            "JWT_SECRET": JWT_SECRET[:5] + "..." if JWT_SECRET else None,
            "SUPABASE_CLIENT_INITIALIZED": supabase_client is not None
        }
        
        # Tenta una connessione di test al database
        conn = get_db_connection()
        db_connection_success = conn is not None
        db_connection_message = "Database connection successful"
        
        if conn:
            try:
                # Verifica che la connessione funzioni eseguendo una query semplice
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
            except Exception as e:
                db_connection_message = f"Database connection established but query failed: {str(e)}"
            finally:
                conn.close()
        else:
            db_connection_message = "Database connection failed"
        
        return jsonify({
            "status": "success",
            "environment_variables": env_vars,
            "database_connection_test": {
                "success": db_connection_success,
                "message": db_connection_message
            },
            "server_info": {
                "python_version": os.environ.get("PYTHON_VERSION", "Unknown"),
                "vercel_region": os.environ.get("VERCEL_REGION", "Unknown"),
                "vercel_env": os.environ.get("VERCEL_ENV", "Unknown")
            }
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": "Error in debug endpoint",
            "error": str(e)
        }), 500

@app.route('/api/tournaments', methods=['GET'])
def get_tournaments():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM tournaments ORDER BY start_date DESC")
            tournaments = cur.fetchall()
            cur.close()
            conn.close()
            return jsonify({
                "status": "success",
                "data": tournaments
            })
        except Exception as e:
            conn.close()
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    else:
        # Fallback to sample data if database connection fails
        return jsonify({
            "status": "success",
            "data": sample_tournaments,
            "note": "Using sample data due to database connection issue"
        })

@app.route('/api/tournaments/<int:tournament_id>', methods=['GET'])
def get_tournament(tournament_id):
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
                return jsonify({
                    "status": "success",
                    "data": tournament
                })
            else:
                cur.close()
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": "Tournament not found"
                }), 404
        except Exception as e:
            conn.close()
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    else:
        # Fallback to sample data
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
    data = request.json
    required_fields = ['name', 'organizer', 'buy_in', 'prize_pool', 'start_date']
    
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
            
            return jsonify({
                "status": "success",
                "message": "Tournament created successfully",
                "data": new_tournament
            }), 201
        except Exception as e:
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

@app.route('/api/investments', methods=['POST'])
def create_investment():
    data = request.json
    required_fields = ['user_id', 'tournament_id', 'amount', 'share_percentage']
    
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
            
            # Check if tournament exists
            cur.execute("SELECT * FROM tournaments WHERE id = %s", (data['tournament_id'],))
            tournament = cur.fetchone()
            
            if not tournament:
                cur.close()
                conn.close()
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
            
            return jsonify({
                "status": "success",
                "message": "Investment created successfully",
                "data": new_investment
            }), 201
        except Exception as e:
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

@app.route('/api/users/register', methods=['POST'])
def register_user():
    data = request.json
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
            
            # Check if username already exists
            cur.execute("SELECT * FROM users WHERE username = %s", (data['username'],))
            if cur.fetchone():
                cur.close()
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": "Username already exists"
                }), 400
            
            # Check if email already exists
            cur.execute("SELECT * FROM users WHERE email = %s", (data['email'],))
            if cur.fetchone():
                cur.close()
                conn.close()
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
            
            return jsonify({
                "status": "success",
                "message": "User registered successfully",
                "data": {
                    "user": new_user,
                    "token": token
                }
            }), 201
        except Exception as e:
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

@app.route('/api/users/login', methods=['POST'])
def login_user():
    data = request.json
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
            
            # Check if user exists
            cur.execute("SELECT * FROM users WHERE email = %s", (data['email'],))
            user = cur.fetchone()
            
            if not user:
                cur.close()
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": "Invalid email or password"
                }), 401
            
            # Check password
            password_hash = hash_password(data['password'])
            if password_hash != user['password_hash']:
                cur.close()
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": "Invalid email or password"
                }), 401
            
            # Generate token
            token = generate_token(user['id'])
            
            cur.close()
            conn.close()
            
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
