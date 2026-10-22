import json
import os
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
run_id = uuid.uuid4().hex[:8]

def request(method, path, payload=None, expected=200):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(req, timeout=20) as response:
            status = response.status
            body = response.read()
    except HTTPError as error:
        status = error.code
        body = error.read()

    if status != expected:
        raise RuntimeError(
            f"{method} {path}: expected {expected}, got {status}: "
            f"{body.decode(errors='replace')}"
        )
    return json.loads(body) if body else None

cast_name = f"Exam Actor {run_id}"
cast = request(
    "POST", "/api/v1/casts/",
    {"name": cast_name, "nationality": "Cameroonian"},
    expected=201,
)
cast_id = cast["id"]
assert request("GET", f"/api/v1/casts/{cast_id}/")["name"] == cast_name
print("PASS: cast created and retrieved")

movie_name = f"Exam Movie {run_id}"
movie = request(
    "POST", "/api/v1/movies/",
    {
        "name": movie_name,
        "plot": "Automated integration test",
        "genres": ["Technology"],
        "casts_id": [cast_id],
    },
    expected=201,
)
movie_id = movie["id"]
saved = request("GET", f"/api/v1/movies/{movie_id}/")
assert saved["name"] == movie_name
assert saved["casts_id"] == [cast_id]
print("PASS: movie created and retrieved with correct cast")

request(
    "POST", "/api/v1/movies/",
    {
        "name": f"Invalid Movie {run_id}",
        "plot": "Must reject an unknown cast",
        "genres": ["Technology"],
        "casts_id": [-1],
    },
    expected=404,
)
print("PASS: movie with unknown cast rejected")

request("DELETE", f"/api/v1/movies/{movie_id}/")
request("GET", f"/api/v1/movies/{movie_id}/", expected=404)
print("PASS: movie deleted and subsequent lookup rejected")
print("Integration test PASSED")
