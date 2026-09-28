"""Direct test: Call Gemini with Sofia's prompt to find the exact error."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

print("=" * 50)
print("  GEMINI DIRECT TEST")
print("=" * 50)

# Test 1: Check API key
api_key = os.getenv("GEMINI_API_KEY", "")
print(f"\n1. API Key: {api_key[:15]}..." if api_key else "\n1. ❌ No API key!")

# Test 2: Initialize client
print("\n2. Initializing Gemini client...")
try:
    from google import genai
    client = genai.Client(api_key=api_key)
    print("   ✅ Client created")
except Exception as e:
    print(f"   ❌ Client failed: {e}")
    # Try the old API
    print("   Trying old google.generativeai API...")
    try:
        import google.generativeai as genai_old
        genai_old.configure(api_key=api_key)
        model = genai_old.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content("Di 'hola' en espanol dominicano")
        print(f"   ✅ Old API works! Response: {response.text[:100]}")
    except Exception as e2:
        print(f"   ❌ Old API also failed: {e2}")
    sys.exit(1)

# Test 3: Call the model
print("\n3. Calling Gemini Flash...")
try:
    from knowledge.scraper import fetch_all_products, build_product_context
    products = fetch_all_products()
    product_ctx = build_product_context(products)
    
    system_prompt = f"""Eres Sofia, asistente de TrendyRD.com. Responde en espanol dominicano.
    
CATALOGO DE PRODUCTOS:
{product_ctx[:1000]}"""
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[{"role": "user", "parts": [{"text": "Hola, que productos venden?"}]}],
        config={
            "system_instruction": system_prompt,
            "max_output_tokens": 500,
            "temperature": 0.3,
        },
    )
    print(f"   ✅ Response: {response.text[:300]}")
    if hasattr(response, "usage_metadata"):
        print(f"   Tokens: {response.usage_metadata}")
except Exception as e:
    print(f"   ❌ FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)
