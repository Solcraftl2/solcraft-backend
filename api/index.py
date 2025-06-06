from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
from datetime import datetime, timedelta
import jwt
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)

# Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'your-secret-key')
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')

# Mock database (in production, use PostgreSQL)
users_db = {}
tournaments_db = {}
investments_db = {}
organizers_db = {}

# Sample data
sample_tournaments = [
    {
        "id": 1,
        "name": "Sunday Million",
        "organizer": "PokerPro",
        "buyIn": 215,
        "prizePool": 1000000,
        "startTime": "2025-06-08T20:00:00Z",
        "status": "upcoming",
        "participants": 4500,
        "maxParticipants": 5000,
        "investmentPool": 250000,
        "minInvestment": 100,
        "expectedROI": 18.5,
        "riskLevel": "medium",
        "organizerRating": 4.8,
    },
    {
        "id": 2,
        "name": "High Roller Championship",
        "organizer": "ChampionAce",
        "buyIn": 5000,
        "prizePool": 2500000,
        "startTime": "2025-06-10T18:00:00Z",
        "status": "upcoming",
        "participants": 450,
        "maxParticipants": 500,
        "investmentPool": 500000,
        "minInvestment": 500,
        "expectedROI": 25.2,
        "riskLevel": "high",
        "organizerRating": 4.9,
    },
    {
        "id": 3,
        "name": "Daily Grind Series",
        "organizer": "TourneyKing",
        "buyIn": 55,
        "prizePool": 100000,
        "startTime": "2025-06-07T19:00:00Z",
        "status": "live",
        "participants": 1800,
        "maxParticipants": 2000,
        "investmentPool": 75000,
        "minInvestment": 50,
        "expectedROI": 12.8,
        "riskLevel": "low",
        "organizerRating": 4.6,
    }
]

sample_investments = [
    {
        "id": 1,
        "tournament": "Sunday Million",
        "organizer": "PokerPro",
        "amount": 1500,
        "investmentDate": "2025-06-01T10:00:00Z",
        "status": "active",
        "currentValue": 1650,
        "roi": 10.0,
        "expectedPayout": "2025-06-08T23:00:00Z",
        "riskLevel": "medium",
    },
    {
        "id": 2,
        "tournament": "High Roller Championship",
        "organizer": "ChampionAce",
        "amount": 5000,
        "investmentDate": "2025-05-28T14:30:00Z",
        "status": "active",
        "currentValue": 5750,
        "roi": 15.0,
        "expectedPayout": "2025-06-10T22:00:00Z",
        "riskLevel": "high",
    }
]

# Initialize sample data
tournaments_db.update({str(t["id"]): t for t in sample_tournaments})
investments_db.update({str(i["id"]): i for i in sample_investments})

def send_email(to_email, subject, body):
    """Send email notification"""
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

def generate_token(user_data):
    """Generate JWT token"""
    payload = {
        'user_id': user_data['id'],
        'wallet_address': user_data['wallet_address'],
        'exp': datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def verify_token(token):
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# Routes
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})

@app.route('/api/auth/connect', methods=['POST'])
def connect_wallet():
    data = request.get_json()
    wallet_address = data.get('wallet_address')
    
    if not wallet_address:
        return jsonify({"error": "Wallet address required"}), 400
    
    # Check if user exists
    user = users_db.get(wallet_address)
    if not user:
        # Create new user
        user = {
            "id": len(users_db) + 1,
            "wallet_address": wallet_address,
            "username": f"User{len(users_db) + 1}",
            "email": "",
            "portfolioValue": 25430,
            "totalInvested": 22500,
            "totalROI": 13.02,
            "isOrganizer": False,
            "joinedDate": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat()
        }
        users_db[wallet_address] = user
    
    token = generate_token(user)
    return jsonify({
        "token": token,
        "user": user,
        "message": "Wallet connected successfully"
    })

@app.route('/api/tournaments', methods=['GET'])
def get_tournaments():
    return jsonify({
        "tournaments": list(tournaments_db.values()),
        "total": len(tournaments_db)
    })

@app.route('/api/tournaments', methods=['POST'])
def create_tournament():
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['name', 'buyIn', 'prizePool', 'startDate', 'startTime', 'maxParticipants']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400
    
    tournament_id = len(tournaments_db) + 1
    tournament = {
        "id": tournament_id,
        "name": data['name'],
        "description": data.get('description', ''),
        "organizer": "Current User",  # In production, get from auth token
        "buyIn": data['buyIn'],
        "prizePool": data['prizePool'],
        "startTime": f"{data['startDate']}T{data['startTime']}:00Z",
        "status": "upcoming",
        "participants": 0,
        "maxParticipants": data['maxParticipants'],
        "investmentPool": data.get('investmentPool', 0),
        "minInvestment": data.get('minInvestment', 50),
        "expectedROI": data.get('expectedROI', 15),
        "riskLevel": data.get('riskLevel', 'medium'),
        "organizerRating": 4.5,
        "collateralLock": data.get('collateralLock', 0),
        "created_at": datetime.utcnow().isoformat()
    }
    
    tournaments_db[str(tournament_id)] = tournament
    
    return jsonify({
        "tournament": tournament,
        "message": "Tournament created successfully"
    }), 201

@app.route('/api/investments', methods=['GET'])
def get_investments():
    return jsonify({
        "investments": list(investments_db.values()),
        "total": len(investments_db)
    })

@app.route('/api/investments', methods=['POST'])
def create_investment():
    data = request.get_json()
    
    tournament_id = data.get('tournament_id')
    amount = data.get('amount')
    
    if not tournament_id or not amount:
        return jsonify({"error": "Tournament ID and amount required"}), 400
    
    tournament = tournaments_db.get(str(tournament_id))
    if not tournament:
        return jsonify({"error": "Tournament not found"}), 404
    
    if amount < tournament['minInvestment']:
        return jsonify({"error": f"Minimum investment is ${tournament['minInvestment']}"}), 400
    
    investment_id = len(investments_db) + 1
    investment = {
        "id": investment_id,
        "tournament": tournament['name'],
        "organizer": tournament['organizer'],
        "amount": amount,
        "investmentDate": datetime.utcnow().isoformat(),
        "status": "active",
        "currentValue": amount,
        "roi": 0.0,
        "expectedPayout": tournament['startTime'],
        "riskLevel": tournament['riskLevel'],
        "created_at": datetime.utcnow().isoformat()
    }
    
    investments_db[str(investment_id)] = investment
    
    return jsonify({
        "investment": investment,
        "message": "Investment created successfully"
    }), 201

@app.route('/api/organizers/apply', methods=['POST'])
def apply_organizer():
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['fullName', 'pokerExperience', 'pokerCredentials', 'organizerExperience', 'collateralAmount']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400
    
    application_id = len(organizers_db) + 1
    application = {
        "id": application_id,
        "fullName": data['fullName'],
        "pokerExperience": data['pokerExperience'],
        "pokerCredentials": data['pokerCredentials'],
        "organizerExperience": data['organizerExperience'],
        "collateralAmount": data['collateralAmount'],
        "status": "pending",
        "submittedAt": datetime.utcnow().isoformat(),
        "reviewedAt": None,
        "reviewNotes": ""
    }
    
    organizers_db[str(application_id)] = application
    
    # Send confirmation email (if configured)
    if SMTP_USER and SMTP_PASS:
        email_body = f"""
        <h2>Organizer Application Received</h2>
        <p>Dear {data['fullName']},</p>
        <p>Thank you for applying to become a tournament organizer on SolCraft.</p>
        <p>Your application has been received and is currently under review.</p>
        <p>We will contact you within 24-48 hours with the results.</p>
        <p>Best regards,<br>SolCraft Team</p>
        """
        send_email("applicant@example.com", "SolCraft Organizer Application Received", email_body)
    
    return jsonify({
        "application": application,
        "message": "Application submitted successfully"
    }), 201

@app.route('/api/dashboard/stats', methods=['GET'])
def get_dashboard_stats():
    total_tournaments = len(tournaments_db)
    total_investments = len(investments_db)
    total_volume = sum(t['prizePool'] for t in tournaments_db.values())
    active_tournaments = len([t for t in tournaments_db.values() if t['status'] == 'live'])
    
    return jsonify({
        "totalTournaments": total_tournaments,
        "totalInvestments": total_investments,
        "totalVolume": total_volume,
        "activeTournaments": active_tournaments,
        "portfolioValue": 25430,
        "totalROI": 13.02,
        "liquidityPool": 547800000,
        "volume24h": 547800000
    })

@app.route('/api/admin/dashboard', methods=['GET'])
def admin_dashboard():
    return jsonify({
        "users": len(users_db),
        "tournaments": len(tournaments_db),
        "investments": len(investments_db),
        "organizers": len(organizers_db),
        "totalVolume": sum(t['prizePool'] for t in tournaments_db.values()),
        "revenue": sum(t['prizePool'] * 0.05 for t in tournaments_db.values()),
        "status": "operational"
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

