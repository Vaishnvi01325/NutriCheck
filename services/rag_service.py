"""
RAG (Retrieval-Augmented Generation) Diet Chatbot Service — NutriCheck
========================================================================
Loads the diet_knowledge.txt knowledge base, retrieves the most relevant
chunks using TF-IDF similarity, then sends the context to the Gemini API
to generate a grounded, accurate diet-tip response.
"""

import os
import math
import re
from config import GEMINI_API_KEY

# ─────────────────────────────────────────────────────────
# Knowledge Base Loading
# ─────────────────────────────────────────────────────────

_KNOWLEDGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'data', 'diet_knowledge.txt'
)

_chunks: list[str] = []


def _load_knowledge_base():
    """Split the knowledge file into paragraph-level chunks."""
    global _chunks
    if _chunks:
        return  # already loaded

    if not os.path.exists(_KNOWLEDGE_PATH):
        _chunks = ["General nutrition advice: eat a balanced diet rich in vegetables, lean proteins, whole grains, and healthy fats. Limit sugar, sodium, and ultra-processed foods."]
        return

    with open(_KNOWLEDGE_PATH, encoding='utf-8') as f:
        text = f.read()

    # Split on double newlines (paragraph breaks)
    raw = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    _chunks = raw


# ─────────────────────────────────────────────────────────
# TF-IDF Retrieval
# ─────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r'[a-z]+', text.lower())


def _tfidf_retrieve(query: str, top_k: int = 4) -> list[str]:
    """Return the top_k most relevant knowledge chunks for the query."""
    _load_knowledge_base()
    if not _chunks:
        return []

    query_tokens = set(_tokenize(query))

    # Compute TF-IDF-like similarity (BM25-lite with term overlap)
    scores = []
    for chunk in _chunks:
        chunk_tokens = _tokenize(chunk)
        chunk_set = set(chunk_tokens)
        overlap = query_tokens & chunk_set
        if not overlap:
            scores.append(0.0)
            continue

        # TF: how many times the overlapping terms appear in this chunk
        tf = sum(chunk_tokens.count(term) for term in overlap)

        # IDF: reward distinctive terms that appear in fewer chunks
        idf_sum = 0.0
        for term in overlap:
            doc_freq = sum(1 for c in _chunks if term in _tokenize(c))
            idf_sum += math.log(1 + len(_chunks) / (1 + doc_freq))

        scores.append(tf + idf_sum)

    # Sort by score descending and return top-k
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    top_chunks = [_chunks[i] for i, s in ranked[:top_k] if s > 0]
    return top_chunks or _chunks[:top_k]


# ─────────────────────────────────────────────────────────
# Gemini API Call
# ─────────────────────────────────────────────────────────

_cached_model_name = None  # Cached after first successful discovery


def _get_gemini_model():
    """
    Auto-discover an available Gemini model from the API (cached after first call).
    Tries a priority list first, then falls back to listing all available models.
    """
    global _cached_model_name
    if _cached_model_name:
        return _cached_model_name

    import google.generativeai as genai

    # Priority list — newest stable models first
    PREFERRED_MODELS = [
        'gemini-2.5-pro',
        'gemini-2.5-flash',
        'gemini-2.0-flash-lite',
        'gemini-2.0-flash-exp',
        'gemini-1.5-flash-latest',
        'gemini-pro',
    ]

    # Try each preferred model quickly
    for model_name in PREFERRED_MODELS:
        try:
            m = genai.GenerativeModel(model_name)
            m.generate_content("hi", generation_config={'max_output_tokens': 1})
            _cached_model_name = model_name
            print(f"[NutriCheck] Using Gemini model: {model_name}")
            return _cached_model_name
        except Exception:
            continue

    # Fallback: list all models from the API and pick first that supports generateContent
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                _cached_model_name = m.name.replace('models/', '')
                print(f"[NutriCheck] Using Gemini model (discovered): {_cached_model_name}")
                return _cached_model_name
    except Exception:
        pass

    return None


def _call_gemini(prompt: str) -> str:
    """Call the Google Gemini API and return the text response."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model_name = _get_gemini_model()
        if not model_name:
            return "⚠️ No available Gemini model found. Please check your API key and quota."
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        return response.text.strip()
    except ImportError:
        return "⚠️ Gemini API not installed. Run: pip install google-generativeai"
    except Exception as e:
        return f"⚠️ AI service error: {str(e)}"


# ─────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────

def chat(user_message: str, analysis_context: dict | None = None) -> str:
    """
    Main chatbot function.

    Args:
        user_message:    The user's question or message.
        analysis_context: Optional dict with the current food analysis
                          (product_name, health_score, verdict, nutrients…)
                          so the bot can give product-specific advice.

    Returns:
        str: The AI-generated response.
    """
    if not GEMINI_API_KEY:
        return "⚠️ Please set GEMINI_API_KEY in your .env file to enable the AI assistant."

    # Retrieve relevant knowledge chunks
    retrieved = _tfidf_retrieve(user_message, top_k=4)
    context_text = "\n\n".join(retrieved) if retrieved else ""

    # Build product context string if available
    product_ctx = ""
    if analysis_context:
        name    = analysis_context.get('product_name', 'Unknown Product')
        score   = analysis_context.get('health_score', 'N/A')
        verdict = analysis_context.get('verdict', '')
        cal     = analysis_context.get('calories', 'N/A')
        sugar   = analysis_context.get('sugar', 'N/A')
        fat     = analysis_context.get('fat', 'N/A')
        sodium  = analysis_context.get('sodium', 'N/A')
        protein = analysis_context.get('protein', 'N/A')
        fiber   = analysis_context.get('fiber', 'N/A')
        product_ctx = f"""
The user has just scanned a food product:
- Product Name: {name}
- Health Score: {score}/100 ({verdict})
- Calories: {cal} kcal | Sugar: {sugar}g | Fat: {fat}g | Sodium: {sodium}mg | Protein: {protein}g | Fiber: {fiber}g

If the user asks about this product, give specific advice based on these values.
"""

    # Compose the full prompt
    prompt = f"""You are NutriBot, an expert nutritionist and diet AI assistant embedded in the NutriCheck food label analyser app.

Your role is to:
1. Answer questions about nutrition, diet, food labels, and healthy eating.
2. Give specific advice about scanned food products when context is available.
3. Be friendly, concise, and evidence-based.
4. Use emojis sparingly for readability.
5. Keep responses under 200 words unless detailed explanation is truly needed.
6. Never give medical diagnoses — always suggest consulting a healthcare professional for medical conditions.

=== RETRIEVED NUTRITION KNOWLEDGE ===
{context_text}
{product_ctx}
=== USER QUESTION ===
{user_message}

=== YOUR RESPONSE ==="""

    return _call_gemini(prompt)
