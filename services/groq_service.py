import logging
import requests
from typing import List, Dict, Any
from config import Config

logger = logging.getLogger(__name__)

def generate_groq_rag_response(bot_username: str, visitor_question: str, context_matches: List[Dict[str, Any]]) -> str:
    """
    Combines retrieved context matches from Pinecone RAG with visitor prompt,
    and calls Groq API to generate an intelligent, strict context-aware answer.
    """
    api_key = Config.GROQ_API_KEY
    model = Config.GROQ_MODEL

    # Filter matches with valid similarity score
    meaningful_matches = [m for m in context_matches if m.get("text") and m.get("score", 1.0) > 0.15]

    if not meaningful_matches:
        return f"I'm sorry, but @{bot_username} does not have any uploaded documents containing information about '{visitor_question}'. Please upload a document on the dashboard to get answers."

    context_str = "\n\n".join([
        f"--- Document Source ({m.get('filename', 'uploaded file')}): ---\n{m.get('text', '')}"
        for m in meaningful_matches
    ])

    system_prompt = f"""You are 'BRAINDOCS AI', an intelligent custom document assistant trained strictly on documents uploaded by '@{bot_username}'.

STRICT RULES:
1. Answer the user's question accurately using ONLY the DOCUMENT CONTEXT provided below.
2. Do NOT use outside or general world knowledge, and do NOT invent facts not present in the context.
3. If the context does not contain the answer, reply strictly: "I'm sorry, but @{bot_username}'s uploaded documents do not contain information to answer this question."

DOCUMENT CONTEXT:
{context_str}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": visitor_question}
    ]

    if not api_key or "gsk_your_groq" in api_key:
        logger.warning("Groq API Key not configured. Returning mock/default RAG response.")
        top_source = meaningful_matches[0].get("filename", "uploaded file")
        top_snippet = meaningful_matches[0].get("text", "")[:300]
        return f"[BRAINDOCS Demo Response]\n\nBased on your documents (Source: '{top_source}'):\n\n\"{top_snippet}...\"\n\n(To enable live Groq LLM replies, please set a valid GROQ_API_KEY in your .env configuration)."

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
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
