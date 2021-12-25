import pathlib
import setuptools

# The directory containing this file
HERE = pathlib.Path(__file__).parent

# The text of the README file
README = (HERE / "README.md").read_text()

# This call to setup() does all the work
setuptools.setup(
    name="Webcam Mods",
    version="0.1.0",
    description=" Face tracking, bg removal, crop, zoom, record & replay, and more webcam mods",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/hamidzr/webcam-mods",
    author='Hamid Zare',
    author_email='contact@hamidza.re',
    keywords='v4l2 webcam virtual-camera virtual-background blur-background',
    license='GPLv2',
    classifiers=[
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python",
        "Topic :: Multimedia :: Video",
        "Topic :: Multimedia :: Video :: Capture",
    ],
    python_requires=">=3.8",
    package_dir={"": "src"},
    project_urls={
        "Homepage": "https://github.com/hamidzr/webcam-mods",
        "Bug Tracker": "https://github.com/hamidzr/webcam-mods/issues",
    },
    packages=setuptools.find_packages(where="src"),
    include_package_data=True,
    install_requires=[
                      ],
    entry_points={
        "console_scripts": [
            "webcam_mods = webcam_mods.entry.__main__:main",
        ]
    },
)

