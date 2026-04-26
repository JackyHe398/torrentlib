import warnings
from setuptools import setup, find_packages

warnings.warn(
    "bt_tracker_utils has been renamed to torrentlib. "
    "Please use 'pip install torrentlib' and update your imports. "
    "This package will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2
)

setup(
    name="torrentlib",
    version="1.0.1",
    author="JackyHe398",
    author_email="hekinghung@gmail.com",
    description="BitTorrent utilities for querying trackers and peers",
    install_requires=[
        "requests>=2.32.4",
        "bencodepy>=0.9.5",
        "humanize>=4.9.0",
        "torrent-parser>=0.4.0"
    ],
    packages=find_packages(),
    python_requires=">=3.10",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown"
)

# python setup.py sdist bdist_wheel
# twine upload dist/*