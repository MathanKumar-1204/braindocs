import os
import logging
from typing import Dict, List, Any, Optional
from config import Config

logger = logging.getLogger(__name__)

_supabase_client = None

def get_supabase_client():
    global _supabase_client
    if _supabase_client is None:
        if Config.SUPABASE_URL and Config.SUPABASE_KEY and "your-supabase" not in Config.SUPABASE_URL:
            try:
                from supabase import create_client, Client
                _supabase_client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
                logger.info("Supabase client initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                _supabase_client = None
    return _supabase_client


# --- Profile & User Management ---

def get_user_profile_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("profiles").select("*").eq("id", user_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"Error fetching profile by ID {user_id}: {e}")
        return None


def get_user_profile_by_username(username: str) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("profiles").select("*").eq("username", username.lower()).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"Error fetching profile by username {username}: {e}")
        return None


def set_user_username(user_id: str, email: str, username: str) -> tuple[bool, str]:
    client = get_supabase_client()
    clean_username = username.strip().lower()
    
    if not client:
        logger.warning("Supabase client not configured. Simulating username set.")
        return True, ""

    try:
        # Check if username already taken by another user
        existing = client.table("profiles").select("id").eq("username", clean_username).execute()
        if existing.data and existing.data[0]["id"] != user_id:
            return False, f"Username '@{clean_username}' is already taken. Please choose another."

        # Try updating existing profile row first
        update_res = client.table("profiles").update({"username": clean_username, "email": email}).eq("id", user_id).execute()
        if not update_res.data:
            # Upsert/Insert profile if no row updated
            data = {"id": user_id, "email": email, "username": clean_username}
            client.table("profiles").upsert(data).execute()

        return True, ""
    except Exception as e:
        logger.error(f"Error setting username for user {user_id}: {e}")
        err_str = str(e).lower()
        # If RLS policy error 42501 or demo user, log warning and allow proceeding with session username
        if "42501" in err_str or "row-level security" in err_str or "demo-user" in str(user_id) or "uuid" in err_str:
            logger.warning(f"Supabase RLS or ID constraint encountered ({e}); setting username in session.")
            return True, ""
        return False, f"Error saving username to database: {str(e)}"


import uuid

def _ensure_valid_uuid(user_id: str) -> str:
    """Ensures user_id string is in valid PostgreSQL UUID format."""
    try:
        val = uuid.UUID(user_id)
        return str(val)
    except Exception:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id)))


# --- Storage Bucket Operations ---

def upload_file_to_storage(username: str, filename: str, file_bytes: bytes, content_type: str = "application/octet-stream") -> str:
    """
    Uploads file to Supabase Storage bucket in folder `<username>/<filename>`.
    Returns storage file path.
    """
    client = get_supabase_client()
    file_path = f"{username.lower()}/{filename}"
    
    if not client:
        logger.warning(f"Supabase client not configured. Simulating storage upload to {file_path}")
        return file_path

    bucket = Config.SUPABASE_STORAGE_BUCKET
    try:
        # Try retrieving or creating bucket if it doesn't exist
        try:
            client.storage.get_bucket(bucket)
        except Exception:
            try:
                client.storage.create_bucket(bucket, options={"public": True})
                logger.info(f"Created public Supabase storage bucket '{bucket}'")
            except Exception as eb:
                logger.warning(f"Storage bucket check/create warning for '{bucket}': {eb}")

        # Upload or overwrite file in storage bucket
        client.storage.from_(bucket).upload(
            path=file_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        logger.info(f"Successfully uploaded {filename} to Supabase storage bucket '{bucket}' path '{file_path}'")
        return file_path
    except Exception as e:
        logger.error(f"Error uploading file to Supabase Storage {file_path}: {e}")
        return file_path


def delete_file_from_storage(file_path: str) -> bool:
    """
    Deletes file from Supabase Storage bucket.
    """
    client = get_supabase_client()
    if not client:
        return True

    bucket = Config.SUPABASE_STORAGE_BUCKET
    try:
        client.storage.from_(bucket).remove([file_path])
        return True
    except Exception as e:
        logger.error(f"Error deleting file from Supabase storage {file_path}: {e}")
        return False


# --- Document Database Operations ---

def save_document_record(user_id: str, username: str, filename: str, file_path: str, file_type: str, file_size: int, chunk_count: int) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    clean_username = username.lower()
    valid_uuid = _ensure_valid_uuid(user_id)

    data = {
        "user_id": valid_uuid,
        "username": clean_username,
        "filename": filename,
        "file_path": file_path,
        "file_type": file_type,
        "file_size": file_size,
        "chunk_count": chunk_count
    }

    if not client:
        data["id"] = f"mock-doc-{filename}"
        return data

    try:
        # 1. Ensure user profile exists in profiles table first to satisfy foreign key constraint
        try:
            client.table("profiles").upsert({"id": valid_uuid, "username": clean_username, "email": f"{clean_username}@user.com"}).execute()
        except Exception as ep:
            logger.warning(f"Profile pre-upsert warning during doc save: {ep}")

        # 2. Insert document record into documents table
        res = client.table("documents").insert(data).execute()
        if res.data:
            logger.info(f"Successfully saved document record {filename} into Supabase DB.")
            return res.data[0]
        return data
    except Exception as e:
        logger.error(f"Error saving document record to Supabase DB: {e}")
        return data


def get_user_documents(username: str) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    if not client:
        return []
    try:
        res = client.table("documents").select("*").eq("username", username.lower()).order("created_at", desc=True).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Error getting documents for {username}: {e}")
        return []


def get_document_by_id(doc_id: str) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("documents").select("*").eq("id", doc_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"Error fetching document by ID {doc_id}: {e}")
        return None


def delete_document_record(doc_id: str) -> bool:
    client = get_supabase_client()
    if not client:
        return True
    try:
        client.table("documents").delete().eq("id", doc_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error deleting document record {doc_id}: {e}")
        return False


# --- Chat Logs Operations ---

def save_chat_log(bot_username: str, visitor_email: str, user_message: str, bot_response: str) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    data = {
        "bot_username": bot_username.lower(),
        "visitor_email": visitor_email.strip().lower(),
        "user_message": user_message,
        "bot_response": bot_response
    }

    if not client:
        data["id"] = "mock-chat-id"
        return data

    try:
        res = client.table("chat_logs").insert(data).execute()
        if res.data:
            logger.info(f"Successfully saved chat log from visitor {visitor_email} for bot {bot_username}")
            return res.data[0]
        return data
    except Exception as e:
        logger.error(f"Error saving chat log for chatbot {bot_username}: {e}")
        return data


def get_chatbot_chat_logs(bot_username: str) -> List[Dict[str, Any]]:
    """
    Fetches all visitor chat logs for a given chatbot owner's username.
    """
    client = get_supabase_client()
    if not client:
        return []
    try:
        res = client.table("chat_logs").select("*").eq("bot_username", bot_username.lower()).order("created_at", desc=True).execute()
        logs = res.data or []
        logger.info(f"Fetched {len(logs)} chat logs for bot {bot_username}")
        return logs
    except Exception as e:
        logger.error(f"Error fetching chat logs for bot {bot_username}: {e}")
        return []
