def test_safe_name():
 from app.services import safe_name
 assert "/" not in safe_name("../x.pdf")
