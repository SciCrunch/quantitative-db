from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any, List, Tuple

import boto3
import requests
from botocore.client import BaseClient
from pydantic_settings import BaseSettings


class PennsieveModel(BaseSettings):
    PENNSIEVE_API_TOKEN: str
    PENNSIEVE_API_SECRET: str
    auth_url: str = 'https://api.pennsieve.io/authentication/cognito-config'
    private_dataset_url: str = 'https://api.pennsieve.io/datasets/'
    public_dataset_url: str = 'https://api.pennsieve.io/discover/datasets'

    class Config:  # type: ignore
        env_file = Path.home() / '.scicrunch/credentials/pennsieve'
        fields = {
            'PENNSIEVE_API_TOKEN': {'env': 'PENNSIEVE_API_TOKEN'},
            'PENNSIEVE_API_SECRET': {'env': 'PENNSIEVE_API_SECRET'},
        }


class Settings(BaseSettings):
    pennsieve: PennsieveModel = PennsieveModel()


class PennsieveClient:
    def __init__(self):
        settings = Settings().pennsieve
        self.public_dataset_url = settings.public_dataset_url
        self.private_dataset_url = settings.private_dataset_url
        self.auth_url = settings.auth_url
        self.api_key = self.__aws_bot_login(
            token=settings.PENNSIEVE_API_TOKEN,
            secret=settings.PENNSIEVE_API_SECRET,
        )
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'accept': '*/*',
        }
        self.session = requests.Session()

    def __reauth(self) -> None:
        settings = Settings().pennsieve
        self.api_key = self.__aws_bot_login(
            token=settings.PENNSIEVE_API_TOKEN,
            secret=settings.PENNSIEVE_API_SECRET,
        )
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'accept': '*/*',
        }

    def __aws_bot_login(self, token: str, secret: str) -> str:
        """Awful AWS bot login for real API key using token + secrets"""
        r = requests.get(self.auth_url)
        r.raise_for_status()
        cognito_app_client_id = r.json()['tokenPool']['appClientId']
        cognito_region = r.json()['region']
        cognito_idp_client: BaseClient = boto3.client(  # type: ignore
            'cognito-idp',
            region_name=cognito_region,
            aws_access_key_id='',
            aws_secret_access_key='',
        )
        login_response = cognito_idp_client.initiate_auth(  # type: ignore
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={'USERNAME': token, 'PASSWORD': secret},
            ClientId=cognito_app_client_id,
        )
        api_key: str = login_response['AuthenticationResult']['AccessToken']
        return api_key

    def __get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> requests.Response:
        """
        Get request to endpoint with params

        Parameters
        ----------
        endpoint : URL
            API endpoint to hit
        params : dict, optional
            API options, by default None

        Returns
        -------
        dict
            API json response
        """
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response

    def _post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        """
        Post request to endpoint with data or json payload

        Parameters
        ----------
        endpoint : URL
            API endpoint to hit
        data : dict, optional
            API contents, by default None
        json : dict, optional
            API contents, by default None

        Returns
        -------
        dict
            API json response
        """
        response = self.session.post(url, data=data, json=payload, headers=self.headers)
        # Pennsieve API is unstable, only fail on 500s
        if response.status_code >= 400:
            print(response.text)
            self.__reauth()
            response = self.session.post(url, data=data, json=payload, headers=self.headers)
        response.raise_for_status()
        return response

    @staticmethod
    def create_path(path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            pass

    def get_user(self):
        return self.__get('https://api.pennsieve.io/user/').json()

    @cache
    def get_dataset(self, id_or_name: str) -> dict[str, Any]:
        return self.__get(f'https://api.pennsieve.io/datasets/{id_or_name}').json()

    def get_dataset_packages(self, id_or_name: str) -> dict[str, Any]:
        return self.__get(f'https://api.pennsieve.io/datasets/{id_or_name}/packages').json()['packages']

    @cache
    def get_dataset_manifest(self, id_or_name: str) -> dict[str, Any]:
        url = 'https://api.pennsieve.io/packages/download-manifest'
        dataset = self.get_dataset(id_or_name)
        payload = {'nodeIds': [child['content']['nodeId'] for child in dataset['children']]}
        dataset['files'] = self._post(url, payload=payload).json()
        return dataset

    @cache
    def get_child_manifest(self, node_id: str) -> dict[str, Any]:
        url = 'https://api.pennsieve.io/packages/download-manifest'
        payload = {'nodeIds': [node_id]}
        resp = self._post(url, payload=payload)
        return resp.json()

    def export_dataset(self, id_or_name: str, output_dir: Path | str, verbose: bool = True) -> None:
        """Export a dataset to a directory

        Parameters
        ----------
        id_or_name : str
            Dataset ID or name
        output_dir : Path | str
            Output directory
        verbose : bool, optional
            Prints filename being downloaded, by default True
        """
        url = 'https://api.pennsieve.io/packages/download-manifest'
        output_dir = Path(output_dir) / id_or_name
        # Pull dataset for root children IDs
        dataset = self.get_dataset(id_or_name)
        for child in dataset['children']:
            payload = {'nodeIds': [child['content']['nodeId']]}
            # Pull tree for 1 child at a time since prebuilt s3 links only last a couple hours
            # If all children are pulled at once, the links will expire before all files are downloaded if over 200GBs
            manifest = self._post(url, payload=payload).json()
            for filemeta in manifest['data']:
                parents_path = output_dir / '/'.join(filemeta['path'])
                # Create nested parent directories if they don"t exist
                self.create_path(parents_path)
                file_path = parents_path / filemeta['fileName']
                if verbose:
                    print(f'downloading path: {file_path}')
                url = filemeta['url']
                # If file already exists, skip if it is stopped in the middle of downloading
                # TODO: query file for checksum; very slow but will garuntee no partial downloads
                if file_path.exists():
                    continue
                # Stream download to file
                with requests.get(url, stream=True) as r:
                    r.raise_for_status()
                    with open(file_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)

    def _private_datasets(self):
        """Get Private dataset for it"s N:# ID

        Notes
        -----
        There is no known limiter at the moment. Expect all results and be conservative.
        """
        return self.__get(self.private_dataset_url).json()

    def _public_datasets(self, limit: int = 1, offset: int = 0, asc: bool = False) -> list[dict[str, Any]]:
        """Everything about the dataset except the N:# id itself"""
        params = {
            'limit': limit,
            'offset': offset,
            'orderBy': 'date',
            'orderDirection': 'asc' if asc else 'desc',
        }
        return self.__get(self.public_dataset_url, params=params).json()['datasets']

    def get_datasets(self) -> List[dict[str, Any]]:
        """
        Get all complete datasets
        """
        # Private API endpoint Needs to be normalized via content key
        intId_id = {d['content']['intId']: d['content']['id'] for d in self._private_datasets()}
        datasets = self._public_datasets(limit=100000)
        for dataset in datasets:
            dataset['dataset_id'] = intId_id.get(dataset['sourceDatasetId'])
        return datasets

    def get_partial_hash(self) -> Tuple[int, int, int | None]:
        """Get latest dataset id & version to see if anything new from pennsieve is worth pulling"""
        latest_dataset = self._public_datasets()[0]
        partial_hash = (
            latest_dataset['sourceDatasetId'],
            latest_dataset['version'],
            latest_dataset['revision'],
        )
        return partial_hash
