import sys
import os

# Add root project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Handler for Vercel serverless function
app = app
