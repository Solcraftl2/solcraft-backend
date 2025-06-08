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
supabase_url = os.environ.get('SUPABASE_URL')
supabase_key = os.environ.get('SUPABASE_KEY')

# Initialize Supabase client
supabase_client = supabase.create_client(supabase_url, supabase_key)

# Database connection function
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"Database connection error: {str(e)}")
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
    return jsonify({
        "status": "success",
        "message": "SolCraft API is running",
        "version": "1.0.0"
    })

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
            
            # Check if username or email already exists
            cur.execute("SELECT * FROM users WHERE username = %s OR email = %s", 
                       (data['username'], data['email']))
            existing_user = cur.fetchone()
            
            if existing_user:
                cur.close()
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": "Username or email already exists"
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
                data.get('wallet_address', None)
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
    
    if 'email' not in data or 'password' not in data:
        return jsonify({
            "status": "error",
            "message": "Email and password are required"
        }), 400
    
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Find user by email
            cur.execute("SELECT * FROM users WHERE email = %s", (data['email'],))
            user = cur.fetchone()
            
            if not user:
                cur.close()
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": "Invalid email or password"
                }), 401
            
            # Verify password
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
            
            # Remove password hash from response
            del user['password_hash']
            
            cur.close()
            conn.close()
            
            return jsonify({
                "status": "success",
                "message": "Login successful",
                "data": {
                    "user": user,
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

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get total tournaments
            cur.execute("SELECT COUNT(*) as total_tournaments FROM tournaments")
            total_tournaments = cur.fetchone()['total_tournaments']
            
            # Get total users
            cur.execute("SELECT COUNT(*) as total_users FROM users")
            total_users = cur.fetchone()['total_users']
            
            # Get total investments
            cur.execute("SELECT SUM(amount) as total_volume FROM investments")
            result = cur.fetchone()
            total_volume = result['total_volume'] if result['total_volume'] else 0
            
            # Get success rate (completed tournaments / total tournaments)
            cur.execute("SELECT COUNT(*) as completed FROM tournaments WHERE status = 'completed'")
            completed = cur.fetchone()['completed']
            success_rate = (completed / total_tournaments * 100) if total_tournaments > 0 else 0
            
            cur.close()
            conn.close()
            
            return jsonify({
                "status": "success",
                "data": {
                    "tournaments": total_tournaments,
                    "users": total_users,
                    "volume": total_volume,
                    "success_rate": success_rate
                }
            })
        except Exception as e:
            conn.close()
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    else:
        # Fallback to sample stats
        return jsonify({
            "status": "success",
            "data": {
                "tournaments": 12,
                "users": 1247,
                "volume": 45678,
                "success_rate": 94
            },
            "note": "Using sample data due to database connection issue"
        })

# Health check endpoint
@app.route('/api/health', methods=['GET'])
def health_check():
    # Check database connection
    db_status = "connected" if get_db_connection() else "disconnected"
    
    return jsonify({
        "status": "success",
        "data": {
            "api": "healthy",
            "database": db_status,
            "timestamp": datetime.utcnow().isoformat()
        }
    })

if __name__ == '__main__':
    app.run(debug=True)
