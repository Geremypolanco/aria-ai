# ── ARIA Agent System — Políticas Vault ──────────────────

# Política para agentes (lectura de secrets operacionales)
path "secret/data/agents/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/agents/*" {
  capabilities = ["read", "list"]
}

# Política para tools (lectura de secrets de integraciones)
path "secret/data/tools/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/tools/*" {
  capabilities = ["read", "list"]
}

# Política para administradores (lectura/escritura global)
path "secret/data/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "secret/metadata/*" {
  capabilities = ["read", "delete", "list"]
}

path "secret/delete/*" {
  capabilities = ["update"]
}

# Auditoría
path "sys/audit/*" {
  capabilities = ["read", "create", "update"]
}

# Health check
path "sys/health" {
  capabilities = ["read", "list"]
}
