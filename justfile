# just manual: https://github.com/casey/just#readme

_default:
    just --list

# Install cargo plugins used by this project
bootstrap:
    poetry install --no-root --with dev

# Build the project as a package (poetry build)
build *args:
    poetry build

lockfile:
    poetry lockfile --no-update

update *args:
    poetry update {{args}}

format:
    poetry run ruff format simple_salesforce tests

# Run code quality checks
check:
    #!/bin/bash -eux
    poetry run ruff check simple_salesforce tests

# Run all tests locally
test *args:
    #!/bin/bash -eux
    poetry run pytest {{args}}

# Run all tests locally
ci-test coverage_dir='./coverage':
    #!/bin/bash -eux
    poetry run pytest --cov-report xml --junitxml={{coverage_dir}}/unittest.junit.xml
