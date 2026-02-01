import base64

with open("youtube_token.pkl", "rb") as f:
    encoded = base64.b64encode(f.read()).decode()

print(encoded)
