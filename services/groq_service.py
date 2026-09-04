import logging
import requests
from typing import List, Dict, Any
from config import Config

logger = logging.getLogger(__name__)

def generate_groq_rag_response(bot_username: str, visitor_question: str, context_matches: List[Dict[str, Any]]) -> str:
    """
    Combines retrieved context matches from Pinecone RAG with visitor prompt,
    and calls Groq API to generate an intelligent, context-aware answer.
    """
    api_key = Config.GROQ_API_KEY
    model = Config.GROQ_MODEL

    # Format context passages
    if context_matches:
        context_str = "\n\n".join([
            f"--- Document Source ({m.get('filename', 'Unknown')}): ---\n{m.get('text', '')}"
            for m in context_matches if m.get('text')
        ])
    else:
        context_str = "No specific document context found for this query."

    system_prompt = f"""You are 'BRAINDOCS AI', an intelligent document assistant representing '{bot_username}'.
Answer the user's question accurately using ONLY the provided context documents below.
If the context does not contain enough information to answer the question, state politely that the uploaded documents do not contain that information, but offer any helpful high-level insights if relevant.

DOCUMENT CONTEXT:
{context_str}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": visitor_question}
    ]

    # Check if Groq SDK or HTTP API is used
    if not api_key or "gsk_your_groq" in api_key:
        logger.warning("Groq API Key not configured. Returning mock/default RAG response.")
        if context_matches:
            top_source = context_matches[0].get("filename", "uploaded file")
            top_snippet = context_matches[0].get("text", "")[:300]
            return f"[BRAINDOCS Demo Response]\n\nBased on your documents (Source: '{top_source}'):\n\n\"{top_snippet}...\"\n\n(To enable live Groq LLM replies, please set a valid GROQ_API_KEY in your .env configuration)."
        else:
            return f"Hello! I am {bot_username}'s BRAINDOCS assistant. No specific documents were found matching your query. (Please add a GROQ_API_KEY in .env for full AI generation)."

    try:
        # Groq API endpoint (compatible with OpenAI API standard)
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 800
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        res_data = response.json()
        bot_reply = res_data["choices"][0]["message"]["content"]
        return bot_reply.strip()

    except Exception as e:
        logger.error(f"Error calling Groq API: {e}")
        return f"I encountered an error generating a response from the Groq AI service. Details: {str(e)}"
