from unittest.mock import MagicMock, patch
from app.services.s3 import S3Storage, get_s3_key


def test_get_s3_key():
    key = get_s3_key("proj-1", "job-2", "images", "scene_001.png")
    assert key == "media-master/proj-1/job-2/images/scene_001.png"


@patch("app.services.s3.boto3")
def test_upload_bytes_returns_url(mock_boto3):
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    storage = S3Storage()
    storage.bucket = "test-bucket"
    url = storage.upload_bytes(b"data", "some/key.png", "image/png")

    mock_client.put_object.assert_called_once()
    assert "test-bucket" in url
    assert "some/key.png" in url
