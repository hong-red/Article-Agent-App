"""配置管理：App 托管版。数据目录、数据库路径、服务器密钥、免费期提示。"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ARTICLES_DIR = os.path.join(DATA_DIR, "articles")
MATERIALS_DIR = os.path.join(DATA_DIR, "materials")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
DB_PATH = os.path.join(DATA_DIR, "app.db")
SECRET_KEY_PATH = os.path.join(DATA_DIR, "secret.key")

# 免费期提示（占位，正式上线前改成真实日期）
FREE_UNTIL = "2026-12"


def ensure_dirs():
    for d in (DATA_DIR, ARTICLES_DIR, MATERIALS_DIR, IMAGES_DIR):
        os.makedirs(d, exist_ok=True)
