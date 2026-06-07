"""
2	Settings centralizados para Aria AI.
3	Todos los secrets se cargan desde variables de entorno o Fly.io secrets.
4	HuggingFace es el motor principal. Groq y OpenAI son respaldo.
5	"""
6	from typing import Optional
7	from pydantic import field_validator
8	from pydantic_settings import BaseSettings, SettingsConfigDict
9	
10	
11	class Settings(BaseSettings):
12	    # ── SISTEMA ───────────────────────────────────────────
13	    ENVIRONMENT: str = "production"
14	    PORT: int = 8000
15	    OWNER_NAME: str = "Señor Polanco"
16	    OWNER_EMAIL: Optional[str] = None
17	    CYCLE_INTERVAL_MINUTES: int = 60
18	    REQUIRE_APPROVAL_FOR_PAYMENTS: bool = True
19	    REQUIRE_APPROVAL_FOR_DEPLOYS: bool = False
20	    MAX_SPEND_WITHOUT_APPROVAL_USD: float = 0.0
21	
22	    # ── NOTIFICACIONES ────────────────────────────────────
23	    TELEGRAM_TOKEN: str = ""
24	    TELEGRAM_BOT_TOKEN: str = ""
25	    TELEGRAM_CHAT_ID: str = ""
26	
27	    @property
28	    def telegram_token(self) -> str:
29	        """Devuelve el token de Telegram disponible."""
30	        return self.TELEGRAM_TOKEN or self.TELEGRAM_BOT_TOKEN
31	
32	    # ── BASE DE DATOS ─────────────────────────────────────
33	    SUPABASE_URL: str = ""
34	    SUPABASE_KEY: str = ""
35	    UPSTASH_REDIS_REST_URL: str = ""
36	    UPSTASH_REDIS_REST_TOKEN: str = ""
37	    REDIS_URL: Optional[str] = None
38	
39	    @field_validator("SUPABASE_URL", mode="before")
40	    @classmethod
41	    def fix_supabase_url(cls, v: str) -> str:
42	        """Corrige URL del dashboard a URL REST del proyecto."""
43	        if not v:
44	            return v
45	        if "supabase.com/dashboard/project/" in v:
46	            project_ref = v.rstrip("/").split("/")[-1]
47	            return f"https://{project_ref}.supabase.co"
48	        return v
49	
50	    # ── HuggingFace (motor principal) ─────────────────────
51	    HF_TOKEN: Optional[str] = None
52	    HF_API_KEY: Optional[str] = None
53	    HUGGING_FACE_TOKEN: Optional[str] = None
54	
55	    @property
56	    def hf_key(self) -> Optional[str]:
57	        """Compatibilidad con ai_client.py: devuelve el HF token."""
58	        return self.HF_TOKEN or self.HF_API_KEY or self.HUGGING_FACE_TOKEN
59	
60	    # ── Modelos HF primarios ───────────────────────────────
61	    HF_MODEL_STRATEGY: str = "Qwen/Qwen2.5-72B-Instruct"
62	    HF_MODEL_CODE: str = "Qwen/Qwen2.5-Coder-7B-Instruct"
63	    HF_MODEL_FAST: str = "microsoft/Phi-3-mini-4k-instruct"
64	    HF_MODEL_CREATIVE: str = "HuggingFaceH4/zephyr-7b-beta"
65	
66	    # ── Modelos HF de respaldo ────────────────────────────
67	    HF_MODEL_STRATEGY_FB: str = "mistralai/Mistral-7B-Instruct-v0.3"
68	    HF_MODEL_CODE_FB: str = "microsoft/Phi-3.5-mini-instruct"
69	    HF_MODEL_FAST_FB: str = "google/flan-t5-large"
70	
71	    # ── Respaldo 1: Groq ──────────────────────────────────
72	    GROQ_API_KEY: Optional[str] = None
73	    GROQ_MODEL: str = "llama-3.3-70b-versatile"
74	    GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"
75	    GROQ_MODEL_CODE: str = "llama-3.3-70b-versatile"
76	
77	    # ── Respaldo 2: OpenAI ────────────────────────────────
78	    OPENAI_API_KEY: Optional[str] = None
79	    OPENAI_MODEL: str = "gpt-4o-mini"
80	
81	    # ── IA Adicional ──────────────────────────────────────
82	    ANTHROPIC_API_KEY: Optional[str] = None
83	    GOOGLE_API_KEY: Optional[str] = None
84	    COHERE_API_KEY: Optional[str] = None
85	
86	    # ── CONTENIDO / SEO ───────────────────────────────────
87	    NEWS_API_KEY: Optional[str] = None
88	    SERP_API_KEY: Optional[str] = None
89	    PEXELS_API_KEY: Optional[str] = None
90	    ELEVENLABS_API_KEY: Optional[str] = None
91	
92	    # ── COMERCIO ──────────────────────────────────────────
93	    GUMROAD_TOKEN: Optional[str] = None
94	    STRIPE_SECRET_KEY: Optional[str] = None
95	    PAYPAL_CLIENT_ID: Optional[str] = None
96	    PAYPAL_SECRET: Optional[str] = None
97	    SHOPIFY_URL: Optional[str] = None
98	    SHOPIFY_API_KEY: Optional[str] = None
99	    SHOPIFY_ADMIN_TOKEN: Optional[str] = None
100	    SHOPIFY_AUTOMATION_TOKEN: Optional[str] = None
101	    
102	    # ── Shopify properties (auto-generados y manuales)
103	    SHOPIFY_SHOP_NAME_MANUAL: Optional[str] = None
104	    SHOPIFY_ACCESS_TOKEN_MANUAL: Optional[str] = None
105	
106	    @property
107	    def SHOPIFY_SHOP_NAME(self) -> str:
108	        """Nombre del shop sin .myshopify.com — extraído de URL o manual."""
109	        if self.SHOPIFY_SHOP_NAME_MANUAL:
110	            return self.SHOPIFY_SHOP_NAME_MANUAL
111	        url = self.SHOPIFY_URL or ""
112	        return url.replace("https://", "").replace("http://", "").replace(".myshopify.com", "").strip("/")
113	
114	    @property
115	    def SHOPIFY_ACCESS_TOKEN(self) -> Optional[str]:
116	        """Token Admin API de Shopify (alias de manual, admin o automation)."""
117	        return self.SHOPIFY_ACCESS_TOKEN_MANUAL or self.SHOPIFY_ADMIN_TOKEN or self.SHOPIFY_AUTOMATION_TOKEN
118	
119	    @property
120	    def SHOPIFY_ENABLED(self) -> bool:
121	        """True si Shopify está configurado con URL/Nombre y token de acceso."""
122	        has_shop = bool(self.SHOPIFY_URL or self.SHOPIFY_SHOP_NAME_MANUAL)
123	        has_token = bool(self.SHOPIFY_ACCESS_TOKEN)
124	        return has_shop and has_token
125	
126	    # ── REDES SOCIALES ────────────────────────────────────
127	    BUFFER_TOKEN: Optional[str] = None
128	    AIRTABLE_TOKEN: Optional[str] = None
129	    MAILCHIMP_API_KEY: Optional[str] = None
130	
131	    # ── MULTIMEDIA ────────────────────────────────────────
132	    CLOUDINARY_CLOUD_NAME: Optional[str] = None
133	    CLOUDINARY_API_KEY: Optional[str] = None
134	    CLOUDINARY_API_SECRET: Optional[str] = None
135	
136	    # ── DESARROLLO ────────────────────────────────────────
137	    GITHUB_TOKEN: Optional[str] = None
138	    GITHUB_USERNAME: str = "Geremypolanco"
139	    VERCEL_TOKEN: Optional[str] = None
140	    NOTION_TOKEN: Optional[str] = None
141	    FACEBOOK_MARKETING_TOKEN: Optional[str] = None
142	    FACEBOOK_AD_ACCOUNT_ID: Optional[str] = None
143	    DID_API_KEY: Optional[str] = None
144	    CANVA_CLIENT_ID: Optional[str] = None
145	    CANVA_CLIENT_SECRET: Optional[str] = None
146	    ARIA_BASE_URL: str = "https://aria-ai.fly.dev"
147	    ZAPIER_WEBHOOK_URL: Optional[str] = None
148	    SOCIAL_CONNECT_TOKEN: str = "aria"
149	
150	    # ── CONOCIMIENTO / KNOWLEDGE SUITE ────────────────────
151	    WOLFRAM_APP_ID: Optional[str] = None         # developer.wolframalpha.com (gratis)
152	    ALPHA_VANTAGE_KEY: Optional[str] = None      # alphavantage.co (gratis 5 req/min)
153	    GNEWS_API_KEY: Optional[str] = None          # gnews.io (gratis 100 req/día)
154	    CHROMA_PERSIST_DIR: str = "/data/chroma"     # directorio local ChromaDB
155	
156	    # ── COMUNICACIÓN ──────────────────────────────────────
157	    TWILIO_ACCOUNT_SID: Optional[str] = None
158	    TWILIO_AUTH_TOKEN: Optional[str] = None
159	
160	    model_config = SettingsConfigDict(
161	        env_file=".env",
162	        env_file_encoding="utf-8",
163	        extra="ignore",
164	        case_sensitive=True,
165	    )
166	
167	
168	settings = Settings()
169	
