from collections import Counter
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

STOPWORDS_ES = {
    "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las", "por",
    "un", "para", "con", "no", "una", "su", "al", "lo", "como", "más", "pero",
    "sus", "le", "ya", "o", "este", "sí", "porque", "esta", "entre", "cuando",
    "muy", "sin", "sobre", "también", "me", "hasta", "hay", "donde", "quien",
    "desde", "todo", "nos", "durante", "todos", "uno", "les", "ni", "contra",
    "otros", "ese", "eso", "ante", "ellos", "e", "esto", "mí", "antes", "algunos",
    "qué", "unos", "yo", "otro", "otras", "otra", "él", "tanto", "esa", "estos",
    "mucho", "quienes", "nada", "muchos", "cual", "poco", "ella", "estar", "estas",
    "algunas", "algo", "nosotros", "mi", "mis", "tú", "te", "ti", "tu", "tus",
    "ellas", "nosotras", "vosotros", "vosotras", "os", "mío", "mía", "míos", "mías",
    "es", "son", "fue", "era", "va", "van", "mas", "si", "asi", "así", "solo"
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

async def human_delay(min_sec=1.0, max_sec=2.0):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

def extract_post_id(url: str) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "story_fbid" in qs:
        return qs["story_fbid"][0]
    if "fbid" in qs:
        return qs["fbid"][0]
    parts = [p for p in parsed.path.split("/") if p]
    return parts[-1] if parts else url[:100]

def normalize_tokens(text: str) -> list[str]:
    clean = re.sub(r'[^\w\sáéíóúüñ]', '', text.lower())
    return [w for w in clean.split() if len(w) > 2 and w not in STOPWORDS_ES]

def detect_coordinated_slogans(registros: list[dict]) -> dict[str, int]:
    """Detecta bigramas/frases clave repetidas por 3 o más usuarios distintos en el post."""
    ngram_counts = Counter()
    for reg in registros:
        tokens = normalize_tokens(reg["comentario"])
        # Extraer bigramas y trigramas únicos por comentario
        ngrams_comentario = set()
        for n in (2, 3):
            for i in range(len(tokens) - n + 1):
                ngrams_comentario.add(" ".join(tokens[i:i+n]))
        for ng in ngrams_comentario:
            ngram_counts[ng] += 1

    # Retornar consignas que aparecen en al menos 3 comentarios distintos
    return {ng: count for ng, count in ngram_counts.items() if count >= 3}

def find_matching_slogan(comentario: str, consignas_frecuentes: dict[str, int]) -> tuple[str | None, int]:
    tokens = normalize_tokens(comentario)
    mejor_consigna = None
    max_rep = 0
    for n in (3, 2):
        for i in range(len(tokens) - n + 1):
            ng = " ".join(tokens[i:i+n])
            if ng in consignas_frecuentes and consignas_frecuentes[ng] > max_rep:
                mejor_consigna = ng
                max_rep = consignas_frecuentes[ng]
    return mejor_consigna, max_rep

def is_similar_comment(comentario: str, todos_comentarios: list[str], idx_actual: int) -> tuple[bool, float]:
    clean = re.sub(r'[^\w\s]', '', comentario.lower()).strip()
    if len(clean) < 6:
        return False, 0.0
    max_sim = 0.0
    for j, otro in enumerate(todos_comentarios):
        if j == idx_actual:
            continue
        otro_clean = re.sub(r'[^\w\s]', '', otro.lower()).strip()
        if not otro_clean:
            continue
        sim = SequenceMatcher(None, clean, otro_clean).ratio()
        if sim > max_sim:
            max_sim = sim
        if sim >= 0.70:
            return True, sim
    return False, max_sim

def evaluate_bot_score(
    nombre: str,
    amigos: int | None,
    cerrada: bool,
    sin_actividad: bool,
    comentario: str,
    todos_comentarios: list[str],
    idx_actual: int,
    consignas_frecuentes: dict[str, int]
) -> tuple[int, list]:
    score = 0
    razones = []

    # 1. Alfabetos no latinos
    patron_foraneo = re.compile(r'[\u0600-\u06FF\u0400-\u04FF\u4E00-\u9FFF\u0900-\u097F\u0E00-\u0E7F]')
    if patron_foraneo.search(nombre):
        score += 50
        razones.append("Nombre con caracteres extranjeros")

    # 2. Consigna repetitiva / Patrón coordinado (Peso reforzado +40%)
    consigna, repeticiones = find_matching_slogan(comentario, consignas_frecuentes)
    es_similar, sim_val = is_similar_comment(comentario, todos_comentarios, idx_actual)

    if es_similar:
        score += 40
        razones.append(f"Comentario clonado ({int(sim_val*100)}% igual a otro perfil)")
    elif consigna:
        score += 40
        razones.append(f"Consigna coordinada: '{consigna}' (repetida {repeticiones} veces)")

    # 3. Cantidad de amigos
    if amigos is not None:
        if amigos < 30:
            score += 35
            razones.append(f"Red muy baja ({amigos} amigos)")
        elif amigos < 100:
            score += 20
            razones.append(f"Pocos amigos ({amigos} amigos)")

    # 4. Perfil cerrado o sin publicaciones
    if cerrada:
        score += 20
        razones.append("Perfil restringido/cerrado")
    if sin_actividad:
        score += 20
        razones.append("Perfil sin publicaciones propias visibles")

    # 5. Relleno genérico corto
    texto_limpio = comentario.strip()
    emojis = re.findall(r'[^\w\s,.\-!?¿¡()\'"]', texto_limpio)
    if len(texto_limpio) > 0 and len(texto_limpio) <= 18 and len(emojis) >= 2:
        score += 15
        razones.append("Frase corta con múltiples emojis")
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
    if clean.lower() in {
        "me gusta", "responder", "compartir", "ver más", "like", "reply", "share",
        "editar", "autor", "fan destacado", "comentar", "comment", "escribir un comentario"
    }:
        return False
    if any(x in href for x in ["/hashtag/", "/watch/", "/photo", "/posts/", "/videos/", "/groups/", "story.php"]):
        if "profile.php" not in href and "comment_id=" not in href:
            return False
    return True

async def expand_all_comments(page, max_rounds: int = 20):
    print("📜 Buscando y expandiendo sección de comentarios...", flush=True)
    try:
        btn_abrir = page.locator("div[role='button'], span[role='button']").filter(
            has_text=re.compile(r"^\d+\s*comentarios$|^\d+\s*comments$|^Comentar$|^Comment$", re.IGNORECASE)
        ).first
        if await btn_abrir.is_visible(timeout=2500):
            await btn_abrir.click()
            print("🖱️ Desplegando panel de comentarios oculto...", flush=True)
            await human_delay(2.0, 3.0)
    except Exception:
        pass

    sin_cambios = 0
    conteo_anterior = 0

    for ronda in range(max_rounds):
        botones_mas = page.locator("div[role='button'], span[role='button']").filter(
            has_text=re.compile(
                r"Ver más comentarios|View more comments|Ver \d+ comentarios más|View \d+ more comments|Ver comentarios anteriores|View previous comments",
                re.IGNORECASE
            )
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
            document.querySelectorAll('div[role="dialog"] div, div[role="main"] div').forEach(el => {
                if (el.scrollHeight > el.clientHeight && el.clientHeight > 200) {
                    el.scrollTop += 1200;
                }
            });
        """)
        await human_delay(1.3, 2.2)

        conteo_art = await page.locator('div[role="article"]').count()
        conteo_links = await page.locator('a[href*="comment_id="]').count()
        conteo_actual = max(conteo_art, conteo_links)
        print(f"   ↳ Ronda {ronda + 1}: {conteo_actual} nodos detectados...", flush=True)

        if conteo_actual == conteo_anterior:
            sin_cambios += 1
            if sin_cambios >= 3:
                print("✅ Se alcanzó el límite de comentarios visibles.", flush=True)
                break
        else:
            sin_cambios = 0
            conteo_anterior = conteo_actual

async def run_analysis(post_url: str, max_comments: int = 250, max_profile_visits: int = 80):
    if not os.path.exists(STATE_FILE):
        print("❌ No existe auth_state.json. Ejecuta primero python src/auth_manager.py", flush=True)
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
        print(f"🔎 Abriendo enlace: {post_url}", flush=True)
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await human_delay(3, 5)

        final_url = page.url
        print(f"🔗 URL resuelta: {final_url}", flush=True)
        fb_post_id = extract_post_id(final_url)

        cur.execute("""
            INSERT INTO publicaciones (fb_post_id, url)
            VALUES (%s, %s)
            ON CONFLICT (fb_post_id) DO UPDATE SET url = EXCLUDED.url
            RETURNING id;
        """, (fb_post_id, final_url))
        post_db_id = cur.fetchone()[0]
        conn.commit()

        try:
            filtro = page.locator("text=/Más relevantes|Most relevant/i").first
            if await filtro.is_visible(timeout=2500):
                await filtro.click()
                await human_delay(1, 2)
                todos = page.locator("text=/Todos los comentarios|All comments/i").first
                if await todos.is_visible(timeout=2500):
                    await todos.click()
                    print("🔄 Filtro cambiado a 'Todos los comentarios'.", flush=True)
                    await human_delay(2, 3)
        except Exception:
            pass

        await expand_all_comments(page, max_rounds=20)

        bloques = await page.locator('div[role="article"]').all()
        print(f"📥 Bloques article detectados: {len(bloques)}", flush=True)

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

        if len(registros) == 0:
            print("⚠️ Vista alternativa detectada. Activando extractor de enlaces directos...", flush=True)
            enlaces_directos = await page.locator('a[href*="comment_id="]').all()
            for link in enlaces_directos:
                if len(registros) >= max_comments:
                    break
                try:
                    txt = (await link.inner_text()).strip()
                    href = await link.get_attribute("href") or ""
                    if is_valid_author_link(txt, href):
                        if href.startswith("/"):
                            href = "https://www.facebook.com" + href
                        perfil_url = href.split("?")[0] if "profile.php" not in href else href.split("&")[0]
                        if perfil_url in usuarios_vistos:
                            continue
                        usuarios_vistos.add(perfil_url)

                        comentario = ""
                        contenedor = link.locator("xpath=ancestor::div[3]")
                        if await contenedor.count() > 0:
                            full_txt = await contenedor.first.inner_text()
                            lineas = [l.strip() for l in full_txt.split("\n") if l.strip() and l.strip() != txt]
                            if lineas:
                                comentario = lineas[0]

                        registros.append({
                            "nombre": txt,
                            "perfil_url": perfil_url,
                            "comentario": comentario
                        })
                except Exception:
                    continue

        if len(registros) == 0:
            print("❌ No se pudieron extraer comentarios visibles.", flush=True)
            await browser.close()
            cur.close()
            conn.close()
            return

        # Analizar patrones globales de consignas repetitivas en toda la publicación
        consignas_frecuentes = detect_coordinated_slogans(registros)
        if consignas_frecuentes:
            top_consignas = sorted(consignas_frecuentes.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"📢 Consignas coordinadas detectadas en este post: {top_consignas}", flush=True)

        print(f"📋 Extracción inicial lista: {len(registros)} perfiles únicos. Iniciando auditoría profunda...", flush=True)

        cur.execute("DELETE FROM comentarios WHERE post_id = %s;", (post_db_id,))
        conn.commit()

        todos_comentarios = [r["comentario"] for r in registros]
        for idx, reg in enumerate(registros):
            consigna, _ = find_matching_slogan(reg["comentario"], consignas_frecuentes)
            es_sim, _ = is_similar_comment(reg["comentario"], todos_comentarios, idx)
            reg["pre_flag"] = bool(consigna) or es_sim or len(reg["comentario"]) <= 18

        registros.sort(key=lambda x: x["pre_flag"], reverse=True)
        todos_comentarios_ordenados = [r["comentario"] for r in registros]

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
                reg["nombre"], amigos, cerrada, sin_actividad,
                reg["comentario"], todos_comentarios_ordenados, idx - 1, consignas_frecuentes
            )
            es_bot = score >= 35
            if es_bot:
                sospechosos_count += 1

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
            """, (post_db_id, perfil_db_id, reg["comentario"], any("Consigna" in r or "clonado" in r for r in razones)))
            conn.commit()

            estado_icono = "🚨 BOT" if es_bot else "✅ OK"
            print(f"[{idx}/{len(registros)}] {estado_icono} ({score}%) | {reg['nombre']} | Amigos: {amigos} | {razones}", flush=True)

        await browser.close()

    cur.close()
    conn.close()

    total = len(registros)
    print("=" * 55, flush=True)
    print(f"📊 AUDITORÍA FINALIZADA: {sospechosos_count}/{total} sospechosos ({round((sospechosos_count/total)*100, 1)}%)", flush=True)
    print("=" * 55, flush=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python src/bot_hunter_engine.py \"URL_DE_LA_PUBLICACION\" [max_profile_visits]")
        sys.exit(1)
    url_objetivo = sys.argv[1]
    visitas = int(sys.argv[2]) if len(sys.argv) >= 3 else 80
    asyncio.run(run_analysis(url_objetivo, max_comments=250, max_profile_visits=visitas))
