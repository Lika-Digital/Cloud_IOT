"""
Model path resolver — returns the correct base directory for OpenVINO model files.

On NUC (Linux with /opt/cloud-iot):  /opt/cloud-iot/backend/models
On dev (Windows or any other):        <repo>/backend/models
"""
import os
import sys


def get_model_dir() -> str:
    """Return the absolute path to the directory that contains model subdirectories."""
    if sys.platform == "linux" and os.path.exists("/opt/cloud-iot"):
        return "/opt/cloud-iot/backend/models"
    # Fallback for dev: <repo-root>/backend/models
    # This file lives at: backend/app/services/model_paths.py
    # So: parent(parent(parent(this file))) == backend/
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(backend_dir, "models")
