import asyncio
import os
import sys
import httpx

# Token from user
TOKEN = "fm2_lJPECAAAAAAAFPq+xBAt761/jYBv0AfibwVCRWbawrVodHRwczovL2FwaS5mbHkuaW8vdjGWAJLOABn4lh8Lk7lodHRwczovL2FwaS5mbHkuaW8vYWFhL3YxxDwDBy4R7J9pO0+3/9B8tXngroLac8Wj0q2HNVNpTJMq0fcp2YEaxUEuDOWWNiANGgMp9S9MKP4Gq0ysjBzETlfioikJxD90Ef3/B81ghqn7ebTwOFzosKGQyHtZ5R/91EeQkuWh39w1nvr0OWT9YKFgROOcD07YU+Ov9CimX6uVRfezzsG0y2w958I0rg2SlAORgc4BHu1gHwWRgqdidWlsZGVyH6J3Zx8BxCAhAvl1lMdsMFgkkweRdBZ9zb2qj/vjHDVuZfgSIXPj6w=="

async def test_direct_hf():
    print("Testing direct HF Inference API...")
    # Model that is usually available on HF Inference API
    model = "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B"
    # Some environments might have DNS issues with the subdomains, using main domain if possible
    url = f"https://huggingface.co/api/models/{model}/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Hello, are you working?"}],
        "max_tokens": 50
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            print(f"Status: {resp.status_code}")
            if resp.status_code == 200:
                print("SUCCESS! HF is responding.")
                print(f"Response: {resp.json()['choices'][0]['message']['content']}")
            else:
                print(f"FAILED: {resp.text}")
        except Exception as e:
            print(f"ERROR: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_direct_hf())
