import os
import subprocess
import sys
import warnings
import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st
from bot_hunter_engine import DB_CONFIG

warnings.filterwarnings("ignore", category=UserWarning, module="pandas")

st.set_page_config(
    page_title="Bot Hunter Bolivia | Auditoría de Redes",
    page_icon="🛡️",
    layout="wide"
)

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #f5f5f5; }
    div[data-testid="stMetric"] {
        background-color: #161b22;
        border-left: 4px solid #facc15;
        padding: 15px;
        border-radius: 6px;
    }
    .terminal-box {
        background-color: #090c10;
        color: #39ff14;
        font-family: 'Courier New', Courier, monospace;
        font-size: 13px;
        padding: 14px;
        border-radius: 8px;
        border: 1px solid #30363d;
        height: 300px;
        overflow-y: auto;
        white-space: pre-wrap;
        line-height: 1.45;
    }
    </style>
""", unsafe_allow_html=True)

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

st.title("🛡️ Bot Hunter Bolivia — Detector de Granjas Coordinadas")
st.caption("Auditoría de inautenticidad, cuentas sin historial y consignas repetitivas en Facebook.")

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("🔎 Nueva Auditoría")
    nueva_url = st.text_input("URL de la publicación de Facebook", placeholder="https://www.facebook.com/...")
    max_perfiles = st.slider("Perfiles a inspeccionar a fondo", min_value=10, max_value=150, value=60, step=10)
    ejecutar_btn = st.button("🚀 Analizar Publicación", width="stretch", type="primary")

    st.divider()
    st.markdown("**Criterios de Detección Activos:**")
    st.markdown("- 🌐 Alfabetos extranjeros (+50%)")
    st.markdown("- 📢 Consigna coordinada / clonada (+40%)")
    st.markdown("- 👥 Red < 30 amigos (+35%)")
    st.markdown("- 🔒 Perfil cerrado / sin posts (+20%)")

# --- TERMINAL EN VIVO EN TIEMPO REAL ---
if ejecutar_btn:
    if nueva_url.strip():
        st.subheader("🖥️ Terminal del Worker en Vivo")
        terminal_placeholder = st.empty()
        logs_acumulados = ["[SYSTEM] Lanzando subproceso Playwright headless..."]
        terminal_placeholder.markdown(
            f'<div class="terminal-box">{"<br>".join(logs_acumulados)}</div>',
            unsafe_allow_html=True
        )

        script_path = os.path.join(os.path.dirname(__file__), "bot_hunter_engine.py")
        proceso = subprocess.Popen(
            [sys.executable, "-u", script_path, nueva_url.strip(), str(max_perfiles)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for linea in iter(proceso.stdout.readline, ""):
            if linea:
                logs_acumulados.append(linea.rstrip())
                visibles = logs_acumulados[-35:]
                terminal_placeholder.markdown(
                    f'<div class="terminal-box">{"<br>".join(visibles)}</div>',
                    unsafe_allow_html=True
                )

        proceso.stdout.close()
        proceso.wait()
        st.success("✅ Auditoría completada. Pulsa el botón inferior para cargar los gráficos actualizados.")
        if st.button("🔄 Ver Gráficos y Resultados Actualizados"):
            st.rerun()
    else:
        st.warning("Ingresa una URL válida en el panel izquierdo.")

# --- CARGA DE DATOS DESDE POSTGRESQL ---
conn = get_connection()
df_posts = pd.read_sql("SELECT id, fb_post_id, url, creado_en FROM publicaciones ORDER BY creado_en DESC;", conn)

if df_posts.empty:
    st.info("Aún no hay publicaciones auditadas. Usa el panel izquierdo para analizar tu primer enlace.")
    conn.close()
    st.stop()

opciones_posts = {f"{row['fb_post_id']} ({str(row['creado_en'])[:16]}) — {row['url'][:55]}...": row['id'] for _, row in df_posts.iterrows()}
seleccion = st.selectbox("📂 Selecciona una publicación auditada:", list(opciones_posts.keys()))
post_id_seleccionado = opciones_posts[seleccion]

query_detalle = """
    SELECT 
        p.nombre AS "Usuario",
        p.bot_score AS "Bot Score",
        p.es_sospechoso AS "Sospechoso",
        p.cantidad_amigos AS "Amigos",
        p.es_cuenta_cerrada AS "Perfil Cerrado",
        p.caracteres_no_latinos AS "Nombre Extranjero",
        c.contenido AS "Comentario",
        p.detalles_anomalia AS "Banderas Detectadas",
        p.url_perfil AS "Enlace Perfil"
    FROM comentarios c
    JOIN perfiles p ON c.perfil_id = p.id
    WHERE c.post_id = %s
    ORDER BY p.bot_score DESC, p.cantidad_amigos ASC NULLS LAST;
"""
df = pd.read_sql(query_detalle, conn, params=(str(post_id_seleccionado),))
conn.close()

# --- MÉTRICAS PRINCIPALES ---
total_analizados = len(df)
total_bots = int(df["Sospechoso"].sum()) if total_analizados > 0 else 0
total_organicos = total_analizados - total_bots
pct_manipulacion = round((total_bots / total_analizados) * 100, 1) if total_analizados > 0 else 0.0
score_promedio = round(df["Bot Score"].mean(), 1) if total_analizados > 0 else 0.0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Perfiles Analizados", total_analizados)
col2.metric("Cuentas Sospechosas (Granja)", total_bots, delta=f"{pct_manipulacion}% del total", delta_color="inverse")
col3.metric("Perfiles Orgánicos", total_organicos)
col4.metric("Score Promedio de Riesgo", f"{score_promedio}%")

if total_analizados == 0:
    st.warning("⚠️ Esta publicación no tiene comentarios extraídos.")
    st.stop()

st.divider()

# --- GRÁFICOS DE EVIDENCIA ---
g_col1, g_col2 = st.columns(2)

with g_col1:
    st.subheader("Proporción Orgánico vs. Sospechoso")
    fig_pie = px.pie(
        names=["Cuentas Sospechosas / Granja", "Usuarios Orgánicos"],
        values=[total_bots, total_organicos],
        color_discrete_sequence=["#facc15", "#2ea043"],
        hole=0.45
    )
    fig_pie.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#f5f5f5")
    st.plotly_chart(fig_pie, width="stretch")

with g_col2:
    st.subheader("Distribución de Puntajes (Bot Score)")
    fig_hist = px.histogram(
        df,
        x="Bot Score",
        nbins=10,
        color="Sospechoso",
        color_discrete_map={True: "#facc15", False: "#2ea043"}
    )
    fig_hist.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#f5f5f5")
    st.plotly_chart(fig_hist, width="stretch")

# --- TABLA DE EVIDENCIA ---
st.subheader("📋 Registro Detallado de Perfiles y Comentarios")

filtro_solo_bots = st.checkbox("Mostrar únicamente cuentas sospechosas (Bot Score >= 35%)", value=True)
df_mostrar = df[df["Sospechoso"] == True] if filtro_solo_bots else df

st.dataframe(
    df_mostrar,
    width="stretch",
    column_config={
        "Enlace Perfil": st.column_config.LinkColumn("Perfil FB"),
        "Bot Score": st.column_config.ProgressColumn("Bot Score", min_value=0, max_value=100, format="%d%%")
    },
    hide_index=True
)

csv_data = df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    label="📥 Descargar Evidencia Completa en CSV",
    data=csv_data,
    file_name=f"auditoria_bots_{post_id_seleccionado}.csv",
    mime="text/csv"
)
