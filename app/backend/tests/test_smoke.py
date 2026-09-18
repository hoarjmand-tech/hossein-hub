from fastapi.testclient import TestClient
def test_health_import():
 from app.main import app
 assert app.title=="Hossein Hub"
def test_safe_name():
 from app.services import safe_name
 assert "/" not in safe_name("../x.pdf")
