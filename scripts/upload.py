import requests, os, argparse, time
from dotenv import load_dotenv

load_dotenv()

MAX_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = 15

def uploadFile(path, bucket_url, headers):
	filename = path.split("/")[-1]
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

def main():
	parser = argparse.ArgumentParser(description="Upload files to Zenodo.")
	parser.add_argument("file", help="Upload only this file (e.g., data/customers.parquet)")
	args = parser.parse_args()

	BASE_URL = 'https://zenodo.org/api'
	ACCESS_TOKEN = os.environ['ZENODO_ACCESS_TOKEN']
	HEADERS = {'Authorization': f'Bearer {ACCESS_TOKEN}'}

	r = requests.get(f'{BASE_URL}/deposit/depositions', headers=HEADERS)
	if r.status_code != 200:
		print('Error getting depositions')
		print(r.json())
		exit(-1)

	depositions = r.json()
	bucket_url = ''
	for d in depositions:
		id = d['id']
		if str(id) == os.environ['ZENODO_DEPOSITION_ID']:
			r = requests.get(f'{BASE_URL}/deposit/depositions/{id}', headers=HEADERS)
			bucket_url = r.json()["links"]["bucket"]
			break

	if bucket_url == '':
		print('Error getting bucket url')
		print(r.json())
		exit(-1)

	print(f'Uploading {args.file}')
	print(uploadFile(args.file, bucket_url, HEADERS).json())

if __name__ == "__main__":
    main()