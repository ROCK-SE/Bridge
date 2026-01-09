import logging
import os
import random
import time
import urllib.request

import pymongo
from pymongo.collection import Collection
from scipy.stats import norm

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def is_strict_ver(identifier: str):
    parts = identifier.split(".")
    if len(parts) > 3:
        return False
    if all(p.isnumeric() for p in parts):
        return True
    return False


def download(
    url: str, save_path: str, check: bool = True, size: int = -1, max_try=3
) -> bool:
    if check and os.path.exists(save_path) and (os.path.getsize(save_path) == size):
        return True

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    success = False
    i = 0

    while (not success) and (i < max_try):
        try:
            urllib.request.urlretrieve(url, save_path)
            success = True
        except Exception as e:
            i += 1
            logger.error(f"Error downloading {url}, retry {i}: {e}")

    return success


def gen_jar_url_path(name: str, version: str):
    group_id, artifact_id = name.split(":")
    group_path = "/".join(group_id.split("."))
    jar_name = f"{artifact_id}-{version}.jar"
    url = (
        f"https://repo1.maven.org/maven2/{group_path}"
        + f"/{artifact_id}/{version}/{jar_name}"
    )
    save_path = os.path.join(group_path, jar_name)
    return url, save_path


def polite_download(url, save_path: str):
    download(url, save_path)
    time.sleep(random.random() * 3)


def insert_many_skip_large(col: Collection, documents: list[dict]):
    error_docs = []
    try:
        col.insert_many(documents, ordered=False)
    except Exception as e:
        for doc in documents:
            try:
                col.insert_one(doc)
            except pymongo.errors.DuplicateKeyError as e:
                pass
            except Exception as e:
                error_docs.append(doc)
    return error_docs
