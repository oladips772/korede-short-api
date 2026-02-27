import boto3
from botocore.exceptions import ClientError
from app.config import settings


class S3Storage:
    def __init__(self):
        self.client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        self.bucket = settings.s3_bucket

    def upload_bytes(self, data: bytes, key: str, content_type: str) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return f"https://{self.bucket}.s3.amazonaws.com/{key}"

    def upload_file(self, file_path: str, key: str, content_type: str) -> str:
        self.client.upload_file(
            Filename=file_path,
            Bucket=self.bucket,
            Key=key,
            ExtraArgs={"ContentType": content_type},
        )
        return f"https://{self.bucket}.s3.amazonaws.com/{key}"

    def download_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def download_file(self, key: str, dest_path: str) -> None:
        self.client.download_file(self.bucket, key, dest_path)

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def key_exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False


def get_s3_key(project_id: str, job_id: str, asset_type: str, filename: str) -> str:
    """Build a consistent S3 key path."""
    return f"media-master/{project_id}/{job_id}/{asset_type}/{filename}"


s3 = S3Storage()
