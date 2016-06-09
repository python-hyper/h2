#!/bin/bash

set -e
set -x

if [[ $TRAVIS_PYTHON_VERSION == pypy ]]; then
    py.test test/
else
    coverage run -m py.test test/
    coverage combine
    coverage report
fi