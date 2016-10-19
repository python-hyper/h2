#!/bin/bash

set -e
set -x

if [[ $TRAVIS_PYTHON_VERSION == pypy ]]; then
    py.test --hypothesis-profile travis test/
else
    coverage run -m py.test --hypothesis-profile travis test/
    coverage report
fi