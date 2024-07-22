import json
import pprint

import pytest
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.testclient import TestClient
from flask_sqlalchemy import SQLAlchemy

from quantdb.api import make_app
from quantdb.utils import log

db = SQLAlchemy()
quantdb_flask_app = make_app(db=db, dev=True)

# TODO: middleware to mount the flask app for now
app = FastAPI()
app.mount("/quantdb", WSGIMiddleware(quantdb_flask_app))
client = TestClient(app)


def test():
    db = SQLAlchemy()
    app = make_app(db=db, dev=True)
    client = app.test_client()
    runner = app.test_cli_runner()

    dataset_uuid = "aa43eda8-b29a-4c25-9840-ecbd57598afc"
    some_object = "414886a9-9ec7-447e-b4d8-3ae42fda93b7"  # XXX FAKE
    actual_package_uuid = "15bcbcd5-b054-40ef-9b5c-6a260d441621"
    base = "http://localhost:8000/quantdb/api/1/"
    urls = (
        f"{base}values/inst",
        f"{base}values/inst?dataset={dataset_uuid}",
        f"{base}values/inst?dataset={dataset_uuid}&union-cat-quant=true",
        f"{base}values/inst?dataset={dataset_uuid}&aspect=distance&aspect=time",
        f"{base}values/inst?dataset={dataset_uuid}&aspect=distance&value-quant-min=0.5",
        f"{base}values/inst?desc-inst=nerve-volume",
        f"{base}objects?dataset={dataset_uuid}",
        f"{base}objects?dataset={dataset_uuid}&aspect=distance",
        f"{base}objects?dataset={dataset_uuid}&aspect=distance&value-quant-min=0.5",  # expect nothing
        f"{base}objects?dataset={dataset_uuid}&aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        f"{base}objects?dataset={dataset_uuid}&subject=sub-f001",
        f"{base}objects?subject=sub-f001",
        f"{base}objects?subject=sub-f001&union-cat-quant=true",
        f"{base}objects?subject=sub-f001&subject=sub-f002&subject=sub-f003&subject=sub-f004&subject=sub-f005",
        f"{base}objects?subject=sub-f001&subject=sub-f002&subject=sub-f003&subject=sub-f004&subject=sub-f005&union-cat-quant=true",
        f"{base}objects?subject=sub-f001&desc-cat=none&value-quant-min=0.5&union-cat-quant=true",
        f"{base}objects?subject=sub-f001&desc-cat=none&aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        f"{base}objects?subject=sub-f001&aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        f"{base}objects?aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        f"{base}objects?desc-cat=none&aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        f"{base}objects?desc-cat=none&aspect=distance&value-quant-min=0.5",
        f"{base}objects?aspect=distance&value-quant-min=0.5",
        f"{base}objects?aspect=distance&value-quant-min=0.5&source-only=true",
        f"{base}objects?desc-inst=nerve-volume&aspect=distance&value-quant-min=0.5&source-only=true",
        # values-quant
        f"{base}values/quant?dataset={dataset_uuid}&aspect=distance",
        f"{base}values/quant?object={actual_package_uuid}&aspect=distance",
        f"{base}values/quant?aspect=distance",
        f"{base}values/quant?aspect=distance-via-reva-ft-sample-id-normalized-v1",
        f"{base}values/quant?aspect=distance-via-reva-ft-sample-id-normalized-v1&agg-type=instance",
        f"{base}values/quant?aspect=distance-via-reva-ft-sample-id-normalized-v1&value-quant-min=0.4&value-quant-max=0.7",
        # values-cat
        f"{base}values/cat?object={actual_package_uuid}",
        f"{base}values/cat?object={actual_package_uuid}&union-cat-quant=true",  # shouldn't need it in this case
        f"{base}values/cat-quant?object={actual_package_uuid}",
        f"{base}values/cat-quant?object={actual_package_uuid}&union-cat-quant=true",
        # values-cat-quant
        f"{base}values?dataset={dataset_uuid}&aspect=distance&value-quant-min=0.5",
        f"{base}values?dataset={dataset_uuid}&aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        f"{base}values?object={actual_package_uuid}",
        f"{base}values?object={actual_package_uuid}&union-cat-quant=true",
        f"{base}values/inst?object={actual_package_uuid}",
        f"{base}values/inst?object={actual_package_uuid}&union-cat-quant=true",
        # prov
        f"{base}values/inst?prov=true",
        f"{base}values/quant?aspect=distance&prov=true",
        f"{base}values/cat?object={actual_package_uuid}",
        f"{base}values/cat?object={actual_package_uuid}&prov=true",  # FIXME somehow this has a 3x increase in records, and non-distinct
        f"{base}values/cat-quant?object={actual_package_uuid}&union-cat-quant=true",
        f"{base}values/cat-quant?object={actual_package_uuid}&union-cat-quant=true&prov=true",
        f"{base}values/cat-quant",
        f"{base}values/cat-quant?prov=true",
        f"{base}values/cat-quant?union-cat-quant=true",
        f"{base}values/cat-quant?union-cat-quant=true&prov=true",
        # desc
        f"{base}desc/inst",
        f"{base}desc/cat",
        f"{base}desc/quant",
        f"{base}desc/inst?include-unused=true",
        f"{base}desc/cat?include-unused=true",
        f"{base}desc/quant?include-unused=true",
        # descriptor values
        f"{base}terms",
        f"{base}aspects",
        f"{base}units",
        f"{base}terms?include-unused=true",
        f"{base}aspects?include-unused=true",
        f"{base}units?include-unused=true",
        # TODO maybe shapes here as well?
    )
    # log.setLevel(9)
    resps = []
    for url in urls:
        log.debug(url)
        resp = client.get(url)
        resp.ok = resp.status_code < 400
        resp.url = resp.request.url
        resp.content = resp.data
        resps.append(json.loads(resp.data.decode()))

    pprint.pprint(resps, width=120)
    # (i := 6, resps[i], urls[i])
    # q = client.get(f'{base}values/quant?dataset={dataset_uuid}&aspect=distance&return-query=true').data.decode()
    # q = client.get(f'{base}values/cat?object={actual_package_uuid}&prov=true&return-query=true').data.decode()
    # print(q)
    breakpoint()


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/quantdb/api/1/values/inst",
        "http://localhost:8000/quantdb/api/1/values/inst?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc",
        "http://localhost:8000/quantdb/api/1/values/inst?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/values/inst?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc&aspect=distance&aspect=time",
        "http://localhost:8000/quantdb/api/1/values/inst?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc&aspect=distance&value-quant-min=0.5",
        "http://localhost:8000/quantdb/api/1/values/inst?desc-inst=nerve-volume",
        "http://localhost:8000/quantdb/api/1/objects?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc",
        "http://localhost:8000/quantdb/api/1/objects?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc&aspect=distance",
        "http://localhost:8000/quantdb/api/1/objects?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc&aspect=distance&value-quant-min=0.5",
        "http://localhost:8000/quantdb/api/1/objects?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc&aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/objects?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc&subject=sub-f001",
        "http://localhost:8000/quantdb/api/1/objects?subject=sub-f001",
        "http://localhost:8000/quantdb/api/1/objects?subject=sub-f001&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/objects?subject=sub-f001&subject=sub-f002&subject=sub-f003&subject=sub-f004&subject=sub-f005",
        "http://localhost:8000/quantdb/api/1/objects?subject=sub-f001&subject=sub-f002&subject=sub-f003&subject=sub-f004&subject=sub-f005&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/objects?subject=sub-f001&desc-cat=none&value-quant-min=0.5&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/objects?subject=sub-f001&desc-cat=none&aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/objects?subject=sub-f001&aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/objects?aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/objects?desc-cat=none&aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/objects?desc-cat=none&aspect=distance&value-quant-min=0.5",
        "http://localhost:8000/quantdb/api/1/objects?aspect=distance&value-quant-min=0.5",
        "http://localhost:8000/quantdb/api/1/objects?aspect=distance&value-quant-min=0.5&source-only=true",
        "http://localhost:8000/quantdb/api/1/objects?desc-inst=nerve-volume&aspect=distance&value-quant-min=0.5&source-only=true",
        "http://localhost:8000/quantdb/api/1/values/quant?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc&aspect=distance",
        "http://localhost:8000/quantdb/api/1/values/quant?object=15bcbcd5-b054-40ef-9b5c-6a260d441621&aspect=distance",
        "http://localhost:8000/quantdb/api/1/values/quant?aspect=distance",
        "http://localhost:8000/quantdb/api/1/values/quant?aspect=distance-via-reva-ft-sample-id-normalized-v1",
        "http://localhost:8000/quantdb/api/1/values/quant?aspect=distance-via-reva-ft-sample-id-normalized-v1&agg-type=instance",
        "http://localhost:8000/quantdb/api/1/values/quant?aspect=distance-via-reva-ft-sample-id-normalized-v1&value-quant-min=0.4&value-quant-max=0.7",
        "http://localhost:8000/quantdb/api/1/values/cat?object=15bcbcd5-b054-40ef-9b5c-6a260d441621",
        "http://localhost:8000/quantdb/api/1/values/cat?object=15bcbcd5-b054-40ef-9b5c-6a260d441621&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/values/cat-quant?object=15bcbcd5-b054-40ef-9b5c-6a260d441621",
        "http://localhost:8000/quantdb/api/1/values/cat-quant?object=15bcbcd5-b054-40ef-9b5c-6a260d441621&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/values?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc&aspect=distance&value-quant-min=0.5",
        "http://localhost:8000/quantdb/api/1/values?dataset=aa43eda8-b29a-4c25-9840-ecbd57598afc&aspect=distance&value-quant-min=0.5&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/values?object=15bcbcd5-b054-40ef-9b5c-6a260d441621",
        "http://localhost:8000/quantdb/api/1/values?object=15bcbcd5-b054-40ef-9b5c-6a260d441621&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/values/inst?object=15bcbcd5-b054-40ef-9b5c-6a260d441621",
        "http://localhost:8000/quantdb/api/1/values/inst?object=15bcbcd5-b054-40ef-9b5c-6a260d441621&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/values/inst?prov=true",
        "http://localhost:8000/quantdb/api/1/values/quant?aspect=distance&prov=true",
        "http://localhost:8000/quantdb/api/1/values/cat?object=15bcbcd5-b054-40ef-9b5c-6a260d441621",
        "http://localhost:8000/quantdb/api/1/values/cat?object=15bcbcd5-b054-40ef-9b5c-6a260d441621&prov=true",
        "http://localhost:8000/quantdb/api/1/values/cat-quant?object=15bcbcd5-b054-40ef-9b5c-6a260d441621&union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/values/cat-quant?object=15bcbcd5-b054-40ef-9b5c-6a260d441621&union-cat-quant=true&prov=true",
        "http://localhost:8000/quantdb/api/1/values/cat-quant",
        "http://localhost:8000/quantdb/api/1/values/cat-quant?prov=true",
        "http://localhost:8000/quantdb/api/1/values/cat-quant?union-cat-quant=true",
        "http://localhost:8000/quantdb/api/1/values/cat-quant?union-cat-quant=true&prov=true",
        "http://localhost:8000/quantdb/api/1/desc/inst",
        "http://localhost:8000/quantdb/api/1/desc/cat",
        "http://localhost:8000/quantdb/api/1/desc/quant",
        "http://localhost:8000/quantdb/api/1/desc/inst?include-unused=true",
        "http://localhost:8000/quantdb/api/1/desc/cat?include-unused=true",
        "http://localhost:8000/quantdb/api/1/desc/quant?include-unused=true",
        "http://localhost:8000/quantdb/api/1/terms",
        "http://localhost:8000/quantdb/api/1/aspects",
        "http://localhost:8000/quantdb/api/1/units",
        "http://localhost:8000/quantdb/api/1/terms?include-unused=true",
        "http://localhost:8000/quantdb/api/1/aspects?include-unused=true",
        "http://localhost:8000/quantdb/api/1/units?include-unused=true",
    ],
)
def test_urls(url: str) -> None:
    """Test all urls if they return a valid response.

    Parameters
    ----------
    url : str
        complete url to test
    """
    resp = client.get(url)
    assert resp.status_code < 400
    data = resp.json()
    assert isinstance(data, dict)
    # pprint.pprint(data, width=120)
