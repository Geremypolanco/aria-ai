# 🛠️ Guía de Configuración: Aria v2.2.0 (Real Execution)

Para que Aria pueda operar en tus cuentas reales de Gmail, Shopify y LinkedIn, debes configurar tus credenciales siguiendo estos pasos.

---

## 📧 1. Gmail API
Aria utiliza la API de Gmail para la limpieza quirúrgica de tu inbox.

1. Ve a [Google Cloud Console](https://console.cloud.google.com/).
2. Crea un nuevo proyecto llamado "Aria-AI".
3. Habilita la **Gmail API**.
4. En "Credentials", crea un **OAuth 2.0 Client ID** (Desktop App).
5. Descarga el archivo JSON y cámbiale el nombre a `credentials.json`.
6. Coloca `credentials.json` en la raíz de la carpeta `aria-ai`.
7. Ejecuta Aria; la primera vez se abrirá una ventana en tu navegador para que autorices el acceso. Se generará un archivo `token.json` automáticamente.

---

## 🛍️ 2. Shopify Admin API
Aria gestiona tu tienda, productos e inventario a través de la API de Administración.

1. Entra a tu panel de Shopify (`tu-tienda.myshopify.com/admin`).
2. Ve a **Settings > Apps and sales channels > Develop apps**.
3. Haz clic en **Create an app** y llámala "Aria-Manager".
4. En **Configuration**, habilita los siguientes scopes:
   - `write_products`, `read_products`
   - `write_themes`, `read_themes`
   - `write_inventory`, `read_inventory`
5. Haz clic en **Install app** y copia el **Admin API access token**.
6. Agrega este token en tu archivo `.env` o en el `SecretsManager` de Aria:
   ```env
   SHOPIFY_SHOP_NAME="tu-tienda"
   SHOPIFY_ACCESS_TOKEN="shpat_xxxxxxxxxxxxxxxx"
   ```

---

## 💼 3. LinkedIn API
Aria publica contenido y realiza outreach B2B.

1. Ve a [LinkedIn Developers](https://www.linkedin.com/developers/).
2. Crea una aplicación llamada "Aria-Social".
3. Solicita acceso a los productos:
   - **Share on LinkedIn**
   - **Sign In with LinkedIn**
4. En la pestaña **Auth**, obtén tu **Client ID** y **Client Secret**.
5. Usa una herramienta como Postman o un script de OAuth para obtener un **Access Token** con los scopes `w_member_social` y `r_liteprofile`.
6. Agrega tus datos al archivo `.env`:
   ```env
   LINKEDIN_ACCESS_TOKEN="AQXxxxx..."
   LINKEDIN_PERSON_ID="tu_urn_id"
   ```

---

## 🚀 Ejecución
Una vez configuradas las llaves, Aria detectará automáticamente los motores reales y pasará del modo "Simulación" al modo "Ejecución Real".

Puedes probar la conexión ejecutando:
```bash
python3 scripts/real_transformations.py
```

**Nota de Seguridad**: Nunca compartas tus archivos `token.json` o `.env` con nadie. Aria los mantendrá seguros en el `SecretsManager`.
