# Guía Paso a Paso: Obtención de APIs para Aria AI (Edición 2025)

Esta guía proporciona instrucciones precisas y actualizadas para obtener las credenciales de las plataformas restantes. He configurado Aria para que use estas credenciales directamente, eliminando la dependencia de Zapier donde ha sido posible.

---

## 1. Facebook e Instagram (Meta Graph API)
*Meta ha unificado estas APIs. Necesitas una cuenta de Facebook y una cuenta de Instagram Profesional vinculada a una Página de Facebook.*

### Paso 1: Crear la App en Meta
1. Ve a [Meta for Developers](https://developers.facebook.com/) e inicia sesión.
2. Haz clic en **"Mis aplicaciones"** -> **"Crear aplicación"**.
3. Selecciona **"Otro"** como tipo de aplicación y haz clic en **"Siguiente"**.
4. Selecciona **"Empresa"** (esto te da acceso a las APIs de Instagram y Facebook Pages).
5. Dale un nombre (ej. `Aria_AI_Integration`) y selecciona tu cuenta de Business Manager si tienes una.

### Paso 2: Configurar Instagram Graph API
1. En el panel lateral, busca **"Añadir producto"** y selecciona **"Instagram Graph API"**.
2. Ve a **"Configuración"** -> **"Básica"** para copiar tu `App ID` y `App Secret`.
3. En **"Inicio de sesión con Facebook"** -> **"Configuración"**, añade esta URL en "URIs de redireccionamiento OAuth válidos":
   * `https://aria-ai.fly.dev/auth/callback/instagram`

### Paso 3: Permisos Críticos (Scopes)
Para que Aria publique sin Zapier, debes solicitar estos permisos en **"Generador de tokens"** o al autorizar:
* `instagram_basic`
* `instagram_content_publish`
* `pages_read_engagement`
* `pages_show_list`
* `ads_management` (opcional para reportes)

---

## 2. TikTok (Content Posting API)
*TikTok requiere que la app sea aprobada para publicar videos directamente.*

### Paso 1: Registro en TikTok for Developers
1. Ve a [TikTok for Developers](https://developers.tiktok.com/).
2. Haz clic en **"Manage apps"** -> **"Connect an app"**.
3. Elige **"Web"** como plataforma.

### Paso 2: Configuración de la App
1. Copia tu `Client Key` y `Client Secret`.
2. En **"Redirect URI"**, añade:
   * `https://aria-ai.fly.dev/auth/callback/tiktok`
3. En la sección **"Products"**, debes añadir:
   * **Login Kit** (para autenticar).
   * **Video Kit** o **Content Posting API** (para publicar).

### Paso 3: Revisión de la App
*TikTok es estricto. Debes subir un video corto mostrando cómo Aria usará la API para que te aprueben el scope de publicación (`video.upload`).*

---

## 3. TikTok Shop Seller (API Directa)
*Ideal para gestionar inventario y órdenes directamente en Aria.*

### Paso 1: Partner Center
1. Regístrate en [TikTok Shop Partner Center](https://partner.tiktokshop.com/).
2. Crea una **"Custom App"**.
3. Selecciona los scopes de **"Product Management"** y **"Order Management"**.

### Paso 2: Credenciales
1. Obtendrás un `App Key` y `App Secret`.
2. **Importante:** Debes autorizar tu propia tienda usando el enlace de autorización que genera el Partner Center.

---

## Resumen de Variables Configuradas
He actualizado el sistema para que priorice estas variables:

| Plataforma | Variable en Aria | Estado Actual |
| :--- | :--- | :--- |
| **LinkedIn** | `LINKEDIN_CLIENT_ID` | ✅ Configurado |
| **Shopify** | `SHOPIFY_ACCESS_TOKEN` | ✅ Configurado (API Directa) |
| **Facebook** | `FACEBOOK_APP_ID` | ⏳ Pendiente (Tu parte) |
| **TikTok** | `TIKTOK_CLIENT_KEY` | ⏳ Pendiente (Tu parte) |

---

## ¿Cómo ingresar las nuevas APIs?
Una vez que las obtengas, puedes enviármelas por aquí o usar el comando en Telegram:
`/config set NOMBRE_VARIABLE valor`

Aria detectará automáticamente las nuevas credenciales y activará los módulos correspondientes sin necesidad de Zapier.
