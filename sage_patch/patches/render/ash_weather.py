"""Add a global weather, `ASH_RAIN`, driving a new `ASHEN` model condition.

The same mechanism as `desert-weather` - `SNOWY` sets `SNOW` when a drawable is bound to its
object, and the new weather sets its own condition beside it - at the fixed weather slot 3, so a
map carries `weather = 3` whether or not `desert-weather` (slot 2) is applied too. Alone, slot 2
holds a placeholder that drives nothing. `AshWeatherWorldbuilderPatch` teaches the editor the
same token.

The table, the hooks and the "any weather" value are shared through `../utils/map_weather.py`, so
this and `desert-weather` compose in either order. Derivation: `../docs/ash-weather.md`.
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
    "WEATHER_INDEX",
    "AshWeatherPatch",
    "AshWeatherWorldbuilderPatch",
]

#: The slot `ASH_RAIN` owns: after `desert-weather`'s 2, whether or not that patch is applied.
WEATHER_INDEX = 3

_SECTION_NAME = ".ashw"
WORLDBUILDER_SECTION_NAME = ".wbash"

DEFAULT_WEATHER = "ASH_RAIN"
DEFAULT_CONDITION = "ASHEN"


class AshWeatherPatch(Patch):
    """Add the `ASH_RAIN` global weather and the model condition it drives."""

    name = "ash-weather"
    author = "officialNecro"
    description = (
        "Add an ASH_RAIN global weather type that drives a new ASHEN model condition, the way "
        "the stock SNOWY drives SNOW. A map opts in with weather = 3 in its WorldInfo chunk "
        "(authored by ash-weather-wb), art with an ASHEN ModelConditionState or WeatherTexture "
        "= ASH_RAIN <texture>; composes with desert-weather in either order. Models follow the "
        "weather only under GameData's ForceModelsToFollowWeather"
    )

    def __init__(self, weather: str = DEFAULT_WEATHER, condition: str = DEFAULT_CONDITION):
        self.weather = weather
        self.condition = condition
        model_conditions.validate_name(self.weather)
        model_conditions.validate_name(self.condition)

    def __str__(self) -> str:
        return f"{self.name} ({self.weather} -> {self.condition})"

    def apply(self, data: bytearray) -> None:
        map_weather.apply_game(data, _SECTION_NAME, WEATHER_INDEX, self.weather, self.condition)

    def ini_surface(self) -> Engine:
        """The weather token at its fixed slot, and the model condition it drives (whose bit
        depends on what else the binary carries)."""
        return Engine(
            enum_members=(
                EnumDelta("MapWeatherType", self.weather, WEATHER_INDEX, self.name),
                EnumDelta("ModelCondition", self.condition, None, self.name),
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        return map_weather.verify_game(
            data, _SECTION_NAME, WEATHER_INDEX, self.weather, self.condition
        )

    @classmethod
    def detect(cls, data: bytes | bytearray) -> AshWeatherPatch | None:
        """Recognise this patch and recover both names it was applied with, out of its cave."""
        found = map_weather.detect_game(data, _SECTION_NAME, WEATHER_INDEX)
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
    def from_cli_args(cls, args: argparse.Namespace) -> AshWeatherPatch:
        return cls(weather=args.weather, condition=args.condition)


class AshWeatherWorldbuilderPatch(Patch):
    """Teach Worldbuilder's map-settings weather dropdown `ASH_RAIN`, at slot 3.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** Give both binaries the same weather
    name, since the map stores the index. Without `desert-weather-wb` the dropdown also lists the
    slot-2 placeholder; picking it is harmless."""

    name = "ash-weather-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add ASH_RAIN to the map-settings weather dropdown at "
        "slot 3, so a map can be authored with it and the dialog stops reverting it. Pass the "
        "same --weather name given to game.dat's ash-weather; composes with desert-weather-wb"
    )

    def __init__(self, weather: str = DEFAULT_WEATHER):
        self.weather = weather
        model_conditions.validate_name(self.weather)

    def __str__(self) -> str:
        return f"{self.name} ({self.weather})"

    def apply(self, data: bytearray) -> None:
        map_weather.apply_worldbuilder(data, WORLDBUILDER_SECTION_NAME, WEATHER_INDEX, self.weather)

    def verify(self, data: bytes | bytearray) -> list[str]:
        return map_weather.verify_worldbuilder(
            data, WORLDBUILDER_SECTION_NAME, WEATHER_INDEX, self.weather
        )

    @classmethod
    def detect(cls, data: bytes | bytearray) -> AshWeatherWorldbuilderPatch | None:
        weather = map_weather.detect_worldbuilder(data, WORLDBUILDER_SECTION_NAME, WEATHER_INDEX)
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
                "one given to the game.dat `ash-weather` patch, since the map stores the index"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> AshWeatherWorldbuilderPatch:
        return cls(weather=args.weather)
