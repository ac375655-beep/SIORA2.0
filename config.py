import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = "SIORA_2026_OPTIMIZATION"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "siora.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False