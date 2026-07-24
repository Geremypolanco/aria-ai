"""
ARIA Business Intelligence & Sales Knowledge Base v2.0
Contains sales techniques, consumer psychology, copywriting, marketing strategies,
Shopify best practices, Zapier automations, and High-Ticket service sales.
This module acts as a "wisdom library" that agents consult to optimize results.
"""

# ── CLASSIC SALES TECHNIQUES ──────────────────────────────────────────────────

SALES_TECHNIQUES = {
    "closing": [
        "The Assumptive Close: Act as if the customer has already decided to buy.",
        "The Urgency Close: Create real or time-limited scarcity (Limited time offer).",
        "The Puppy Dog Close: Offer a no-commitment trial.",
        "The Ben Franklin Close: List pros and cons, ensuring the pros win by far.",
        "The Summary Close: Summarize all agreed-upon benefits before asking for the decision.",
        "The Question Close: 'What would you need to see to make this decision today?'",
    ],
    "psychology": [
        "Social Proof: Show that others are already getting results.",
        "Reciprocity: Give free value before asking for the sale.",
        "Authority: Position ARIA as the undisputed expert in the niche.",
        "Commitment & Consistency: Get small 'yeses' before the big 'yes'.",
        "Scarcity: Genuinely limit availability to increase desire.",
        "Loss Aversion: Show what the customer loses by NOT acting now.",
        "Anchoring: Present the high price first so the real one seems reasonable.",
    ],
    "copywriting": [
        "AIDA: Attention, Interest, Desire, Action.",
        "PAS: Problem, Agitation, Solution.",
        "Before-After-Bridge: Show the current state, the desired state, and how the product is the bridge.",
        "The 4 P's: Promise, Picture, Proof, Push.",
        "FAB: Features, Advantages, Benefits — always end on the benefit to the customer.",
        "Storytelling: Use real customer stories to create emotional connection.",
    ],
    "follow_up": [
        "The 3-Day Rule: First follow-up 3 days after no response.",
        "Value-First Follow-up: Send a useful resource instead of just asking 'did you see my message?'.",
        "The 'Break-up' Email: One last polite message stating we'll stop following up (creates urgency).",
        "Multi-channel Follow-up: Combine email, LinkedIn, and Telegram for greater reach.",
        "Automated Sequences: Use Zapier + Mailchimp for automated nurturing sequences.",
    ],
}

# ── MARKETING STRATEGIES ──────────────────────────────────────────────────────

MARKETING_STRATEGY = {
    "linkedin_authority": [
        "Hook: Start with a strong statement or a question in the first 3 lines.",
        "Body: Use short paragraphs, lists, and white space for mobile readability.",
        "CTA: Soft calls to action ('What do you think?') or direct ones ('Click here').",
        "Storytelling: Share the 'behind the scenes' of creating products on Shopify.",
        "Expertise: Publish technical insights on AI and the circular economy to build trust.",
    ],
    "shopify_seo_mastery": [
        "Titles: Main keyword + Benefit + Brand.",
        "Meta Desc: Max 160 characters with a strong CTA.",
        "URL Slugs: Short and descriptive, keywords only.",
    ],
    "content_pillars": [
        "Educational: Teach how to solve a specific problem.",
        "Inspirational: Success stories and transformations.",
        "Promotional: Direct offers and product benefits.",
        "Engagement: Questions and polls to get to know the audience.",
        "Behind-the-Scenes: Show the product creation process to build trust.",
    ],
    "distribution_channels": {
        "organic": [
            "SEO Blogs",
            "X (Twitter) Threads",
            "LinkedIn Articles",
            "Reddit Communities",
            "Organic TikTok",
        ],
        "paid": ["Meta Ads", "Google Search", "TikTok Spark Ads", "Google Shopping"],
        "direct": ["Email Newsletters", "Telegram Channel", "Direct Outreach", "WhatsApp Business"],
        "ecommerce": ["Shopify Store", "Google Shopping", "Instagram Shopping", "TikTok Shop"],
    },
}

# ── SHOPIFY KNOWLEDGE ─────────────────────────────────────────────────────────

SHOPIFY_KNOWLEDGE = {
    "listing_optimization": [
        "SEO Title: include main keyword, brand, and key attribute (max 70 characters).",
        "Persuasive HTML description: use AIDA format with short paragraphs and bullet points.",
        "Images: minimum 3-5 high-resolution photos. White background for comparison + lifestyle.",
        "Image alt text: include main keyword and product description.",
        "Competitive pricing: research competitors. Show original price struck through (compare_at_price).",
        "Inventory: always manage through Shopify to avoid overselling.",
        "Tags: include 10-15 relevant tags for internal search and marketing apps.",
        "SEO metafields: optimize SEO title (max 70 chars) and meta description (max 160 chars).",
        "Structured data: ensure Product schema for Google Shopping and rich snippets.",
        "Reviews: set up a review app (Judge.me, Yotpo) to generate social proof.",
        "Collections: organize products into logical collections to improve navigation and SEO.",
        "Videos: add a 30-90 second product video to increase conversion.",
    ],
    "store_optimization": [
        "Fast theme: use Shopify 2.0 themes (Dawn, Debut) for better performance.",
        "Core Web Vitals: optimize LCP, FID, and CLS to improve Google ranking.",
        "Mobile-first: ensure the store is flawless on mobile (70%+ of traffic).",
        "Optimized checkout: reduce steps to a minimum and offer multiple payment methods.",
        "Upsell and Cross-sell: set up recommendation apps (ReConvert, Frequently Bought Together).",
        "Abandoned Cart Recovery: set up automatic emails at 1h, 24h, and 72h.",
        "Live Chat: add live chat to resolve questions and increase conversion.",
        "Trust Badges: display security seals, guarantees, and payment methods.",
        "Load speed: compress images, use a CDN, and minimize unnecessary apps.",
    ],
    "product_research": [
        "Analyze Google Trends to identify products in an upward trend.",
        "Check Amazon Best Sellers and Movers & Shakers to validate demand.",
        "Study TikTok Shop and viral hashtags for trending products.",
        "Calculate margin: selling price should be at least 3x the cost (the 3x rule).",
        "Check restrictions: avoid products with patents, regulations, or high competition.",
        "Evaluate upsell potential: products with recurring accessories or consumables.",
        "Analyze competitors' negative reviews to identify market gaps.",
        "Validate with keyword research: at least 1,000 monthly searches for the product.",
    ],
    "marketing_channels": [
        "Google Shopping: sync catalog with Google Merchant Center for free traffic.",
        "Instagram Shopping: tag products in posts and stories for direct purchase.",
        "TikTok Shop: integrate the store to take advantage of TikTok's viral traffic.",
        "Pinterest Shopping: ideal for visual products (fashion, home, decor).",
        "Email Marketing: Klaviyo or Mailchimp for welcome, abandonment, and post-purchase sequences.",
        "SMS Marketing: Postscript or Attentive for high-open-rate notifications.",
        "Influencer Marketing: collaborate with micro-influencers (10K-100K) for better ROI.",
        "Retargeting Ads: Meta Pixel and Google Ads to recover visitors who didn't buy.",
    ],
}

# ── ZAPIER + SHOPIFY KNOWLEDGE ────────────────────────────────────────────────

ZAPIER_SHOPIFY_AUTOMATIONS = {
    "revenue_generation": [
        "Quiz/Form → OpenAI → Email: AI-personalized product consulting (Revenue First Strategy).",
        "Abandoned Cart → Gmail/SMS: personalized reminder at 1h, 24h, and 72h.",
        "New Customer → Klaviyo: 7-email welcome sequence with value and offers.",
        "Product Back in Stock → Email List: notify customers on the waiting list.",
        "High-Value Order → Slack + CRM: alert for personalized VIP follow-up.",
    ],
    "operations": [
        "New Order → Google Sheets: log sales for automatic analysis and reports.",
        "New Order → Gmail/Slack: notify the team of each sale in real time.",
        "Inventory Updated → Gmail: alert when stock falls below the minimum threshold.",
        "New Paid Order → Airtable: sync data for operations management.",
        "Fraud Order → Slack: alert immediately to stop shipment.",
    ],
    "customer_retention": [
        "New Customer → HubSpot/Salesforce: create a contact in CRM for follow-up.",
        "New Customer → Mailchimp: add to email marketing list (with GDPR consent).",
        "Post-Purchase → Typeform: send satisfaction survey after 7 days.",
        "VIP Customer (LTV > $500) → Slack: identify and give special treatment.",
        "Repeat Customer → Discount Code: send automatic discount code.",
    ],
    "ai_powered": [
        "New Order → OpenAI → Personalized Thank You Email: unique thank-you email.",
        "Customer Review → OpenAI → Response: respond to reviews automatically with AI.",
        "New Product → OpenAI → Social Post: automatically generate a social media post.",
        "Sales Data → OpenAI → Weekly Report: sales report with AI insights.",
        "Customer Query → OpenAI → Support Response: 24/7 AI customer support.",
    ],
}

# ── HIGH-TICKET SALES ─────────────────────────────────────────────────────────

HIGH_TICKET_KNOWLEDGE = {
    "service_categories": [
        "Business Consulting: $1,000 - $10,000/month. Help companies scale.",
        "Executive Coaching: $500 - $5,000/session. Leadership and strategy development.",
        "Custom Software Development: $5,000 - $50,000/project.",
        "Digital Marketing Agency: $2,000 - $20,000/month. Full marketing management.",
        "Corporate Training: $3,000 - $30,000/program. Team upskilling.",
        "Premium Brand Design: $5,000 - $25,000/project. Complete visual identity.",
        "AI Automation: $3,000 - $15,000/project. Implement AI in businesses.",
        "E-commerce Consulting: $2,000 - $10,000/month. Optimize online stores.",
    ],
    "qualification_process": [
        "Application form: filter prospects with 5-7 key questions about budget and goals.",
        "Discovery call: 30 min to understand the problem and evaluate fit.",
        "Custom proposal: 3-5 page document with specific solution and expected ROI.",
        "Proposal presentation: 60 min call to present and handle objections.",
        "Contract and onboarding: premium onboarding process that justifies the price.",
    ],
    "pricing_strategies": [
        "Value-Based Pricing: charge based on value generated, not time invested.",
        "Retainer Model: recurring monthly billing for predictable revenue.",
        "Performance-Based: charge a % of the results generated (e.g.: 10% of the sales increase).",
        "Productized Services: package the service as a product with a fixed price and clear deliverables.",
        "Tiered Packages: offer 3 tiers (Basic, Professional, Premium) to maximize conversion.",
    ],
    "objection_handling": [
        "'It's too expensive': Reframe around the cost of NOT solving the problem. Show specific ROI.",
        "'I need to think about it': Ask what additional information they need to decide.",
        "'I don't have the budget': Explore installment payment options or start with a pilot project.",
        "'Why you and not someone else?': Present specific success stories and unique differentiators.",
        "'I need to check with my partner': Offer to include the partner on the next call.",
    ],
    "shopify_integration": [
        "Create a service page on Shopify with a detailed description and an application button.",
        "Use Shopify to charge deposits or initial service payments.",
        "Create digital products (ebooks, courses) as an entry point into the High-Ticket funnel.",
        "Set up Zapier so new entry-product purchases trigger a sales follow-up.",
        "Use Shopify Analytics to identify high-value (LTV) customers for premium offers.",
    ],
}

# ── EXPANDED VOCABULARY ───────────────────────────────────────────────────────

VOCABULARY_EXPANSION = {
    "persuasive_verbs": [
        "Accelerate",
        "Unlock",
        "Master",
        "Scale",
        "Transform",
        "Maximize",
        "Automate",
        "Conquer",
        "Simplify",
        "Empower",
        "Optimize",
        "Multiply",
    ],
    "emotional_triggers": [
        "Exclusive",
        "Instant",
        "Guaranteed",
        "Revealed",
        "Limited",
        "Secret",
        "Proven",
        "Powerful",
        "Essential",
        "Lucrative",
        "Premium",
        "Elite",
    ],
    "business_terms": [
        "ROI (Return on Investment)",
        "LTV (Lifetime Value)",
        "CAC (Customer Acquisition Cost)",
        "Churn Rate",
        "Conversion Rate Optimization (CRO)",
        "Scalability",
        "Synergy",
        "Average Order Value (AOV)",
        "Customer Retention Rate",
        "Net Promoter Score (NPS)",
        "Gross Margin",
        "MRR (Monthly Recurring Revenue)",
        "ARR (Annual Recurring Revenue)",
    ],
    "ecommerce_terms": [
        "Listing Optimization",
        "Product-Market Fit",
        "Abandoned Cart Recovery",
        "Upsell",
        "Cross-sell",
        "Bundle",
        "Flash Sale",
        "BFCM (Black Friday Cyber Monday)",
        "Dropshipping",
        "Print-on-Demand",
        "Private Label",
        "White Label",
        "SKU (Stock Keeping Unit)",
        "COGS (Cost of Goods Sold)",
        "Fulfillment",
    ],
}


# ── ACCESS FUNCTIONS ──────────────────────────────────────────────────────────


def get_sales_advice(category: str = "closing") -> list:
    return SALES_TECHNIQUES.get(category, [])


def get_marketing_strategy() -> dict:
    return MARKETING_STRATEGY


def get_vocab() -> dict:
    return VOCABULARY_EXPANSION


def get_shopify_knowledge(category: str = "listing_optimization") -> list:
    """Gets specific Shopify knowledge by category."""
    return SHOPIFY_KNOWLEDGE.get(category, [])


def get_zapier_automations(category: str = "revenue_generation") -> list:
    """Gets recommended Zapier automations by category."""
    return ZAPIER_SHOPIFY_AUTOMATIONS.get(category, [])


def get_high_ticket_knowledge(category: str = "service_categories") -> list:
    """Gets High-Ticket sales knowledge by category."""
    return HIGH_TICKET_KNOWLEDGE.get(category, [])


def get_full_ecommerce_playbook() -> dict:
    """Returns the complete e-commerce playbook for Aria."""
    return {
        "shopify": SHOPIFY_KNOWLEDGE,
        "zapier": ZAPIER_SHOPIFY_AUTOMATIONS,
        "high_ticket": HIGH_TICKET_KNOWLEDGE,
        "sales": SALES_TECHNIQUES,
        "marketing": MARKETING_STRATEGY,
        "vocabulary": VOCABULARY_EXPANSION,
    }
