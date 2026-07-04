from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Aeropuerto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    ciudad = db.Column(db.String(100), nullable=False)
    latitud = db.Column(db.Float, nullable=False)
    longitud = db.Column(db.Float, nullable=False)
    estado = db.Column(db.String(20), default="Abierto")

class Ruta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    origen_id = db.Column(db.Integer, db.ForeignKey('aeropuerto.id'), nullable=False)
    destino_id = db.Column(db.Integer, db.ForeignKey('aeropuerto.id'), nullable=False)
    
    distancia = db.Column(db.Float, nullable=False)
    tiempo = db.Column(db.Float, nullable=False) 
    costo = db.Column(db.Float, nullable=False)
    consumo = db.Column(db.Float, nullable=False)
    estado = db.Column(db.String(30), default="Activa")

    origen = db.relationship("Aeropuerto", foreign_keys=[origen_id])
    destino = db.relationship("Aeropuerto", foreign_keys=[destino_id])

class Simulacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    origen = db.Column(db.String(150))
    destino = db.Column(db.String(150))
    criterio = db.Column(db.String(50))
    distancia_total = db.Column(db.Float)
    tiempo_total = db.Column(db.Float)
    costo_total = db.Column(db.Float)
    consumo_total = db.Column(db.Float)
    nodos_ruta = db.Column(db.Text)
    estado_red = db.Column(db.String(100))