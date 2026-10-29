"""Serverless entry point for Vercel (and any WSGI-style function host).

Vercel imports this module and looks for a WSGI callable named ``app``. The repo
root is added to ``sys.path`` so ``import app`` resolves to the real Flask
application one level up.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app  # noqa: E402,F401  (re-exported for the runtime)
