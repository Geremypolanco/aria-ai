-- Tabla para cuentas de redes sociales conectadas via OAuth
-- Ejecutar en Supabase SQL Editor

CREATE TABLE IF NOT EXISTS social_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform        TEXT NOT NULL,           -- facebook, instagram, tiktok, linkedin
    account_id      TEXT,                    -- ID de la cuenta en la plataforma
    username        TEXT,                    -- nombre de usuario
    email           TEXT,                    -- email si la plataforma lo proporciona
    access_token    TEXT NOT NULL,           -- token de acceso OAuth
    refresh_token   TEXT,                    -- token de refresco (si aplica)
    expires_at      TIMESTAMPTZ,            -- cuando vence el access_token
    scopes          TEXT,                    -- permisos otorgados
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indice por plataforma para busquedas rapidas
CREATE UNIQUE INDEX IF NOT EXISTS social_accounts_platform_idx ON social_accounts(platform) WHERE is_active = TRUE;

-- Trigger para actualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE OR REPLACE TRIGGER update_social_accounts_updated_at
    BEFORE UPDATE ON social_accounts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
