"""Add a third global weather, `DESERT`, driving a new `SAND` model condition.

Stock weather is `NORMAL`/`SNOWY`, and `SNOWY` sets the `SNOW` model condition when a drawable is
bound to its object. The patch adds `DESERT` as weather index 2 and `SAND` as a model condition, and
pairs them at the two places the engine relates weather to model conditions.
`DesertWeatherWorldbuilderPatch` teaches the editor the same tokens.

The table, the hooks and the "any weather" value are shared with every other map-weather patch
(`ash-weather` takes slot 3) through `../utils/map_weather.py`, so they compose in either order.

Derivation: `../docs/desert-weather.md`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sage_ini.engine import Engine, EnumDelta

from ...patcher import Patch
from ..utils import map_weather, model_conditions

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_CONDITION",
    "DEFAULT_WEATHER",
    "NEW_WEATHER_INDEX",
    "SNOW_BIT",
    "DesertWeatherPatch",
    "DesertWeatherWorldbuilderPatch",
    "build_bind_code",
    "build_upgrade_code",
]

#: The slot `DESERT` owns. It is also the stock member count, so on its own the patch appends.
NEW_WEATHER_INDEX = len(map_weather.STOCK_WEATHER_NAMES)

SNOW_BIT = map_weather.SNOW_BIT

_SECTION_NAME = ".desertw"

#: The PE section name field is 8 bytes and truncates silently.
WORLDBUILDER_SECTION_NAME = ".wbdsrt"

DEFAULT_WEATHER = "DESERT"
DEFAULT_CONDITION = "SAND"


def build_bind_code(base_va: int, condition_bit: int, weather: int = NEW_WEATHER_INDEX) -> bytes:
    """The head cave for `Drawable::bindToObject`, as this patch builds it on a fresh site."""
    return map_weather.build_bind_code(base_va, condition_bit, weather)


def build_upgrade_code(base_va: int, condition_bit: int, weather: int = NEW_WEATHER_INDEX) -> bytes:
    """The head cave for the timed-upgrade expiry update, as this patch builds it on a fresh
    site."""
    return map_weather.build_upgrade_code(base_va, condition_bit, weather)


class DesertWeatherPatch(Patch):
    """Add a third global weather and the model condition it drives."""

    name = "desert-weather"
    author = "officialNecro"
    description = (
        "Add a DESERT global weather type that drives a new SAND model condition, the way the "
        "stock SNOWY drives SNOW. A map opts in with weather = 2 in its WorldInfo chunk "
        "(authored by desert-weather-wb, not map.ini), art with a SAND ModelConditionState or "
        "WeatherTexture = DESERT <texture>, and models follow the weather only under GameData's "
        "ForceModelsToFollowWeather"
    )

    def __init__(self, weather: str = DEFAULT_WEATHER, condition: str = DEFAULT_CONDITION):
        self.weather = weather
        self.condition = condition
        model_conditions.validate_name(self.weather)
        model_conditions.validate_name(self.condition)

    def __str__(self) -> str:
        return f"{self.name} ({self.weather} -> {self.condition})"

    def apply(self, data: bytearray) -> None:
        map_weather.apply_game(data, _SECTION_NAME, NEW_WEATHER_INDEX, self.weather, self.condition)

    def ini_surface(self) -> Engine:
        """The two tokens this patch adds: the weather (`GameData.Weather`, and the
        `WeatherTexture` selector that reads the same table) and the model condition it drives.

        The weather's index is the slot this patch owns; the model condition's bit depends on
        what else the binary carries, so only the first is stated here."""
        return Engine(
            enum_members=(
                EnumDelta("MapWeatherType", self.weather, NEW_WEATHER_INDEX, self.name),
                EnumDelta("ModelCondition", self.condition, None, self.name),
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        return map_weather.verify_game(
            data, _SECTION_NAME, NEW_WEATHER_INDEX, self.weather, self.condition
        )

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DesertWeatherPatch | None:
        """Recognise this patch **and recover both names it was applied with**, out of its own
        cave: the model-condition table it wrote ends in the condition, and the weather table
        after it holds the weather at slot 2."""
        found = map_weather.detect_game(data, _SECTION_NAME, NEW_WEATHER_INDEX)
        if found is None:
            return None
        try:
            patch = cls(weather=found[0], condition=found[1])
        except ValueError:
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--weather",
            default=DEFAULT_WEATHER,
            metavar="NAME",
            help=(
                f"name of the weather token to add (default {DEFAULT_WEATHER}); the value "
                "`GameData Weather =` and `WeatherTexture` then accept"
            ),
        )
        parser.add_argument(
            "--condition",
            default=DEFAULT_CONDITION,
            metavar="NAME",
            help=(
                f"name of the model condition it drives (default {DEFAULT_CONDITION}); uppercase "
                "letters, digits and underscores, and must not already be a model condition"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DesertWeatherPatch:
        return cls(weather=args.weather, condition=args.condition)


class DesertWeatherWorldbuilderPatch(Patch):
    """Teach Worldbuilder's map-settings weather dropdown `DESERT`.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** It is the authoring half of
    `desert-weather`; give both binaries the same weather name, since the map stores the index.
    The dropdown's bound is a hardcoded member count, and leaving it alone is destructive: the
    dialog clears a selection past it and writes -1 back into the map. Scope is the dropdown only
    - the editor viewport keeps drawing the non-`SAND` variant.
    """

    name = "desert-weather-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add DESERT to the map-settings weather dropdown, so a "
        "map can be authored with it and the dialog stops reverting it. Pass the same --weather "
        "name given to game.dat's desert-weather; the editor viewport still draws the non-SAND "
        "variant"
    )

    def __init__(self, weather: str = DEFAULT_WEATHER):
        self.weather = weather
        model_conditions.validate_name(self.weather)

    def __str__(self) -> str:
        return f"{self.name} ({self.weather})"

    def apply(self, data: bytearray) -> None:
        map_weather.apply_worldbuilder(
            data, WORLDBUILDER_SECTION_NAME, NEW_WEATHER_INDEX, self.weather
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        return map_weather.verify_worldbuilder(
            data, WORLDBUILDER_SECTION_NAME, NEW_WEATHER_INDEX, self.weather
        )

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DesertWeatherWorldbuilderPatch | None:
        """Recognise this patch **and recover its weather name** from its own cave."""
        weather = map_weather.detect_worldbuilder(
            data, WORLDBUILDER_SECTION_NAME, NEW_WEATHER_INDEX
        )
        if weather is None:
            return None
        try:
            patch = cls(weather=weather)
        except ValueError:
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--weather",
            default=DEFAULT_WEATHER,
            metavar="NAME",
            help=(
                f"name of the weather token to add (default {DEFAULT_WEATHER}); must match the "
                "one given to the game.dat `desert-weather` patch, since the map stores the index"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DesertWeatherWorldbuilderPatch:
        return cls(weather=args.weather)
