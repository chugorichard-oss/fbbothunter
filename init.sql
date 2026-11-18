CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS publicaciones (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fb_post_id VARCHAR(255) UNIQUE NOT NULL,
    url TEXT NOT NULL,
    titulo_pagina VARCHAR(255),
    fecha_publicacion TIMESTAMP,
    total_reacciones INT DEFAULT 0,
    total_comentarios INT DEFAULT 0,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS perfiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fb_user_id VARCHAR(255) UNIQUE,
    nombre VARCHAR(255) NOT NULL,
    url_perfil TEXT,
    caracteres_no_latinos BOOLEAN DEFAULT FALSE,
    dias_activo INT,
    cantidad_amigos INT,
    es_cuenta_cerrada BOOLEAN DEFAULT FALSE,
    bot_score INT DEFAULT 0,
    es_sospechoso BOOLEAN DEFAULT FALSE,
    detalles_anomalia JSONB DEFAULT '[]'::jsonb,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS comentarios (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID REFERENCES publicaciones(id) ON DELETE CASCADE,
    perfil_id UUID REFERENCES perfiles(id) ON DELETE CASCADE,
    contenido TEXT,
    fecha_comentario TIMESTAMP,
    sentimiento_score FLOAT DEFAULT 0.0,
    es_duplicado BOOLEAN DEFAULT FALSE,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_perfiles_bot_score ON perfiles(bot_score);
CREATE INDEX IF NOT EXISTS idx_comentarios_post_id ON comentarios(post_id);
