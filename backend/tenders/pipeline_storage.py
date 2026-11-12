"""Private S3 storage shared by web and worker; large bodies stay on disk."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import boto3
from botocore.config import Config
from django.conf import settings


def client():
    return boto3.client('s3', endpoint_url=settings.PIPELINE_S3_ENDPOINT,
        aws_access_key_id=settings.PIPELINE_S3_ACCESS_KEY,
        aws_secret_access_key=settings.PIPELINE_S3_SECRET_KEY,
        region_name='us-east-1', config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}))


def store(path, digest):
    if not settings.PIPELINE_S3_ENDPOINT:
        import shutil
        target = settings.MEDIA_ROOT / 'indexed' / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(path).resolve() != target.resolve():
            shutil.copyfile(path, target)
        return str(target)
    key = f'sha256/{digest[:2]}/{digest}'
    client().upload_file(str(path), settings.PIPELINE_S3_BUCKET, key)
    return f's3://{settings.PIPELINE_S3_BUCKET}/{key}'


def object_key(reference):
    prefix = f's3://{settings.PIPELINE_S3_BUCKET}/'
    if not reference.startswith(prefix):
        raise ValueError('Dokument ni v skupni shrambi.')
    return reference[len(prefix):]


@contextmanager
def local_file(reference):
    if not reference.startswith('s3://'):
        yield Path(reference)
        return
    with TemporaryDirectory(prefix='razpizi-object-') as directory:
        path = Path(directory) / 'document'
        client().download_file(settings.PIPELINE_S3_BUCKET, object_key(reference), str(path))
        yield path


def stream(reference):
    return client().get_object(Bucket=settings.PIPELINE_S3_BUCKET, Key=object_key(reference))['Body']
