import requests

endpoints = ['wildfires', 'vegetation', 'climate']
base_url = 'http://localhost:8000'

for ep in endpoints:
    try:
        print(f"Testing /{ep}")
        res = requests.get(f"{base_url}/{ep}")
        res.raise_for_status()
        data = res.json()
        
        print(f"  Type : {data.get('type')}")
        if 'features' in data:
            print(f"  Count: {len(data['features'])}")
            if len(data['features']) > 0:
                print(f"  First Feature Geometry: {data['features'][0].get('geometry')}")
                print(f"  First Feature Props: {data['features'][0].get('properties')}")
        else:
            print(f"  No 'features' key found! Keys: {list(data.keys())}")
        print("-" * 40)
    except Exception as e:
        print(f"  Failed: {e}")
