import os
import logging
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_cors import CORS
from config import Config

# Import services
from services import (
    document_service,
    supabase_service,
    pinecone_service,
    groq_service
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("braindocs")

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)


# Context Processor to make user object and config available in templates
@app.context_processor
def inject_globals():
    user = session.get("user")
    return dict(user=user, config=Config)


# --- Authentication & Session Routes ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/auth/callback")
def auth_callback():
    return render_template("index.html")


@app.route("/api/auth/session", methods=["POST"])
def set_auth_session():
    data = request.get_json() or {}
    user_id = data.get("id")
    email = data.get("email")

    if not user_id or not email:
        return jsonify({"error": "Missing user identification"}), 400

    profile = supabase_service.get_user_profile_by_id(user_id)
    username = profile.get("username") if profile else None

    session_user = {
        "id": user_id,
        "email": email,
        "username": username
    }
    session["user"] = session_user

    if not username:
        return jsonify({"redirect": url_for("onboarding")})
    else:
        return jsonify({"redirect": url_for("dashboard")})


@app.route("/auth/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("index"))


# --- Onboarding Route ---

@app.route("/onboarding")
def onboarding():
    user = session.get("user")
    if not user:
        flash("Please sign in first.", "error")
        return redirect(url_for("index"))
    if user.get("username"):
        return redirect(url_for("dashboard"))
    return render_template("onboarding.html")


@app.route("/api/username", methods=["POST"])
def set_username_route():
    user = session.get("user")
    if not user:
        flash("Please sign in first.", "error")
        return redirect(url_for("index"))

    username = request.form.get("username") or (request.get_json() or {}).get("username")
    if not username:
        flash("Username is required.", "error")
        return redirect(url_for("onboarding"))

    clean_username = username.strip().lower()
    success, err_msg = supabase_service.set_user_username(user["id"], user["email"], clean_username)

    if not success:
        flash(err_msg or "That username is already taken. Please try another.", "error")
        return redirect(url_for("onboarding"))

    # Update session user
    user["username"] = clean_username
    session["user"] = user
    session.modified = True

    flash(f"Username '@{clean_username}' set successfully! Your Pinecone namespace and storage directory are ready.", "success")
    return redirect(url_for("dashboard"))


# --- Main Dashboard & File Upload ---

@app.route("/dashboard")
def dashboard():
    user = session.get("user")
    if not user:
        flash("Please sign in to access your dashboard.", "error")
        return redirect(url_for("index"))
    if not user.get("username"):
        return redirect(url_for("onboarding"))

    username = user["username"]
    documents = supabase_service.get_user_documents(username)
    return render_template("dashboard.html", documents=documents)


@app.route("/api/upload", methods=["POST"])
def upload_document():
    user = session.get("user")
    if not user or not user.get("username"):
        flash("Unauthorized upload request.", "error")
        return redirect(url_for("index"))

    username = user["username"]
    user_id = user["id"]

    if "file" not in request.files:
        flash("No file attached to upload request.", "error")
        return redirect(url_for("dashboard"))

    file = request.files["file"]
    if not file or file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("dashboard"))

    filename = file.filename
    file_bytes = file.read()
    file_size = len(file_bytes)
    ext = filename.split(".")[-1].lower()

    if ext not in ["pdf", "docx", "txt", "csv"]:
        flash(f"Unsupported file extension: .{ext}. Allowed: PDF, DOCX, TXT, CSV.", "error")
        return redirect(url_for("dashboard"))

    try:
        # 1. Extract Text
        logger.info(f"Extracting text from {filename} for user {username}")
        text = document_service.extract_text(file_bytes, filename)
        if not text:
            flash(f"Could not extract text content from {filename}.", "error")
            return redirect(url_for("dashboard"))

        # 2. Chunk Text
        chunks = document_service.chunk_text(text)
        logger.info(f"Generated {len(chunks)} chunks from {filename}")

        # 3. Generate Vector Embeddings (384 dimensions)
        embeddings = document_service.generate_embeddings(chunks)

        # 4. Upload File to Supabase Storage Bucket under `{username}/{filename}`
        file_path = supabase_service.upload_file_to_storage(
            username=username,
            filename=filename,
            file_bytes=file_bytes,
            content_type=file.content_type or "application/octet-stream"
        )

        # 5. Save Document Record in Supabase DB
        doc_record = supabase_service.save_document_record(
            user_id=user_id,
            username=username,
            filename=filename,
            file_path=file_path,
            file_type=ext,
            file_size=file_size,
            chunk_count=len(chunks)
        )
        doc_id = doc_record.get("id") if doc_record else filename

        # 6. Upsert Vectors to Pinecone Namespace `{username}`
        pinecone_service.upsert_vectors_to_namespace(
            username=username,
            doc_id=doc_id,
            filename=filename,
            chunks=chunks,
            embeddings=embeddings
        )

        flash(f"Successfully uploaded and indexed '{filename}' into Pinecone namespace '@{username}' ({len(chunks)} vector chunks)!", "success")

    except Exception as e:
        logger.error(f"Upload pipeline failed for {filename}: {e}", exc_info=True)
        flash(f"Error processing file '{filename}': {str(e)}", "error")

    return redirect(url_for("dashboard"))


# --- Profile, Document Management & Visitor Chat Logs ---

@app.route("/profile")
def profile():
    user = session.get("user")
    if not user or not user.get("username"):
        flash("Please sign in and set a username first.", "error")
        return redirect(url_for("index"))

    username = user["username"]
    documents = supabase_service.get_user_documents(username)
    chat_logs = supabase_service.get_chatbot_chat_logs(username)

    return render_template("profile.html", documents=documents, chat_logs=chat_logs)


@app.route("/api/documents/<doc_id>", methods=["DELETE"])
def delete_document_route(doc_id):
    user = session.get("user")
    if not user or not user.get("username"):
        return jsonify({"error": "Unauthorized"}), 401

    username = user["username"]
    doc = supabase_service.get_document_by_id(doc_id)

    if not doc:
        # Fallback delete for mock or unsaved doc
        pinecone_service.delete_vectors_by_document(username, doc_id)
        return jsonify({"success": True})

    if doc.get("username") != username:
        return jsonify({"error": "Forbidden - Document belongs to another user"}), 403

    # 1. Delete vectors from Pinecone namespace
    pinecone_service.delete_vectors_by_document(username, doc_id, chunk_count=doc.get("chunk_count", 500))

    # 2. Delete file from Supabase Storage
    if doc.get("file_path"):
        supabase_service.delete_file_from_storage(doc["file_path"])

    # 3. Delete record from Supabase DB
    supabase_service.delete_document_record(doc_id)

    return jsonify({"success": True})


RESERVED_USERNAMES = {"dashboard", "profile", "onboarding", "auth", "api", "static", "favicon.ico"}

@app.route("/<username>")
@app.route("/project_link/<username>")
def public_chatbot(username):
    clean_username = username.strip().lower()
    if clean_username in RESERVED_USERNAMES:
        return redirect(url_for(clean_username))
    return render_template("chatbot.html", bot_username=clean_username)


@app.route("/api/chat/<username>", methods=["POST"])
def chat_with_bot(username):
    data = request.get_json() or {}
    visitor_email = data.get("visitor_email", "anonymous@guest.com")
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Message body cannot be empty"}), 400

    clean_username = username.strip().lower()

    try:
        # 1. Embed query question (384-dim vector)
        query_vector = document_service.generate_single_embedding(user_message)

        # 2. Query Pinecone vector database in namespace `{clean_username}`
        context_matches = pinecone_service.query_vector_namespace(clean_username, query_vector, top_k=5)

        # 3. Generate response using Groq LLM API with retrieved context
        bot_response = groq_service.generate_groq_rag_response(clean_username, user_message, context_matches)

        # 4. Store chat session log in Supabase DB (bot_username, visitor_email, user_message, bot_response)
        supabase_service.save_chat_log(clean_username, visitor_email, user_message, bot_response)

        return jsonify({"reply": bot_response})

    except Exception as e:
        logger.error(f"Error handling chatbot response for @{clean_username}: {e}", exc_info=True)
        return jsonify({"error": f"Failed to process chat: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
