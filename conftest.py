# Variables obligatorias para poder importar la app en los tests (database.py las exige al
# importarse). setdefault: si el entorno ya las define, se respetan. Sin Postgres real, el
# lifespan reintenta y sigue con DB.pool=None (los endpoints de base responden 503).
import os

os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:1/test")
