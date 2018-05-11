# SEE https://raw.githubusercontent.com/pypa/sampleproject/master/setup.py
from setuptools import setup, find_packages
from codecs import open
from os import path
here = path.abspath(path.dirname(__file__))
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()
setup(
    name='autotrace',
 version='0.0.10',
    description='Telemetry on any command',
    author='Ian Miell',
    author_email='ian.miell@gmail.com',
    packages=find_packages(exclude=[]),
    install_requires=['curtsies','pexpect'],
    entry_points={
        'console_scripts': [
            'autotrace=autotrace.autotrace:main',
        ],
    },
)
