"""Единый экземпляр SQLAlchemy, чтобы избежать циклических импортов."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
