# WINGS

[![Build](https://github.com/charliekilpatrick/WINGS/actions/workflows/build_and_test.yaml/badge.svg?branch=main)](https://github.com/charliekilpatrick/WINGS/actions/workflows/build_and_test.yaml?query=branch%3Amain)
[![Docs](https://github.com/charliekilpatrick/WINGS/actions/workflows/docs.yaml/badge.svg?branch=main)](https://github.com/charliekilpatrick/WINGS/actions/workflows/docs.yaml?query=branch%3Amain)

Pipeline toolkit and campaign site for nearby-galaxy HST imaging. The installable package is `wpipe`; the NGP demo site lives under `wings/src/pipelinesite`.

## Requirements

- Python 3.12+
- A MySQL server if you will run `wpipe` pipelines (local install or the Docker helper below)
- `pip` can install the rest from PyPI

Core dependencies: `numpy`, `pandas`, `tenacity`, `tables`, `sqlalchemy`, `mysql-connector-python`, `mysqlclient`, `astropy`, `jinja2`.

## Install `wpipe`

```bash
git clone https://github.com/charliekilpatrick/WINGS.git
cd WINGS
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

Optional extras:

```bash
python -m pip install -e ".[test]"    # pytest
python -m pip install -e ".[demo]"    # NGP campaign site
python -m pip install -e ".[docs]"    # Sphinx
```

A conda environment is also described in `environment.yml` (`python=3.12`).

This project uses `pyproject.toml`. `pip install .` and `pip install -e .` both work; there is no `setup.py`.

## Tests

From the repository root, with the demo extra installed:

```bash
export PIPELINESITE_DEMO=1
export PYTHONPATH="$PWD:$PWD/wings/src:$PWD/wings/src/pipelinesite"
python wings/src/pipelinesite/manage.py test tests
```

Tests are organized under `tests/` by type (`catalog`, `campaign`, `photometry`, `mosaic`, `inventory`, `overlay`). Interactive `wpipe` scripts live in `tests/wpipe/manual/` and are not collected by pytest.

## MySQL for `wpipe`

`wpipe` needs a running MySQL server and an engine URL before you import it.

Local server:

```bash
export WPIPE_ENGINEURL="mysql+pymysql://<username>:<password>@localhost/server"
```

Docker helper (MySQL 5.7.29 on port 8000, root password `password`, data in `"${HOME}/docker/storage/wings_mysql/"`):

```bash
# requires Docker and a MySQL client
wings/scripts/run_mysql_container.sh
mysql --host localhost -P 8000 --protocol=tcp -u root -p
export WPIPE_ENGINEURL="mysql+pymysql://root:password@localhost:8000/server"
pip install PyMySQL   # used by this docker URL; not installed by default
```

Stop the container with `docker container stop wingsmysql`.

## Useful environment variables

- `WPIPE_NO_PBS_SCHEDULER=1` — skip PBS job submission
- `WPIPE_USER` — database user name (default `default`)

## Run a pipeline

```bash
mkdir mypipe && cd mypipe
wingspipe init
wingspipe init \
  -w <PATH_TO_WINGS>/wings/src/test/data/tasks/ \
  -i <PATH_TO_WINGS>/wings/src/test/data/inputs/ \
  -c <PATH_TO_WINGS>/wings/src/test/data/default.conf
wingspipe run
wingspipe delete
```

## NGP campaign demo

```bash
cd wings/src/pipelinesite
./run_demo.sh
```

Then open http://127.0.0.1:8000/. The demo uses SQLite (`PIPELINESITE_DEMO=1`) and does not need the live wpipe MySQL database.

Sync newly archived GO 18338 targets into the campaign table:

```bash
cd wings/src/pipelinesite
PIPELINESITE_DEMO=1 .venv/bin/python manage.py sync_program_targets
```

## Documentation

Pushes to `main` build the Sphinx site and publish it to the `gh-pages` branch. After you set **Settings → Pages → Deploy from a branch** to `gh-pages` `/ (root)`, the site is at https://charliekilpatrick.github.io/WINGS/.

```bash
python -m pip install -e ".[docs]"
make -C docs html
```

## Authors

See the [contributors](https://github.com/charliekilpatrick/WINGS/graphs/contributors).
