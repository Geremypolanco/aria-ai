# 🛠️ Setup Guide: Connecting Gmail, Shopify, and LinkedIn

To let ARIA operate on your real Gmail, Shopify, and LinkedIn accounts, configure the credentials below.

---

## 📧 1. Gmail

Gmail goes through ARIA's connector hub — the same one-click "Connect" flow used for every other integration (Slack, Notion, HubSpot, etc.), not a manually downloaded credentials file.

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project called "Aria-AI".
3. Enable the **Gmail API**.
4. Under **Credentials**, create an **OAuth 2.0 Client ID** (Web application), and add your deployed app's URL + `/connectors/google/callback` as an authorized redirect URI.
5. Set these in your `.env` or Fly.io secrets:
   ```env
   GOOGLE_CLIENT_ID="xxxxxxxx.apps.googleusercontent.com"
   GOOGLE_CLIENT_SECRET="xxxxxxxx"
   ```
6. In the running app, open **Settings → Connectors → Google** and click **Connect** to complete the OAuth flow. Tokens are stored server-side, scoped to your account — no local files to manage.

---

## 🛍️ 2. Shopify Admin API

ARIA manages your store, products, and inventory through the Admin API using a direct access token (not the connector-hub OAuth flow).

1. Open your Shopify admin (`your-store.myshopify.com/admin`).
2. Go to **Settings → Apps and sales channels → Develop apps**.
3. Click **Create an app** and name it "Aria-Manager".
4. Under **Configuration**, enable these scopes:
   - `write_products`, `read_products`
   - `write_themes`, `read_themes`
   - `write_inventory`, `read_inventory`
5. Click **Install app** and copy the **Admin API access token**.
6. Set these in your `.env` or Fly.io secrets:
   ```env
   SHOPIFY_URL="https://your-store.myshopify.com"
   SHOPIFY_ADMIN_TOKEN="shpat_xxxxxxxxxxxxxxxx"
   ```

---

## 💼 3. LinkedIn API

ARIA publishes content and runs B2B outreach using a direct access token (not the connector-hub OAuth flow).

1. Go to [LinkedIn Developers](https://www.linkedin.com/developers/).
2. Create an app called "Aria-Social".
3. Request access to these products:
   - **Share on LinkedIn**
   - **Sign In with LinkedIn**
4. On the **Auth** tab, get your **Client ID** and **Client Secret**.
5. Use a tool like Postman, or an OAuth script, to get an **Access Token** with the `w_member_social` and `r_liteprofile` scopes, plus your profile's author URN.
6. Set these in your `.env`:
   ```env
   LINKEDIN_ACCESS_TOKEN="AQXxxxx..."
   LINKEDIN_PERSON_URN="urn:li:person:xxxxxxxx"
   ```

---

## 🚀 Verifying the connection

Once credentials are set, ARIA automatically picks up each real integration — no separate "switch to real mode" step. Check `/api/v1/connectors/status` (or **Settings → Connectors** in the app) to confirm each service shows as connected.

**Security note**: never share your `.env` file or Fly.io secrets with anyone. ARIA keeps tokens server-side and never commits them to the codebase.
