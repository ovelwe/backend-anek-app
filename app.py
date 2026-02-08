import os
import datetime
import random
import jwt
import bleach
from flask import Flask, request, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

db_url = os.getenv('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-key-for-dev')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:5173')
CORS(app, resources={r"/*": {"origins": [frontend_url]}}, supports_credentials=True)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

class Users(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column('password_hash', db.String(255), nullable=False)

class Jokes(db.Model):
    __tablename__ = 'jokes'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    author_name = db.Column('author_id', db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    comments = db.relationship('Comment', backref='joke_ref', lazy=True, cascade="all, delete-orphan")

class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(255), nullable=False)
    author_username = db.Column(db.String(50))
    joke_id = db.Column(db.Integer, db.ForeignKey('jokes.id'), nullable=False)

class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(500), nullable=False)
    author_username = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)

def token_required(f):
    def decorated(*args, **kwargs):
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'message': 'Unauthorized'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = Users.query.get(data['user_id'])
            if not current_user:
                raise Exception()
        except:
            return jsonify({'message': 'Invalid session'}), 401
        return f(current_user, *args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'message': 'Missing data'}), 400
    if Users.query.filter_by(username=data['username']).first():
        return jsonify({'message': 'Username taken'}), 400
    hashed = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    new_user = Users(username=data['username'], password=hashed)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({'message': 'OK'}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user = Users.query.filter_by(username=data['username']).first()
    if user and bcrypt.check_password_hash(user.password, data['password']):
        token = jwt.encode({
            'user_id': user.id,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, app.config['SECRET_KEY'], algorithm="HS256")
        resp = make_response(jsonify({'username': user.username, 'message': 'OK'}))
        is_prod = os.getenv('RAILWAY_ENVIRONMENT') is not None
        resp.set_cookie(
            'session_token',
            token,
            httponly=True,
            samesite='None' if is_prod else 'Lax',
            secure=True if is_prod else False,
            max_age=86400
        )
        return resp
    return jsonify({'message': 'Login failed'}), 401

@app.route('/logout', methods=['POST'])
def logout():
    resp = make_response(jsonify({'message': 'Logged out'}))
    is_prod = os.getenv('RAILWAY_ENVIRONMENT') is not None
    resp.set_cookie(
        'session_token',
        '',
        expires=0,
        httponly=True,
        samesite='None' if is_prod else 'Lax',
        secure=True if is_prod else False
    )
    return resp

@app.route('/joke/random', methods=['GET'])
def get_random():
    jokes_list = Jokes.query.all()
    if not jokes_list:
        return jsonify({'id': 0, 'content': 'Шуток пока нет', 'author': 'System', 'comments': []})
    j = random.choice(jokes_list)
    return jsonify({
        'id': j.id,
        'content': j.content,
        'author': j.author_name,
        'comments': [{'text': c.text, 'author_username': c.author_username} for c in j.comments]
    })

@app.route('/joke/add', methods=['POST'])
@token_required
def add_joke(current_user):
    data = request.json
    clean = bleach.clean(data.get('content', ''))[:500]
    new_joke = Jokes(content=clean, author_name=current_user.username)
    db.session.add(new_joke)
    db.session.commit()
    return jsonify({'id': new_joke.id}), 201

@app.route('/joke/<int:joke_id>/comment', methods=['POST'])
@token_required
def add_comment(current_user, joke_id):
    data = request.json
    clean = bleach.clean(data.get('text', ''))[:255]
    new_comment = Comment(text=clean, author_username=current_user.username, joke_id=joke_id)
    db.session.add(new_comment)
    db.session.commit()
    return jsonify({'message': 'OK'}), 201

@app.route('/chat', methods=['GET'])
def get_chat():
    messages = ChatMessage.query.order_by(ChatMessage.timestamp.desc()).limit(50).all()
    return jsonify([
        {
            'text': m.text,
            'author': m.author_username,
            'time': m.timestamp.strftime('%H:%M')
        } for m in reversed(messages)
    ])

@app.route('/chat', methods=['POST'])
@token_required
def send_chat(current_user):
    data = request.json
    clean = bleach.clean(data.get('text', ''))[:500]
    new_msg = ChatMessage(text=clean, author_username=current_user.username)
    db.session.add(new_msg)
    db.session.commit()
    return jsonify({'message': 'Sent'}), 201

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)