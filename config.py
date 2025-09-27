API_TOKEN = "8244427408:AAFsrxadSnM0hzdL6dhujvC7oAOqCqDmrO8"
ADMIN_ID = 1083503320
YOUGILE_API_KEY = "rCEakSyWemqJFLJKbNRqLBY5av-hMPT8mOV3fTvtC8KvdtIGZLg4l6szM6vJXC6C"
PROJECT_ID = "84b19c0b-e706-4735-93df-80fe00d0cd40"
COLUMN_ID = "b117840d-29dc-4a71-818f-9072f40867de" # мы получим его через test.py

import os

def _get_env(name: str, required: bool = True) -> str | None:
    value = os.getenv(name)
    if required and (value is None or value.strip() == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

API_TOKEN = _get_env("API_TOKEN")
YOUGILE_API_KEY = _get_env("YOUGILE_API_KEY")
COLUMN_ID = _get_env("COLUMN_ID")

# ADMIN_ID необязателен для запуска, но если задан — приводим к int
_admin_id = os.getenv("ADMIN_ID")
ADMIN_ID = int(_admin_id) if _admin_id and _admin_id.isdigit() else None
