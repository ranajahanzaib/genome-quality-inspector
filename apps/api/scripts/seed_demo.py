"""Request the API to register and analyze the bundled synthetic fixtures."""

import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

api_url = os.environ.get("GQI_API_URL", "http://127.0.0.1:8000").rstrip("/")
request = Request(f"{api_url}/api/v1/demo/seed", data=b"{}", method="POST")

try:
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
except URLError as exc:
    raise SystemExit(
        f"Could not reach the Genome Quality Inspector API at {api_url}. "
        "Start the API first."
    ) from exc

print(f"Registered {len(result['items'])} synthetic demo datasets:")
for dataset in result["items"]:
    print(f"- {dataset['name']} ({dataset['dataset_type']}): {dataset['status']}")
