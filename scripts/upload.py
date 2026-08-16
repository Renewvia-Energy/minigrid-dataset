import requests, os, argparse, time
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
MAX_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 15

def uploadFile(path, bucket_url, headers):
	filename = os.path.basename(path)
	url = "%s/%s" % (bucket_url, filename)
	for attempt in range(1, MAX_ATTEMPTS + 1):
		try:
			with open(path, 'rb') as fp:
				r = requests.put(url, data=fp, headers=headers)
			r.raise_for_status()
			return r
		except requests.exceptions.RequestException as e:
			if attempt == MAX_ATTEMPTS:
				raise
			wait = RETRY_BACKOFF_SECONDS * attempt
			print(f'Upload attempt {attempt}/{MAX_ATTEMPTS} failed ({e}); retrying in {wait}s')
			time.sleep(wait)

def getBucketUrl(base_url, headers):
	r = requests.get(f'{base_url}/deposit/depositions', headers=headers)
	if r.status_code != 200:
		print('Error getting depositions')
		print(r.json())
		exit(-1)

	deposition_id = os.environ['ZENODO_DEPOSITION_ID']
	for d in r.json():
		if str(d['id']) == deposition_id:
			r2 = requests.get(f'{base_url}/deposit/depositions/{d["id"]}', headers=headers)
			return r2.json()["links"]["bucket"]

	print('Error: deposition not found')
	exit(-1)

def getUploadedFilenames(base_url, deposition_id, headers):
	r = requests.get(f'{base_url}/deposit/depositions/{deposition_id}/files', headers=headers)
	r.raise_for_status()
	return {f['filename'] for f in r.json()}

def main():
	parser = argparse.ArgumentParser(description="Upload files to Zenodo.")
	parser.add_argument("file", nargs='?', help="Upload only this file (e.g., data/customers.parquet). If omitted, uploads all files in the data directory not already in the bucket.")
	args = parser.parse_args()

	BASE_URL = 'https://zenodo.org/api'
	ACCESS_TOKEN = os.environ['ZENODO_ACCESS_TOKEN']
	HEADERS = {'Authorization': f'Bearer {ACCESS_TOKEN}'}

	bucket_url = getBucketUrl(BASE_URL, HEADERS)

	if args.file:
		print(f'Uploading {args.file}')
		print(uploadFile(args.file, bucket_url, HEADERS).json())
	else:
		uploaded = getUploadedFilenames(BASE_URL, os.environ['ZENODO_DEPOSITION_ID'], HEADERS)
		all_files = sorted(f for f in os.listdir(DATA_DIR) if os.path.isfile(os.path.join(DATA_DIR, f)))
		to_upload = [f for f in all_files if f not in uploaded]

		print(f'{len(uploaded)} file(s) already in bucket, {len(to_upload)} to upload.')
		failed = []
		for filename in to_upload:
			path = os.path.join(DATA_DIR, filename)
			print(f'Uploading {filename} ...')
			try:
				uploadFile(path, bucket_url, HEADERS)
				print(f'  done.')
			except Exception as e:
				print(f'  ERROR: {e}')
				failed.append(filename)
		if failed:
			print(f'\n{len(failed)} file(s) failed: {", ".join(failed)}')
		else:
			print('All files uploaded successfully.')

if __name__ == "__main__":
    main()
