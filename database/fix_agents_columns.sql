-- =====================================================
  -- ARIA AI — Fix columnas faltantes en tabla 'agents'
  -- Ejecutar en: Supabase Dashboard → SQL Editor → Run
  -- Causa: la tabla agents fue creada con un schema diferente
  -- =====================================================

  -- Agregar columnas faltantes que los agentes necesitan
  ALTER TABLE agents ADD COLUMN IF NOT EXISTS description  TEXT    DEFAULT '';
  ALTER TABLE agents ADD COLUMN IF NOT EXISTS capabilities JSONB   DEFAULT '[]';
  ALTER TABLE agents ADD COLUMN IF NOT EXISTS metadata     JSONB   DEFAULT '{}';

  -- Verificar resultado
  SELECT column_name, data_type, column_default
  FROM information_schema.columns
  WHERE table_name = 'agents'
  ORDER BY ordinal_position;
  