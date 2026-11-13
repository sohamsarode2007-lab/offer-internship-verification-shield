from pathlib import Path


def test_frontend_serves_only_built_dist(api_client):
    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    root = api_client.get("/")
    route = api_client.get("/withdraw")

    if (dist / "index.html").is_file():
        assert root.status_code == 200
        assert route.status_code == 200
        assert '<div id="root"></div>' in root.text
        assert "src/main.tsx" not in root.text
    else:
        assert root.status_code == 404
        assert route.status_code == 404

    if (dist / "index.html").is_file():
        response = api_client.get("/ui/")
        assert response.status_code == 200
        assert "src/main.tsx" not in response.text
