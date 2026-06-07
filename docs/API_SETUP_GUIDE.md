# Guía Completa de Configuración de APIs para Aria AI

Aria AI soporta integraciones con múltiples plataformas sociales para automatizar la publicación de contenido, interacción con usuarios y gestión de comercio electrónico. Esta guía detalla el proceso para obtener las credenciales necesarias (Client ID, Client Secret, etc.) para **LinkedIn**, **TikTok**, **TikTok Shop Seller**, **Facebook** e **Instagram**, de manera que puedan ser configuradas en el archivo `.env` del proyecto.

---

## 1. LinkedIn

Aria requiere acceso a la API de LinkedIn para publicar contenido y gestionar interacciones.

### Pasos para obtener las credenciales:

1. Ingresa al [LinkedIn Developer Portal](https://www.linkedin.com/developers/).
2. Haz clic en **Create app** (Crear aplicación).
3. Completa la información requerida:
   * **App name:** Elige un nombre para tu aplicación (ej. Aria AI Social).
   * **LinkedIn Page:** Asocia la aplicación a una página de empresa existente de LinkedIn o crea una nueva.
   * **Privacy policy URL:** (Opcional pero recomendado).
   * **App logo:** Sube un logo.
4. Una vez creada, ve a la pestaña **Auth** (Autenticación).
5. Aquí encontrarás tu **Client ID** y **Client Secret**.
6. En la misma pestaña, bajo **OAuth 2.0 settings**, añade la URL de redirección (Redirect URL) que utiliza Aria:
   * `https://tu-dominio-aria.fly.dev/auth/callback/linkedin` (reemplaza `tu-dominio-aria.fly.dev` por tu URL base configurada en `ARIA_BASE_URL`).
7. Ve a la pestaña **Products** (Productos) y solicita acceso a los productos necesarios para publicar contenido:
   * **Share on LinkedIn** (Compartir en LinkedIn)
   * **Sign In with LinkedIn using OpenID Connect** (Iniciar sesión con LinkedIn)

### Variables de entorno a configurar en Aria:
```env
LINKEDIN_CLIENT_ID="tu_client_id_aqui"
LINKEDIN_CLIENT_SECRET="tu_client_secret_aqui"
```

---

## 2. TikTok

Para publicar videos en TikTok, Aria utiliza la TikTok Content Posting API.

### Pasos para obtener las credenciales:

1. Crea una cuenta de desarrollador en [TikTok for Developers](https://developers.tiktok.com/).
2. Ve a **Manage apps** y haz clic en **Connect an app** (Conectar una aplicación).
3. Selecciona la plataforma (Web/Desktop) y completa los detalles de la aplicación (Nombre, descripción, categoría, ícono).
4. En la sección **Products** (Productos), añade **Login Kit** y **Content Posting API** (Direct Post o Upload).
5. Configura la **Redirect URI** para OAuth:
   * `https://tu-dominio-aria.fly.dev/auth/callback/tiktok`
6. Ve a la sección **App details** -> **Credentials**. Aquí encontrarás tu **Client Key** y **Client Secret**.
7. Debes enviar la aplicación a revisión (**Submit for review**) para poder usarla en modo Producción.

### Variables de entorno a configurar en Aria:
```env
TIKTOK_CLIENT_KEY="tu_client_key_aqui"
TIKTOK_CLIENT_SECRET="tu_client_secret_aqui"
```

---

## 3. TikTok Shop Seller

TikTok está transicionando todas las integraciones de vendedores al TikTok Shop Partner Center.

### Pasos para obtener las credenciales:

1. Regístrate en el [TikTok Shop Partner Center](https://partner.tiktokshop.com/).
   * _Nota: Asegúrate de elegir el portal correcto (US Partner Portal para tiendas en EE. UU., o Global para otros mercados)._
2. Haz clic en **App & Service** y luego en **Create app & service**.
3. Selecciona el tipo de aplicación: **Custom app** (si es solo para tu propia tienda) o **Public app** (si planeas distribuirla a otros vendedores).
4. Completa la información de la aplicación (Nombre, categoría, etc.).
5. Configura tu **Redirect URL** y tu **Webhook URL** (si Aria manejará webhooks de órdenes).
6. Selecciona los permisos (Scopes) necesarios para la API (ej. Gestión de productos, Gestión de órdenes, Inventario).
7. Una vez creada, obtendrás tu **App Key** y **App Secret**.
8. Envía la aplicación a revisión. Una vez aprobada, podrás generar tokens de acceso para conectar tu tienda.

### Alternativa sin API oficial (Session Cookies):
Aria también soporta conectarse a TikTok Shop Seller utilizando cookies de sesión si no tienes una aplicación aprobada.
1. Inicia sesión en TikTok Shop Seller Center en Chrome.
2. Usa la extensión **Cookie-Editor**.
3. Exporta las cookies como JSON y envíalas a Aria a través de Telegram (`/sesion tiktok_shop`). La cookie clave requerida es `sessionid`.

---

## 4. Facebook e Instagram

Facebook e Instagram utilizan la misma infraestructura de aplicaciones en Meta for Developers. Aria utiliza la Graph API para interactuar con ambas plataformas.

### Pasos para obtener las credenciales:

1. Inicia sesión en [Meta for Developers](https://developers.facebook.com/).
2. Haz clic en **My Apps** (Mis aplicaciones) y luego en **Create App** (Crear aplicación).
3. Selecciona los casos de uso necesarios. Para Aria, generalmente necesitarás:
   * **Authenticate and request data from users with Facebook Login** (Autenticar usuarios).
   * **Manage everything on your Page** (Administrar páginas).
   * **Manage messaging & content on Instagram** (Administrar contenido en Instagram).
4. Completa el nombre de la aplicación y asóciala a una cuenta de administrador comercial (Business Manager).
5. En el panel de control de la aplicación (App Dashboard), ve a **App Settings** -> **Basic** (Configuración -> Básica).
6. Aquí encontrarás tu **App ID** y **App Secret**.
7. Configura los productos **Facebook Login** e **Instagram Graph API**.
8. En la configuración de Facebook Login, añade la **Valid OAuth Redirect URI**:
   * Para Facebook: `https://tu-dominio-aria.fly.dev/auth/callback/facebook`
   * Para Instagram: `https://tu-dominio-aria.fly.dev/auth/callback/instagram`
9. **Permisos requeridos (Scopes):**
   * **Facebook:** `pages_manage_posts`, `pages_read_engagement`, `publish_to_groups`, `email`, `public_profile`.
   * **Instagram:** `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`.
   * _Nota: Para publicar en Instagram mediante la API, la cuenta de Instagram debe ser una cuenta Profesional (Business o Creator) y estar vinculada a una Página de Facebook._

### Variables de entorno a configurar en Aria:
```env
FACEBOOK_APP_ID="tu_app_id_aqui"
FACEBOOK_APP_SECRET="tu_app_secret_aqui"
```
_(Instagram utiliza las mismas variables `FACEBOOK_APP_ID` y `FACEBOOK_APP_SECRET` en la configuración de Aria)._

---

## Consideración sobre URLs y Callbacks

Asegúrate de que la variable `ARIA_BASE_URL` en tu archivo `.env` o en los secretos de Fly.io esté correctamente configurada con el dominio público de tu servidor (por ejemplo, `https://aria-ai.fly.dev`). Esta URL se utiliza dinámicamente para generar las URLs de redirección (callbacks) durante el proceso de autorización OAuth.

```env
ARIA_BASE_URL="https://tu-dominio-aria.fly.dev"
```

## Referencias

[1] [LinkedIn Developer FAQ](https://developer.linkedin.com/support/faq)
[2] [TikTok for Developers: Register Your App](https://developers.tiktok.com/doc/getting-started-create-an-app)
[3] [TikTok Shop Partner Center](https://partner.tiktokshop.com/)
[4] [Meta for Developers: Create an App](https://developers.facebook.com/docs/development/create-an-app/)
[5] [Meta for Developers: Instagram Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
