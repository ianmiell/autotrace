# SEE https://raw.githubusercontent.com/pypa/sampleproject/master/setup.py
from setuptools import setup, find_packages
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

# Arguments marked as "Required" below must be included for upload to PyPI.
# Fields marked as "Optional" may be commented out.

setup(
    name='telemetrise',
 version='0.0.5',
    description='Telemetry on any command',
    author='Ian Miell',
    author_email='ian.miell@gmail.com',
    packages=find_packages(exclude=[]),
    install_requires=['curtsies','pexpect'],
    entry_points={
        'console_scripts': [
            'telemetrise=telemetrise.telemetrise:main',
        ],
    },
)
