from setuptools import setup, find_packages

setup(
    name="euro-top-stats",
    version="0.1.0",
    description="CLI stats football européen — top 5 ligues + CL/EL/ECL",
    author="Mathieu Chevalier",
    packages=find_packages(),
    install_requires=[
        "sqlalchemy>=2.0",
        "typer>=0.15",
        "rich>=13",
        "httpx>=0.28",
        "requests>=2.32",
        "beautifulsoup4>=4.12",
        "lxml>=5.3",
        "python-dotenv>=1.0",
    ],
    entry_points={
        "console_scripts": [
            "euro-top=cli.main:app",
        ],
    },
    python_requires=">=3.10",
)
