import os
import zipfile
import shutil
import requests
from time import sleep

ZIP_DATASET = (
    "https://data.uni-hannover.de/dataset/25a28ec2-f9a8-412f-a6e8-6808b66ef957/resource/3dcefa6d-d57e-4de7-bc11-56227ae4e119/download/raw.zip"
)

TTL_FILES = [
    "https://zenodo.org/records/12798851/files/EnDe50.ttl?download=1",
    "https://zenodo.org/records/12798851/files/EnDe100.ttl?download=1",
    "https://zenodo.org/records/12798851/files/EnDe1000.ttl?download=1"
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "../../data")
TEMP_DIR = os.path.join(BASE_DIR, "../../temp_download")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


def download_file_resumable(url, target_path, retries=3, timeout=60):
    temp_path = target_path + ".part"
    offset_path = target_path + ".offset"

    for attempt in range(retries):
        # Always re-read offset before each attempt
        if os.path.exists(offset_path):
            with open(offset_path, "r") as f:
                try:
                    existing_bytes = int(f.read().strip())
                except:
                    existing_bytes = 0
        elif os.path.exists(temp_path):
            existing_bytes = os.path.getsize(temp_path)
        else:
            existing_bytes = 0

        try:
            session = requests.Session()
            head = session.head(url, allow_redirects=True, timeout=timeout)
            final_url = head.url

            headers = {"Range": f"bytes={existing_bytes}-"} if existing_bytes else {}
            print(f"Starting download from offset {existing_bytes} bytes")

            with session.get(final_url, stream=True, headers=headers, timeout=timeout) as r:
                if existing_bytes > 0 and r.status_code != 206:
                    raise RuntimeError(f"Resume failed: expected HTTP 206, got {r.status_code}")

                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0)) + existing_bytes
                mode = "ab" if existing_bytes else "wb"

                with open(temp_path, mode) as f:
                    downloaded = existing_bytes
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            f.flush()
                            os.fsync(f.fileno())
                            downloaded += len(chunk)

                            with open(offset_path, "w") as ofs:
                                ofs.write(str(downloaded))

                            percent = downloaded * 100 / total
                            print(f"\rDownloading... {percent:.2f}% ({downloaded / (1024**2):.1f} MB)", end="")

            os.rename(temp_path, target_path)
            if os.path.exists(offset_path):
                os.remove(offset_path)
            print(f"\nSaved to: {target_path}")
            return
        except Exception as e:
            print(f"\nDownload failed (attempt {attempt + 1}): {e}")
            sleep(2 * (attempt + 1))

    raise RuntimeError(f"Failed to download {url} after {retries} attempts")



# --- ZIP download ---
zip_filename = os.path.basename(ZIP_DATASET)
zip_path = os.path.join(TEMP_DIR, zip_filename)
extract_path = os.path.join(TEMP_DIR, "unzipped")

if os.path.exists(os.path.join(DATA_DIR, "lubm-lkg-1.ttl")):  # or another known file from the zip
    print("ZIP dataset already extracted, skipping download.")
else:
    download_file_resumable(ZIP_DATASET, zip_path)

    print(f"Extracting: {zip_filename}")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_path)

    print("Moving ZIP contents to /data...")
    for item in os.listdir(extract_path):
        src = os.path.join(extract_path, item)
        dst = os.path.join(DATA_DIR, item)
        if os.path.exists(dst):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            else:
                os.remove(dst)
        shutil.move(src, dst)

# --- TTL files ---
def download_ttl(url):
    filename = url.split("files/")[-1].split("?")[0]
    dst = os.path.join(DATA_DIR, filename)
    if os.path.exists(dst):
        print(f"Skipping TTL (already exists): {filename}")
        return
    print(f"Downloading TTL: {filename}")
    download_file_resumable(url, dst)

for ttl_url in TTL_FILES:
    download_ttl(ttl_url)

# --- Cleanup ---
if os.path.exists(TEMP_DIR):
    shutil.rmtree(TEMP_DIR)

print("All datasets downloaded and placed in /data.")
