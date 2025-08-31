import os
import io
import pandas as pd
from flask import Flask, render_template, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_cors import CORS

# --- CONFIGURACIÓN INICIAL ---
app = Flask(__name__)
CORS(app, supports_credentials=True)
app.config['SECRET_KEY'] = 'una-clave-secreta-muy-dificil-de-adivinar'

# --- CONFIGURACIÓN DE LA BASE DE DATOS PARA RENDER ---
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- CONFIGURACIÓN DE FLASK-LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.unauthorized_handler
def unauthorized():
    return jsonify({'status': 'error', 'message': 'Se requiere autenticación'}), 401

# --- MODELOS DE LA BASE DE DATOS (Sin cambios) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(80), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class Pago(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    apartamento = db.Column(db.String(10), nullable=False)
    fecha_pago = db.Column(db.Date, nullable=False)
    mes_cancelado = db.Column(db.String(20), nullable=False)
    monto_usd = db.Column(db.Float, default=0.0)
    monto_bs = db.Column(db.Float, default=0.0)
    forma_pago = db.Column(db.String(50), nullable=False)
    referencia = db.Column(db.String(100), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)
    registrado_por = db.Column(db.String(80))

    def to_dict(self):
        return {
            'id': self.id, 'apartamento': self.apartamento,
            'fecha_pago': self.fecha_pago.strftime('%Y-%m-%d'),
            'mes_cancelado': self.mes_cancelado, 'monto_usd': self.monto_usd,
            'monto_bs': self.monto_bs, 'forma_pago': self.forma_pago,
            'referencia': self.referencia, 'observaciones': self.observaciones,
            'registrado_por': self.registrado_por
        }

class Gasto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha_gasto = db.Column(db.Date, nullable=False)
    descripcion = db.Column(db.String(200), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    proveedor = db.Column(db.String(100), nullable=True)
    factura = db.Column(db.String(100), nullable=True)
    registrado_por = db.Column(db.String(80))

    def to_dict(self):
        return {
            'id': self.id, 'fecha_gasto': self.fecha_gasto.strftime('%Y-%m-%d'),
            'descripcion': self.descripcion, 'monto': self.monto,
            'proveedor': self.proveedor, 'factura': self.factura,
            'registrado_por': self.registrado_por
        }

# --- RUTAS (Sin cambios) ---
@app.route("/api/login", methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user and user.check_password(data['password']):
        login_user(user)
        return jsonify({'status': 'success', 'username': user.username, 'role': user.role})
    return jsonify({'status': 'error', 'message': 'Usuario o contraseña incorrectos'}), 401

@app.route("/api/logout")
@login_required
def logout():
    logout_user()
    return jsonify({'status': 'success'})

@app.route("/api/check_session")
def check_session():
    if current_user.is_authenticated:
        return jsonify({'logged_in': True, 'username': current_user.username, 'role': current_user.role})
    return jsonify({'logged_in': False})

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/pagos", methods=['POST', 'GET'])
@login_required
def handle_pagos():
    if request.method == 'POST':
        datos = request.json
        fecha_pago_obj = datetime.strptime(datos['payment-date'], '%Y-%m-%d').date()
        nuevo_pago = Pago(
            apartamento=datos['apto'], fecha_pago=fecha_pago_obj,
            mes_cancelado=datos['month-paid'], monto_usd=float(datos.get('amount-usd') or 0),
            monto_bs=float(datos.get('amount-bs') or 0), forma_pago=datos['payment-method'],
            referencia=datos.get('reference-number'), observaciones=datos.get('observations'),
            registrado_por=current_user.username
        )
        db.session.add(nuevo_pago)
        db.session.commit()
        return jsonify({'mensaje': 'Pago agregado con éxito'}), 201
    else: # GET
        pagos = Pago.query.order_by(Pago.id.desc()).all()
        return jsonify([pago.to_dict() for pago in pagos])

@app.route("/api/gastos", methods=['POST', 'GET'])
@login_required
def handle_gastos():
    if request.method == 'POST':
        datos = request.json
        fecha_gasto_obj = datetime.strptime(datos['expense-date'], '%Y-%m-%d').date()
        nuevo_gasto = Gasto(
            fecha_gasto=fecha_gasto_obj, descripcion=datos['description'],
            monto=float(datos['amount']), proveedor=datos.get('supplier'),
            factura=datos.get('invoice-number'),
            registrado_por=current_user.username
        )
        db.session.add(nuevo_gasto)
        db.session.commit()
        return jsonify({'mensaje': 'Gasto agregado con éxito'}), 201
    else: # GET
        gastos = Gasto.query.order_by(Gasto.id.desc()).all()
        return jsonify([gasto.to_dict() for gasto in gastos])

@app.route('/api/reporte-excel')
@login_required
def descargar_reporte():
    try:
        pagos_query = Pago.query.all()
        gastos_query = Gasto.query.all()
        pagos_df = pd.DataFrame([p.to_dict() for p in pagos_query])
        gastos_df = pd.DataFrame([g.to_dict() for g in gastos_query])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            pagos_df.to_excel(writer, sheet_name='Pagos', index=False)
            gastos_df.to_excel(writer, sheet_name='Gastos', index=False)
        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f"Reporte_Condominio_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        )
    except Exception as e:
        return str(e)

# --- COMANDO PARA INICIALIZAR LA BASE DE DATOS (SIMPLIFICADO) ---
@app.cli.command("create-db")
def create_db_command():
    """Crea las tablas de la base de datos y los usuarios iniciales."""
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin_user = User(username='admin', role='admin')
            admin_user.set_password('admin123')
            db.session.add(admin_user)
            print("Usuario admin creado.")
        if not User.query.filter_by(username='tesorero').first():
            tesorero__user = User(username='tesorero', role='tesorero')
            tesorero_user.set_password('tesorero123')
            db.session.add(tesorero_user)
            print("Usuario tesorero creado.")
        db.session.commit()
        print("Base de datos inicializada y usuarios creados.")

