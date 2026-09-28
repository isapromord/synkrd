"""
Seed Legal Knowledge Base — Sprint 2.5
Inserts initial Dominican Republic legal articles into Supabase
with Gemini gemini-embedding-001 vectors (768 dims) for RAG semantic search.

Usage: python scripts/seed_legal_knowledge.py
"""

import os
import sys
import json
import time
import httpx
from dotenv import load_dotenv
from supabase import create_client

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Load .env — try shopify-bot first, then flow-bot
env_paths = [
    os.path.join(os.path.dirname(__file__), "..", ".env"),
    os.path.join(os.path.expanduser("~"), "Desktop", "flow-bot", ".env"),
]
for p in env_paths:
    if os.path.exists(p):
        load_dotenv(p)
        print(f"[OK] Loaded .env from: {os.path.abspath(p)}")
        break

SUPABASE_URL = os.getenv("MICONDO_SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("MICONDO_SUPABASE_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
    print("❌ Missing env vars: MICONDO_SUPABASE_URL, MICONDO_SUPABASE_KEY, GEMINI_API_KEY")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def generate_embedding(text: str) -> list:
    """Generate 768-dim embedding via Gemini gemini-embedding-001."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-embedding-001:embedContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": 768,
    }
    resp = httpx.post(url, json=payload, timeout=15.0)
    resp.raise_for_status()
    return resp.json().get("embedding", {}).get("values", [])


# ═══════════════════════════════════════════════════════════════
# LEGAL CORPUS — Dominican Republic Laws for Condominiums
# ═══════════════════════════════════════════════════════════════

LEGAL_ARTICLES = [
    # ── Ley 5038 (Condominios) ───────────────────────────────
    {
        "category": "condominios",
        "law_name": "Ley 5038",
        "article_number": "Art. 1-3",
        "title": "División de la propiedad en condominios",
        "summary": (
            "Permite dividir edificios de dos o más pisos en apartamentos, viviendas "
            "o locales independientes. Cada propietario es dueño exclusivo de su unidad "
            "y copropietario del terreno y partes comunes (patios, muros, techos, "
            "escaleras, ascensores)."
        ),
        "full_text": (
            "Artículos 1-3 de la Ley 5038 sobre Condominios (1958): Los pisos de un "
            "edificio de dos o más pueden pertenecer a propietarios distintos. Cada "
            "propietario será dueño exclusivo de su piso y copropietario del terreno "
            "común y de las cosas de uso general, como patios, muros maestros, techos, "
            "escaleras, ascensores, portería, etc."
        ),
        "keywords": ["propiedad", "condominio", "copropietario", "apartamento", "areas comunes"],
        "applies_to": "both",
        "source": "Ley 5038-1958, Sobre Condominios",
        "effective_date": "1958-11-21",
        "is_pending": False,
    },
    {
        "category": "condominios",
        "law_name": "Ley 5038",
        "article_number": "Art. 4",
        "title": "Obligación de pago de cuotas de mantenimiento",
        "summary": (
            "Cada propietario está obligado a contribuir proporcionalmente a las cargas "
            "relativas a la conservación, mantenimiento, reparación y administración de "
            "las cosas comunes. La contribución es proporcional al valor de las fracciones "
            "divididas del inmueble. El impago puede acarrear sanciones e hipotecas."
        ),
        "full_text": (
            "Artículo 4.- Cada propietario contribuirá a las cargas relativas a la "
            "conservación, al mantenimiento, a la reparación, a la reconstrucción y a la "
            "administración de las cosas comunes, proporcionalmente al valor de las "
            "fracciones divididas del inmueble, teniendo en cuenta su extensión y situación."
        ),
        "keywords": ["cuota", "mantenimiento", "pago", "obligacion", "carga", "moroso"],
        "applies_to": "both",
        "source": "Ley 5038-1958, Sobre Condominios",
        "effective_date": "1958-11-21",
        "is_pending": False,
    },
    {
        "category": "condominios",
        "law_name": "Ley 5038",
        "article_number": "Art. 9",
        "title": "Consorcio de propietarios",
        "summary": (
            "Todos los propietarios de las unidades forman obligatoriamente un consorcio "
            "con personalidad jurídica para la administración de las cosas comunes. El "
            "consorcio actúa como representante legal a través de un administrador."
        ),
        "full_text": (
            "Artículo 9.- Para la buena administración de las cosas comunes, todos los "
            "propietarios de las unidades del inmueble forman obligatoriamente un consorcio "
            "con personalidad jurídica, que actuará como representante legal a través de "
            "un administrador."
        ),
        "keywords": ["consorcio", "propietarios", "administracion", "personalidad juridica"],
        "applies_to": "both",
        "source": "Ley 5038-1958, Sobre Condominios",
        "effective_date": "1958-11-21",
        "is_pending": False,
    },
    {
        "category": "condominios",
        "law_name": "Ley 5038",
        "article_number": "Art. 12",
        "title": "Obligatoriedad de resoluciones de asamblea",
        "summary": (
            "Las resoluciones del consorcio de propietarios son obligatorias siempre que "
            "sean tomadas por mayoría de votos en asambleas debidamente convocadas."
        ),
        "full_text": (
            "Artículo 12.- Las resoluciones del consorcio de propietarios son obligatorias "
            "para todos los copropietarios, siempre que sean tomadas por la mayoría de "
            "votos, computados según el valor de las fracciones divididas, en asamblea "
            "debidamente convocada."
        ),
        "keywords": ["asamblea", "resolucion", "votacion", "mayoria", "obligatoria"],
        "applies_to": "both",
        "source": "Ley 5038-1958, Sobre Condominios",
        "effective_date": "1958-11-21",
        "is_pending": False,
    },
    {
        "category": "condominios",
        "law_name": "Ley 5038",
        "article_number": "Art. 14-15",
        "title": "Funciones del administrador del condominio",
        "summary": (
            "El administrador tiene a su cargo la ejecución de las decisiones de la asamblea "
            "del consorcio, la guarda, conservación y mantenimiento de las cosas comunes. "
            "Puede compeler a cada interesado al cumplimiento de sus obligaciones. Principales "
            "funciones: cobro de cuotas, manejo presupuestario, supervisión de mantenimiento, "
            "custodia de documentos y representación legal del consorcio."
        ),
        "full_text": (
            "Artículos 14-15.- El administrador tendrá a su cargo la ejecución de las "
            "resoluciones de la asamblea, y la guarda, conservación y mantenimiento de las "
            "cosas comunes. Podrá compeler a cada interesado al cumplimiento de sus "
            "obligaciones. Actúa como representante del consorcio en calidad de demandante "
            "o demandado."
        ),
        "keywords": ["administrador", "funciones", "cobro", "cuota", "representante", "mantenimiento"],
        "applies_to": "admin",
        "source": "Ley 5038-1958, Sobre Condominios",
        "effective_date": "1958-11-21",
        "is_pending": False,
    },

    # ── Ley 16-92 (Código de Trabajo) ────────────────────────
    {
        "category": "laboral",
        "law_name": "Ley 16-92",
        "article_number": "Art. 258",
        "title": "Empleados de condominios NO son domésticos",
        "summary": (
            "Los trabajadores al servicio del consorcio de propietarios de un condominio "
            "NO son considerados trabajadores domésticos. Se rigen por las disposiciones "
            "generales del Código de Trabajo (contratos, vacaciones, cesantía, seguridad "
            "social). Esto aplica a porteros, conserjes, personal de limpieza y vigilancia."
        ),
        "full_text": (
            'Artículo 258.- Son trabajadores domésticos los que se dedican de modo exclusivo '
            'y en forma habitual y continua a labores de cocina, aseo, asistencia y demás, '
            'propias de un hogar o de otro medio ambiente privado, que no importen lucro '
            'o negocio para el empleador o sus parientes. No son domésticos los trabajadores '
            'al servicio del consorcio de propietarios de un condominio.'
        ),
        "keywords": ["domestico", "condominio", "portero", "conserje", "empleado", "laboral"],
        "applies_to": "admin",
        "source": "Ley 16-92, Código de Trabajo",
        "effective_date": "1992-06-11",
        "is_pending": False,
    },
    {
        "category": "laboral",
        "law_name": "Ley 16-92",
        "article_number": "Art. 177",
        "title": "Vacaciones anuales de trabajadores",
        "summary": (
            "Todo trabajador tiene derecho a 14 días laborales de vacaciones con disfrute "
            "de salario, después de un año continuo de servicio. El empleador puede posponer "
            "las vacaciones hasta 6 meses después de adquirido el derecho."
        ),
        "full_text": (
            "Artículo 177.- Los empleadores tienen la obligación de conceder a todo "
            "trabajador un período de vacaciones de catorce (14) días laborables con "
            "disfrute de salario, después de un trabajo continuo no menor de un año "
            "ni mayor de cinco."
        ),
        "keywords": ["vacaciones", "dias", "descanso", "salario", "derecho"],
        "applies_to": "employee",
        "source": "Ley 16-92, Código de Trabajo",
        "effective_date": "1992-06-11",
        "is_pending": False,
    },
    {
        "category": "laboral",
        "law_name": "Ley 16-92",
        "article_number": "Art. 80",
        "title": "Cesantía por terminación de contrato",
        "summary": (
            "Cuando un contrato por tiempo indefinido termina por decisión del empleador "
            "sin justa causa (desahucio), debe pagar cesantía según la antigüedad: "
            "3-6 meses = 6 días; 6-12 meses = 13 días; 1-5 años = 21 días/año; "
            ">5 años = 23 días/año de salario ordinario. No aplica si el trabajador "
            "renuncia voluntariamente."
        ),
        "full_text": (
            "Artículo 80.- El empleador que ejerza el desahucio debe pagar al trabajador "
            "un auxilio de cesantía: después de trabajo continuo no menor de 3 meses ni "
            "mayor de 6 = 6 días de salario ordinario; no menor de 6 meses ni mayor de "
            "1 año = 13 días; no menor de 1 año ni mayor de 5 = 21 días de salario "
            "ordinario por cada año; no menor de 5 años = 23 días de salario ordinario "
            "por cada año de servicio prestado."
        ),
        "keywords": ["cesantia", "desahucio", "prestaciones", "despido", "liquidacion", "pago"],
        "applies_to": "employee",
        "source": "Ley 16-92, Código de Trabajo",
        "effective_date": "1992-06-11",
        "is_pending": False,
    },
    {
        "category": "laboral",
        "law_name": "Ley 16-92",
        "article_number": "Art. 219",
        "title": "Salario de Navidad (Regalía Pascual)",
        "summary": (
            "El empleador debe pagar al trabajador un salario de Navidad equivalente a "
            "la duodécima parte (1/12) del salario ordinario devengado durante el año "
            "calendario. Debe pagarse a más tardar el 20 de diciembre. No se computa para "
            "el cálculo de preaviso, cesantía ni asistencia económica."
        ),
        "full_text": (
            "Artículo 219.- El empleador está obligado a pagar al trabajador, en el mes "
            "de diciembre, el salario de navidad, consistente en la duodécima parte del "
            "salario ordinario devengado por el trabajador en el año calendario."
        ),
        "keywords": ["navidad", "regalia", "salario", "diciembre", "doble sueldo"],
        "applies_to": "employee",
        "source": "Ley 16-92, Código de Trabajo",
        "effective_date": "1992-06-11",
        "is_pending": False,
    },

    # ── Ley 87-01 (Seguridad Social) ────────────────────────
    {
        "category": "seguridad_social",
        "law_name": "Ley 87-01",
        "article_number": "Art. 2-5",
        "title": "Sistema Dominicano de Seguridad Social (SDSS)",
        "summary": (
            "Todo empleador debe inscribir a sus trabajadores en la Tesorería de la "
            "Seguridad Social (TSS). El sistema cubre: Seguro de vejez, discapacidad "
            "y sobrevivencia (AFP); Seguro familiar de salud (ARS); Seguro de riesgos "
            "laborales (ARL). Las cotizaciones se dividen entre empleador y trabajador."
        ),
        "full_text": (
            "Artículos 2-5.- Se crea el Sistema Dominicano de Seguridad Social que tiene "
            "como finalidad regular y desarrollar los derechos y deberes recíprocos del "
            "Estado y de los ciudadanos en lo concerniente al financiamiento para la "
            "protección de la población contra los riesgos de vejez, discapacidad, "
            "sobrevivencia, enfermedad, maternidad, infancia y riesgos laborales."
        ),
        "keywords": ["seguridad social", "TSS", "AFP", "ARS", "ARL", "cotizacion", "seguro"],
        "applies_to": "admin",
        "source": "Ley 87-01, Sobre Seguridad Social",
        "effective_date": "2001-05-09",
        "is_pending": False,
    },

    # ── Reforma Código de Trabajo (Pendiente) ─────────────────
    {
        "category": "laboral",
        "law_name": "Reforma Código de Trabajo",
        "article_number": "Proyecto de Ley",
        "title": "Reforma laboral 2025 — Nuevos derechos laborales",
        "summary": (
            "Reforma al Código de Trabajo aprobada en segunda lectura en el Senado "
            "(Oct 2025), pendiente de promulgación. Cambios principales: regulación "
            "del teletrabajo, derecho a la desconexión digital, ampliación de licencia "
            "de paternidad, aumento gradual de vacaciones, protección contra acoso "
            "laboral, y regulación de plataformas digitales. IMPORTANTE: Esta ley aún "
            "no está promulgada — los artículos actuales de la Ley 16-92 siguen vigentes."
        ),
        "full_text": (
            "Proyecto de reforma al Código de Trabajo dominicano. Aprobado en segunda "
            "lectura por el Senado en octubre 2025. Pendiente de promulgación por el "
            "Poder Ejecutivo. Entre los cambios principales: regulación del teletrabajo "
            "y trabajo remoto, derecho a la desconexión digital después de la jornada "
            "laboral, ampliación de licencia de paternidad de 2 a 5 días, aumento gradual "
            "del período de vacaciones, protección contra el acoso laboral y sexual, "
            "regulación de empleados en plataformas digitales."
        ),
        "keywords": ["reforma", "teletrabajo", "desconexion digital", "paternidad", "vacaciones", "acoso"],
        "applies_to": "both",
        "source": "Proyecto de Reforma al Código de Trabajo (Senado, Oct 2025)",
        "effective_date": None,
        "is_pending": True,
    },
]


def main():
    """Seed all legal articles with embeddings."""
    print(f"🔄 Seeding {len(LEGAL_ARTICLES)} legal articles...")
    print(f"   Supabase: {SUPABASE_URL[:30]}...")
    print(f"   Gemini API: {GEMINI_API_KEY[:10]}...")
    print()

    success_count = 0
    error_count = 0

    for i, article in enumerate(LEGAL_ARTICLES, 1):
        law = article["law_name"]
        art = article.get("article_number", "")
        print(f"  [{i}/{len(LEGAL_ARTICLES)}] {law} {art} — {article['title'][:50]}...")

        # Generate embedding from title + summary
        embed_text = f"{article['title']}. {article['summary']}"
        try:
            embedding = generate_embedding(embed_text)
            if embedding:
                article["embedding"] = embedding
                print(f"    ✅ Embedding: {len(embedding)} dimensions")
            else:
                print(f"    ⚠️ No embedding returned, inserting without vector")
        except Exception as e:
            print(f"    ⚠️ Embedding failed: {e}")

        # Insert into Supabase
        try:
            result = supabase.table("legal_knowledge").insert(article).execute()
            if result.data:
                success_count += 1
                print(f"    ✅ Inserted: {result.data[0]['id'][:8]}...")
            else:
                error_count += 1
                print(f"    ❌ No data returned from insert")
        except Exception as e:
            error_count += 1
            print(f"    ❌ Insert failed: {e}")

        # Rate limiting (Gemini free tier: 60 req/min)
        time.sleep(1.5)

    print()
    print(f"═══════════════════════════════════════════════")
    print(f"  ✅ Inserted: {success_count}/{len(LEGAL_ARTICLES)}")
    if error_count:
        print(f"  ❌ Errors: {error_count}")
    print(f"═══════════════════════════════════════════════")


if __name__ == "__main__":
    main()
