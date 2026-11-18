# 🛡️ Bot Hunter Bolivia — Detector de Granjas Coordinadas en Facebook

Herramienta de auditoría digital desarrollada en Python, Playwright, PostgreSQL y Streamlit para detectar comportamiento inauténtico coordinado (granjas de bots, cuentas recién creadas sin historial y repetición sistemática de consignas) en publicaciones públicas de Facebook en Bolivia.

---

## 🏗️ Arquitectura del Sistema

1. **URL Publicación FB:** Entrada del enlace público a auditar.
2. **Playwright Extractor:** Expande el árbol completo de comentarios e inspecciona perfiles.
3. **Motor de Bot Score:** Evalúa alfabetos foráneos, tamaño de red, privacidad y similitud de texto.
4. **PostgreSQL + Redis:** Persistencia relacional y control de estado en Docker.
5. **Dashboard Streamlit:** Visualización interactiva, métricas de manipulación y exportación CSV.

---

## 📊 Criterios de Evaluación (Bot Score)

Cada perfil extraído recibe una puntuación de riesgo (0% a 100%) basada en cinco señales ponderadas:

* **Alfabetos no latinos (+50%):** Detección mediante Regex de caracteres árabes, cirílicos, asiáticos o devanagari sin vínculo local.
* **Red de amigos mínima (+35%):** Perfiles con menos de 30 amigos (+20% si tienen menos de 100 amigos).
* **Consigna repetitiva (+30%):** Similitud de texto >= 72% respecto a otros comentarios en la misma publicación.
* **Perfil vacío o restringido (+20%):** Cuentas bloqueadas o sin publicaciones propias visibles en su muro.
* **Relleno genérico (+15%):** Frases cortas de plantilla acompañadas de múltiples emojis repetitivos.

---

## 🚀 Instalación y Despliegue Local

### 1. Levantar Base de Datos y Caché
    docker compose up -d

### 2. Configurar Entorno Virtual de Python
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    playwright install chromium
    sudo ./venv/bin/playwright install-deps chromium

### 3. Generar Sesión de Navegación (Una sola vez)
Ejecuta el gestor de sesión para iniciar sesión en una cuenta de auditoría y guardar las cookies localmente en src/auth_state.json:
    python src/auth_manager.py

### 4. Ejecutar el Dashboard Web
    streamlit run src/dashboard.py
Accede desde tu navegador a http://localhost:8501.

### 5. Ejecución por Línea de Comandos (Opcional)
    python src/bot_hunter_engine.py "[https://www.facebook.com/pagina/posts/123456789](https://www.facebook.com/pagina/posts/123456789)"

---

## ⚠️ Aviso Ético y Uso Responsable
Este proyecto tiene fines de investigación, transparencia informativa y auditoría de desinformación en espacios públicos. No almacena credenciales en el repositorio y respeta pausas aleatorias de navegación para evitar sobrecarga en los servidores consultados.
