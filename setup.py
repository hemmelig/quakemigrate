# -*- coding: utf-8 -*-
"""
A Python package for automatic earthquake detection and location using waveform
migration and stacking.

QuakeMigrate is a Python package for automatic earthquake detection and
location using waveform migration and stacking. It can be used to produce
catalogues of earthquakes, including hypocentres, origin times, phase arrival
picks, and local magnitude estimates, as well as rigorous estimates of the
associated uncertainties.

The package has been built with a modular architecture, providing the potential
for extension and adaptation at numerous entry points.

:copyright:
    2020-2022, QuakeMigrate developers.
:license:
    GNU General Public License, Version 3
    (https://www.gnu.org/licenses/gpl-3.0.html)

"""

import os
import pathlib
import platform
import shutil
import sys

from distutils.ccompiler import get_default_compiler
from setuptools import Extension, find_packages, setup


# The minimum python version which can be used to run QuakeMigrate
MIN_PYTHON_VERSION = (3, 7)

# Fail fast if the user is on an unsupported version of Python.
if sys.version_info < MIN_PYTHON_VERSION:
    msg = (f"QuakeMigrate requires python version >= {MIN_PYTHON_VERSION}"
           f" you are using python version {sys.version_info}")
    print(msg, file=sys.stderr)
    sys.exit(1)

# Check if we are on RTD and don't build extensions if we are.
READ_THE_DOCS = os.environ.get("READTHEDOCS", None) == "True"
if READ_THE_DOCS:
    try:
        environ = os.environb
    except AttributeError:
        environ = os.environ

    environ[b"CC"] = b"x86_64-linux-gnu-gcc"
    environ[b"LD"] = b"x86_64-linux-gnu-ld"
    environ[b"AR"] = b"x86_64-linux-gnu-ar"

# Directory of the current file
SETUP_DIRECTORY = pathlib.Path.cwd()
DOCSTRING = __doc__.split("\n")

# Check for MSVC (Windows)
if platform.system() == "Windows" and (
        "msvc" in sys.argv or
        "-c" not in sys.argv and
        get_default_compiler() == "msvc"):
    IS_MSVC = True
else:
    IS_MSVC = False

INSTALL_REQUIRES = [
    "matplotlib",
    "numpy",
    "obspy",
    "pandas",
    "pyproj",
    "scipy"
]

if READ_THE_DOCS:
    EXTRAS_REQUIRES = {
        "docs": [
            "Sphinx >= 1.8.1",
            "docutils"
        ]
    }
else:
    EXTRAS_REQUIRES = {
        "fmm": [
            "scikit-fmm==2022.08.15"
        ]
    }

KEYWORDS = [
    "seismic event detection", "seismic event location", "waveform migration",
    "array", "seismic", "seismology", "earthquake", "seismic waves",
    "waveform", "processing"
]

# Monkey patch for MS Visual Studio
if IS_MSVC:
    # Remove 'init' entry in exported symbols
    def _get_export_symbols(self, ext):
        return ext.export_symbols
    from setuptools.command.build_ext import build_ext
    build_ext.get_export_symbols = _get_export_symbols


def export_symbols(path):
    """
    Required for Windows systems - functions defined in qmlib.def.
    """
    with (SETUP_DIRECTORY / path).open("r") as f:
        lines = f.readlines()[2:]
    return [s.strip() for s in lines if s.strip() != ""]


def get_extensions():
    """
    Config function used to compile C code into a Python extension.
    """
    import numpy
    extensions = []

    if READ_THE_DOCS:
        return []

    extension_args = {
        "include_dirs": [
            str(pathlib.Path.cwd() / "quakemigrate" / "core" / "src"),
            str(pathlib.Path(sys.prefix) / "include"),
            numpy.get_include()
        ],
        "library_dirs": [
            str(pathlib.Path(sys.prefix) / "lib")
        ]
    }
    if platform.system() == "Darwin":
        extension_args["include_dirs"].extend([
            "/usr/local/include",
            "/usr/local/opt/llvm/include"
        ])
        extension_args["library_dirs"].extend([
            "/usr/local/lib",
            "/usr/local/opt/llvm/lib",
            "/usr/local/opt/libomp/lib"
        ])

    sources = [
        str(pathlib.Path("quakemigrate") / "core/src/quakemigrate.c")
    ]

    extra_link_args = []
    if IS_MSVC:
        extra_compile_args = ["/openmp", "/TP", "/O2"]
        extension_args["export_symbols"] = export_symbols(
            "quakemigrate/core/src/qmlib.def"
        )
        extension_args["library_dirs"].extend([
            str(pathlib.Path.cwd() / "quakemigrate" / "core"),
            str(pathlib.Path(sys.prefix) / "bin")
        ])
    else:
        extra_compile_args = []
        extra_link_args.extend(["-lm"])
        if platform.system() == "Darwin":
            extra_link_args.extend(["-lomp"])
            extra_compile_args.extend(["-Xpreprocessor"])
        else:
            extra_link_args.extend(["-lgomp"])
        extra_compile_args.extend(["-fopenmp", "-fPIC", "-Ofast"])

    extension_args["extra_link_args"] = extra_link_args
    extension_args["extra_compile_args"] = extra_compile_args

    extensions.extend([
        Extension(
            "quakemigrate.core.src.qmlib",
            sources=sources,
            **extension_args
        )
    ])

    return extensions


def setup_package():
    """Setup package"""

    if READ_THE_DOCS:
        INSTALL_REQUIRES.append("mock")

    package_dir, package_data = {}, {}
    if IS_MSVC:
        package_dir["quakemigrate.core"] = str(
            pathlib.Path("quakemigrate") / "core"
        )
        package_data["quakemigrate.core"] = [
            "quakemigrate/core/src/*.dll"
        ]

    setup_args = {
        "name": "quakemigrate",
        "description": " ".join(DOCSTRING[1:3]),
        "long_description": "\n".join(DOCSTRING[4:]),
        "url": "https://github.com/QuakeMigrate/QuakeMigrate",
        "author": "The QuakeMigrate Development Team",
        "author_email": """
            quakemigrate.developers@gmail.com,
            tom.winder@esc.cam.ac.uk,
            conor.bacon@esc.cam.ac.uk
        """,
        "license": "GNU General Public License, Version 3 (GPLv3)",
        "classifiers": [
            "Development Status :: 5 - Production/Stable",
            "Intended Audience :: Science/Research",
            "Topic :: Scientific/Engineering",
            "Natural Language :: English",
            "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
            "Operating System :: OS Independent",
            "Programming Language :: Python",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
        ],
        "keywords": KEYWORDS,
        "install_requires": INSTALL_REQUIRES,
        "extras_require": EXTRAS_REQUIRES,
        "zip_safe": False,
        "packages": find_packages(),
        "ext_modules": get_extensions(),
        "package_data": package_data,
        "package_dir": package_dir
    }

    shutil.rmtree(str(SETUP_DIRECTORY / "build"), ignore_errors=True)

    setup(**setup_args)


if __name__ == "__main__":
    # clean --all does not remove extensions automatically
    if "clean" in sys.argv and "--all" in sys.argv:
        # Delete complete build directory
        path = SETUP_DIRECTORY / "build"
        shutil.rmtree(str(path), ignore_errors=True)

        # Delete all shared libs from clib directory
        path = SETUP_DIRECTORY / "quakemigrate" / "core" / "src"
        for filename in path.glob("*.pyd"):
            filename.unlink(missing_ok=True)
        for filename in path.glob("*.so"):
            filename.unlink(missing_ok=True)
        for filename in path.glob("*.dll"):
            filename.unlink(missing_ok=True)
    else:
        setup_package()
