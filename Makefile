.PHONY: publish

publish:
	rm -rf dist/
	pip3 install -U twine wheel pip setuptools
	python3 setup.py sdist bdist_wheel
	twine upload -s dist/*
