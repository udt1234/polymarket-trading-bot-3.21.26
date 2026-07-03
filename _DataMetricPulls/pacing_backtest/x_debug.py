import sys, json, urllib.request, urllib.parse, urllib.error
sys.stdout.reconfigure(encoding='utf-8')
ENV = r"C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\.env"
stored = None
for line in open(ENV, encoding='utf-8'):
    if line.startswith('X_BEARER_TOKEN='):
        stored = line.split('=', 1)[1].strip()

raw_encoded = "AAAAAAAAAAAAAAAAAAAAAMrv%2BAEAAAAA5FgTNAzaunElBnf4D2%2FeRpNwvaU%3D7GcMSF0L1jOQ0GetqkKJIik1HwxPBYFk4pXE90lBh5RN3LvT84"

def hit(label, token, url):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req) as r:
            print(f"[{label}] HTTP {r.status} OK -> {json.loads(r.read())}")
    except urllib.error.HTTPError as e:
        print(f"[{label}] HTTP {e.code}  {e.read().decode()[:200]}")

U = 'https://api.x.com/2/users/by/username/elonmusk'
print("token lengths -> stored(decoded):", len(stored), " raw(encoded):", len(raw_encoded))
hit("decoded  /users", stored, U)
hit("encoded  /users", raw_encoded, U)
# also try the v2 base host api.twitter.com (legacy alias)
hit("decoded  /users (twitter.com)", stored, 'https://api.twitter.com/2/users/by/username/elonmusk')
