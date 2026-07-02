import os
from huggingface_hub import InferenceClient

# Token from user
TOKEN = "fm2_lJPECAAAAAAAFPq+xBAt761/jYBv0AfibwVCRWbawrVodHRwczovL2FwaS5mbHkuaW8vdjGWAJLOABn4lh8Lk7lodHRwczovL2FwaS5mbHkuaW8vYWFhL3YxxDwDBy4R7J9pO0+3/9B8tXngroLac8Wj0q2HNVNpTJMq0fcp2YEaxUEuDOWWNiANGgMp9S9MKP4Gq0ysjBzETlfioikJxD90Ef3/B81ghqn7ebTwOFzosKGQyHtZ5R/91EeQkuWh39w1nvr0OWT9YKFgROOcD07YU+Ov9CimX6uVRfezzsG0y2w958I0rg2SlAORgc4BHu1gHwWRgqdidWlsZGVyH6J3Zx8BxCAhAvl1lMdsMFgkkweRdBZ9zb2qj/vjHDVuZfgSIXPj6w=="

def test_hf_hub():
    print("Testing HF via huggingface_hub library...")
    client = InferenceClient(token=TOKEN)
    model = "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B"
    
    try:
        # Simple completion
        response = client.chat_completion(
            model=model,
            messages=[{"role": "user", "content": "Hello, verify you are working."}],
            max_tokens=20
        )
        print("SUCCESS!")
        print(f"Response: {response.choices[0].message.content}")
    except Exception as e:
        print(f"FAILED: {str(e)}")

if __name__ == "__main__":
    test_hf_hub()
