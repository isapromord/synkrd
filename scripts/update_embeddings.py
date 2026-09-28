"""
Generate and update embeddings for existing legal_knowledge articles.
Uses Gemini gemini-embedding-001 API with 768 dimensions.
"""
import os, sys, time, httpx
from dotenv import load_dotenv
from supabase import create_client

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Load env
for p in [
    os.path.join(os.path.dirname(__file__), "..", ".env"),
    os.path.join(os.path.expanduser("~"), "Desktop", "flow-bot", ".env"),
]:
    if os.path.exists(p):
        load_dotenv(p)
        print(f"[OK] .env loaded from {os.path.abspath(p)}")
        break

URL = os.getenv("MICONDO_SUPABASE_URL", "")
KEY = os.getenv("MICONDO_SUPABASE_KEY", "")
GEMINI = os.getenv("GEMINI_API_KEY", "")

if not all([URL, KEY, GEMINI]):
    print("[ERROR] Missing: MICONDO_SUPABASE_URL, MICONDO_SUPABASE_KEY, or GEMINI_API_KEY")
    sys.exit(1)

sb = create_client(URL, KEY)

def embed(text):
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={GEMINI}",
        json={
            "model": "models/gemini-embedding-001",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": 768,
        },
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json().get("embedding", {}).get("values", [])

# Get articles without embeddings
rows = sb.table("legal_knowledge").select("id, title, summary").is_("embedding", "null").execute()
articles = rows.data or []
print(f"\n[INFO] Found {len(articles)} articles without embeddings\n")

ok = 0
for i, a in enumerate(articles, 1):
    txt = f"{a['title']}. {a['summary']}"
    print(f"  [{i}/{len(articles)}] {a['title'][:60]}...")
    try:
        vec = embed(txt)
        if vec:
            sb.table("legal_knowledge").update({"embedding": vec}).eq("id", a["id"]).execute()
            print(f"    [OK] {len(vec)} dims")
            ok += 1
        else:
            print(f"    [WARN] Empty embedding")
    except Exception as e:
        print(f"    [ERR] {e}")
    time.sleep(1.5)

print(f"\n{'='*50}")
print(f"  Updated: {ok}/{len(articles)}")
print(f"{'='*50}")
