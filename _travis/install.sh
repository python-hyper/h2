#!/usr/bin/env bash

set -e
set -x

pip install -U pip setuptools
pip install -U tox

if [ $TOXENV = "h2spec" ]; then
    # We want to get the latest release of h2spec. We do that by asking the
    # Github API for it, and then parsing the JSON for the appropriate kind of
    # binary. Happily, the binary is always called "h2spec" so we don't need
    # even more shenanigans to get this to work.
    TARBALL=$(curl -s https://api.github.com/repos/summerwind/h2spec/releases/latest | jq --raw-output '.assets[] | .browser_download_url | select(endswith("linux_amd64.tar.gz"))')
    curl -LO "$TARBALL"
    tar xvf $TARBALL
    mv h2spec /usr/local/bin
fi
