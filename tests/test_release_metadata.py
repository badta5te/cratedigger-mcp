"""The release metadata agrees: PyPI package, MCP Registry entry and README."""

import json
import re
import tomllib
from pathlib import Path
from typing import Any, get_args

from runout_mcp.discogs import Currency

ROOT = Path(__file__).parent.parent
REGISTRY_DESCRIPTION_LIMIT = 100
# Verbatim from the Discogs API Terms of Use, typographic quotes included.
DISCOGS_DISCLAIMER = (
    "This application uses Discogs’ API but is not affiliated with, sponsored or endorsed by "  # noqa: RUF001
    "Discogs. ‘Discogs’ is a trademark of Zink Media, LLC."  # noqa: RUF001
)


def project() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as file:
        table: dict[str, Any] = tomllib.load(file)["project"]
    return table


def registry_entry() -> dict[str, Any]:
    entry: dict[str, Any] = json.loads((ROOT / "server.json").read_text())
    return entry


def readme() -> str:
    return (ROOT / "README.md").read_text()


def test_registry_entry_names_the_server_as_the_readme_marker_does() -> None:
    marker = re.search(r"<!-- mcp-name: (\S+) -->", readme())

    assert marker is not None
    assert registry_entry()["name"] == marker.group(1) == "io.github.badta5te/runout-mcp"


def test_registry_entry_points_to_the_pypi_package_run_with_uvx() -> None:
    entry = registry_entry()
    version = project()["version"]

    assert entry["version"] == version
    assert [
        (package["registryType"], package["identifier"], package["version"], package["runtimeHint"])
        for package in entry["packages"]
    ] == [("pypi", project()["name"], version, "uvx")]


def test_registry_description_fits_the_registry_limit() -> None:
    assert 0 < len(registry_entry()["description"]) < REGISTRY_DESCRIPTION_LIMIT


def test_registry_entry_asks_for_the_token_as_a_secret() -> None:
    variables = {
        variable["name"]: variable
        for package in registry_entry()["packages"]
        for variable in package["environmentVariables"]
    }

    assert variables["DISCOGS_TOKEN"]["isRequired"] is True
    assert variables["DISCOGS_TOKEN"]["isSecret"] is True
    assert variables["DISCOGS_CURRENCY"].get("isRequired", False) is False
    assert variables["DISCOGS_CURRENCY"]["choices"] == list(get_args(Currency))


def test_readme_installs_from_pypi_and_carries_the_discogs_notices() -> None:
    text = " ".join(readme().split())

    for term in (
        "uvx runout-mcp",
        DISCOGS_DISCLAIMER,
        "Data provided by Discogs",
        "MIT License",
    ):
        assert term in text
