from setuptools import setup, find_packages

setup(
    name="modrinth-bot",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "aiogram==3.0.0b7",
        "python-dotenv==1.0.0",
        "rapidfuzz==3.0.0",
        "redis==4.5.4",
    ],
)