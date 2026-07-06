"""
conftest.py — proje kök dizinini sys.path'e ekler,
böylece tests/ içinden doğrudan import çalışır.
"""
import sys
import os

# tests/ → vbp/ (proje kökü)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
