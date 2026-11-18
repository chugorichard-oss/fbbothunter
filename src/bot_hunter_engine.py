import asyncio
from difflib import SequenceMatcher
import os
import random
import re
import sys
from urllib.parse import urlparse, parse_qs
import psycopg2
from psycopg2.extras import Json
from playwright.async_api import async_playwright

STATE_FILE = os.path.join(os.path.dirname(__file__), "auth_state.json")

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "bot_hunter_db",
    "user": "hunter_admin",
    "password": "SecretHunterPassword2026!"
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

async def human_delay(min_sec=1.0, max_sec=2.2):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

def extract_post_id(url: str) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "story_fbid" in qs:
        return qs["story_fbid"][0]
    parts = [p for p in parsed.path.split("/") if p]
    return parts[-1] if parts else url[:100]

def text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def is_repetitive_comment(comentario: str, comentarios_previos: list[str]) -> tuple[bool, float]:
    clean = re.sub(r'[^\w\s]', '', comentario.lower()).strip()
    if len(clean) < 6:
        return False, 0.0
    max_sim = 0.0
    for prev in comentarios_previos:
        prev_clean = re.sub(r'[^\w\s]', '', prev.lower()).strip()
        if not prev_clean:
            continue
        sim = text_similarity(clean, prev_clean)
        if sim > max_sim:
            max_sim = sim
        if sim >= 0.72:
            return True, sim
    return False, max_sim

def evaluate_bot_score(
    nombre: str,
    amigos: int | None,
    cerrada: bool,
    sin_actividad: bool,
    comentario: str,
    comentarios_previos: list[str]
) -> tuple[int, list]:
    score = 0
    razones = []

    # 1. Alfabetos no latinos
    patron_foraneo = re.compile(r'[\u0600-\u06FF\u0400-\u04FF\u4E00-\u9FFF\u0900-\u097F\u0E00-\u0E7F]')
    if patron_foraneo.search(nombre):
        score += 50
        razones.append("Nombre con caracteres extranjeros")

    # 2. Cantidad de amigos
    if amigos is not None:
        if amigos < 30:
            score += 35
            razones.append(f"Red muy baja ({amigos} amigos)")
        elif amigos < 100:
            score += 20
            razones.append(f"Pocos amigos ({amigos} amigos)")

    # 3. Perfil cerrado o cascarón vacío
    if cerrada:
        score += 20
        razones.append("Perfil restringido/cerrado")
    if sin_actividad:
        score += 20
        razones.append("Perfil sin publicaciones propias visibles")

    # 4. Similitud de consigna / comentario copiado con variaciones
    es_similar, sim_val = is_repetitive_comment(comentario, comentarios_previos)
    if es_similar:
        score += 30
        razones.append(f"Consigna repetitiva ({int(sim_val*100)}% similar a otro comentario)")

    # 5. Comentario genérico corto o exceso de emojis
    texto_limpio = comentario.strip()
    emojis = re.findall(r'[^\w\s,.\-!?¿¡()\'"]', texto_limpio)
    if len(texto_limpio) > 0 and len(texto_limpio) <= 18 and len(emojis) >= 2:
        score += 15
        razones.append("Frase corta de relleno con múltiples emojis")
    elif len(texto_limpio) > 0 and len(texto_limpio) <= 4:
        score += 10
        razones.append("Comentario monosilábico o solo emoji")

    return min(score, 100), razones

async def inspect_profile(context, profile_url: str) -> dict:
    info = {"amigos": None, "cerrada": False, "sin_actividad": False}
    if not profile_url or "facebook.com" not in profile_url:
        return info

    page = await context.new_page()
    try:
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=15000)
        await human_delay(1.0, 1.8)
        body_text = await page.inner_text("body")

        if re.search(r"restringió su perfil|locked their profile|bloqueó su perfil", body_text, re.IGNORECASE):
            info["cerrada"] = True

        if re.search(r"no hay publicaciones disponibles|no posts available", body_text, re.IGNORECASE):
            info["sin_actividad"] = True

        match_amigos = re.search(r'(\d+(?:[.,]\d+)?)\s*(mil|k)?\s*(?:amigos|friends)', body_text, re.IGNORECASE)
        if match_amigos:
            num_str = match_amigos.group(1).replace(",", ".")
            multiplicador = 1000 if match_amigos.group(2) else 1
            info["amigos"] = int(float(num_str) * multiplicador)
    except Exception:
        pass
    finally:
        await page.close()
    return info

def is_valid_author_link(text: str, href: str) -> bool:
    if not text or not href:
        return False
    clean = text.strip()
    if len(clean) < 2 or "\n" in clean:
        return False
    if re.match(r'^\d+\s*(min|h|d|sem|s|m|y|w)$', clean, re.IGNORECASE):
        return False
    if clean.lower() in {"me gusta", "responder", "compartir", "ver más", "like", "reply", "share", "editar", "autor", "fan destacado"}:
        return False
    if any(x in href for x in ["/hashtag/", "/watch/", "/photo", "/posts/", "/videos/", "comment_id="]):
        if "profile.php" not in href and len(urlparse(href).path.strip("/").split("/")) > 1:
            return False
    return True

async def expand_all_comments(page, max_rounds: int = 25):
    print("📜 Expandiendo todos los comentarios disponibles...")
    sin_cambios = 0
    conteo_anterior = 0

    for ronda in range(max_rounds):
        botones_mas = page.locator("div[role='button'], span[role='button']").filter(
            has_text=re.compile(r"Ver más comentarios|View more comments|Ver \d+ comentarios más|View \d+ more comments", re.IGNORECASE)
        )
        cantidad_botones = await botones_mas.count()
        for i in range(cantidad_botones):
            try:
                btn = botones_mas.nth(i)
                if await btn.is_visible():
                    await btn.click()
                    await human_delay(1.0, 1.8)
            except Exception:
                pass

        await page.evaluate("""
            window.scrollBy(0, 1200);
            document.querySelectorAll('div[role="dialog"] div').forEach(el => {
                if (el.scrollHeight > el.clientHeight) {
                    el.scrollTop += 1200;
                }
            });
        """)
        await human_delay(1.3, 2.2)

        conteo_actual = await page.locator('div[role="article"]').count()
        print(f"   ↳ Ronda {ronda + 1}: {conteo_actual} bloques cargados...")

        if conteo_actual == conteo_anterior:
            sin_cambios += 1
            if sin_cambios >= 3:
                print("✅ Se alcanzó el final de los comentarios visibles.")
                break
        else:
            sin_cambios = 0
            conteo_anterior = conteo_actual

async def run_analysis(post_url: str, max_comments: int = 250, max_profile_visits: int = 100):
    if not os.path.exists(STATE_FILE):
        print("❌ No existe auth_state.json. Ejecuta primero python src/auth_manager.py")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            storage_state=STATE_FILE,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="es-LA",
            timezone_id="America/La_Paz"
        )

        page = await context.new_page()
        print(f"🔎 Abriendo enlace: {post_url}")
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await human_delay(3, 5)

        final_url = page.url
        print(f"🔗 URL resuelta: {final_url}")
        fb_post_id = extract_post_id(final_url)

        cur.execute("""
            INSERT INTO publicaciones (fb_post_id, url)
            VALUES (%s, %s)
            ON CONFLICT (fb_post_id) DO UPDATE SET url = EXCLUDED.url
            RETURNING id;
        """, (fb_post_id, final_url))
        post_db_id = cur.fetchone()[0]
        cur.execute("DELETE FROM comentarios WHERE post_id = %s;", (post_db_id,)); conn.commit()

        try:
            filtro = page.locator("text=/Más relevantes|Most relevant/i").first
            if await filtro.is_visible(timeout=3000):
                await filtro.click()
                await human_delay(1, 2)
                todos = page.locator("text=/Todos los comentarios|All comments/i").first
                if await todos.is_visible(timeout=3000):
                    await todos.click()
                    await human_delay(2, 3)
        except Exception:
            pass

        await expand_all_comments(page, max_rounds=25)

        bloques = await page.locator('div[role="article"]').all()
        print(f"📥 Total de bloques capturados en DOM: {len(bloques)}")

        # Fase 1: Extraer todos los comentarios rápidamente
        registros = []
        usuarios_vistos = set()

        for bloque in bloques:
            if len(registros) >= max_comments:
                break
            try:
                enlaces = await bloque.locator('a').all()
                nombre = None
                perfil_url = None

                for link in enlaces:
                    txt = (await link.inner_text()).strip()
                    href = await link.get_attribute("href") or ""
                    if is_valid_author_link(txt, href):
                        nombre = txt
                        if href.startswith("/"):
                            href = "https://www.facebook.com" + href
                        perfil_url = href.split("?")[0] if "profile.php" not in href else href.split("&")[0]
                        break

                if not nombre or not perfil_url or perfil_url in usuarios_vistos:
                    continue

                usuarios_vistos.add(perfil_url)

                comentario = ""
                textos_auto = await bloque.locator('div[dir="auto"]').all()
                for t_el in textos_auto:
                    t_str = (await t_el.inner_text()).strip()
                    if t_str and t_str != nombre:
                        comentario = t_str
                        break

                registros.append({
                    "nombre": nombre,
                    "perfil_url": perfil_url,
                    "comentario": comentario
                })
            except Exception:
                continue

        print(f"📋 Extracción inicial lista: {len(registros)} perfiles únicos. Iniciando auditoría profunda...")

        # Fase 2: Evaluar texto y priorizar visitas a perfiles
        comentarios_previos = []
        for reg in registros:
            es_sim, _ = is_repetitive_comment(reg["comentario"], comentarios_previos)
            reg["pre_flag"] = es_sim or len(reg["comentario"]) <= 18
            comentarios_previos.append(reg["comentario"])

        # Ordenar para inspeccionar primero los que ya tienen señales sospechosas en el texto
        registros.sort(key=lambda x: x["pre_flag"], reverse=True)

        comentarios_analizados = []
        visitas_perfil = 0
        sospechosos_count = 0

        for idx, reg in enumerate(registros, start=1):
            amigos = None
            cerrada = False
            sin_actividad = False

            if visitas_perfil < max_profile_visits:
                datos = await inspect_profile(context, reg["perfil_url"])
                amigos = datos["amigos"]
                cerrada = datos["cerrada"]
                sin_actividad = datos["sin_actividad"]
                visitas_perfil += 1

            score, razones = evaluate_bot_score(
                reg["nombre"], amigos, cerrada, sin_actividad, reg["comentario"], comentarios_analizados
            )
            es_bot = score >= 35
            if es_bot:
                sospechosos_count += 1

            comentarios_analizados.append(reg["comentario"])

            cur.execute("""
                INSERT INTO perfiles (fb_user_id, nombre, url_perfil, caracteres_no_latinos, cantidad_amigos, es_cuenta_cerrada, bot_score, es_sospechoso, detalles_anomalia)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fb_user_id) DO UPDATE SET
                    bot_score = EXCLUDED.bot_score,
                    es_sospechoso = EXCLUDED.es_sospechoso,
                    cantidad_amigos = COALESCE(EXCLUDED.cantidad_amigos, perfiles.cantidad_amigos),
                    es_cuenta_cerrada = EXCLUDED.es_cuenta_cerrada,
                    detalles_anomalia = EXCLUDED.detalles_anomalia,
                    actualizado_en = CURRENT_TIMESTAMP
                RETURNING id;
            """, (
                reg["perfil_url"], reg["nombre"], reg["perfil_url"],
                any("extranjeros" in r for r in razones),
                amigos, cerrada, score, es_bot, Json(razones)
            ))
            perfil_db_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO comentarios (post_id, perfil_id, contenido, es_duplicado)
                VALUES (%s, %s, %s, %s);
            """, (post_db_id, perfil_db_id, reg["comentario"], any("repetitiva" in r for r in razones)))
            cur.execute("DELETE FROM comentarios WHERE post_id = %s;", (post_db_id,)); conn.commit()

            if es_bot or idx <= 15:
                estado_icono = "🚨 BOT/GRANJA" if es_bot else "✅ ORGÁNICO"
                print(f"[{idx}/{len(registros)}] {estado_icono} ({score}%) | {reg['nombre']} | Amigos: {amigos} | \"{reg['comentario'][:35]}...\" | {razones}")

        await browser.close()

    cur.close()
    conn.close()

    total = len(registros)
    print("\n" + "=" * 60)
    print(f"📊 RESUMEN DE AUDITORÍA CALIBRADO:")
    print(f"   • Perfiles únicos analizados: {total}")
    print(f"   • Perfiles inspeccionados a fondo: {visitas_perfil}")
    print(f"   • Cuentas sospechosas (Score >= 35%): {sospechosos_count} ({round((sospechosos_count/total)*100, 1) if total else 0}%)")
    print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python src/bot_hunter_engine.py \"URL_DE_LA_PUBLICACION\"")
        sys.exit(1)
    url_objetivo = sys.argv[1]
    asyncio.run(run_analysis(url_objetivo, max_comments=250, max_profile_visits=100))
