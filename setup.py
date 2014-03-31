from setuptools import setup, find_packages


setup(
    name="Vase",
    version="0.1.4",
    author="Vladimir Kryachko",
    author_email="v.kryachko@gmail.com",
    description = "Async Web framework based on Tulip/asyncio",
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.4",
    ],
    packages=find_packages(exclude=["*.tests", "*.tests.*", "tests.*", "tests"]),
)
