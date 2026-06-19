"""Vercel serverless entry point — Flask app'i handler olarak expose eder."""
import sys
import os

# Proje kökünü Python path'e ekle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Vercel ortamında data dosyaları /tmp/ai_trade/ altında tutulur
os.environ.setdefault("VERCEL_DATA_DIR", "/tmp/ai_trade")

from scalpbot.dashboard import app  # noqa: E402

# Vercel, 'app' adındaki WSGI uygulamasını otomatik tanır
# (eski sürümler için 'handler' alias'ı da ekliyoruz)
handler = app
