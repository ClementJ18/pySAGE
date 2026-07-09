"""Apply edited JSON attributes back onto a save (`apply_json`), producing a new `SaveFile`.

The JSON from `sage_save.export` is a *decoded view*, not the raw bytes, so writing edits back
needs the original save as the source of the (mostly opaque) chunk bulk. `apply_json` takes a
parsed save plus a possibly-edited dict and re-encodes only the fully-decoded chunks whose
fields are present: `CHUNK_GameState` (description, timestamp, map path, profile), the
`CHUNK_GameStateMap` header (map paths, game mode), `CHUNK_Campaign`, `CHUNK_Players` (per-player
`money` - a u32 in place), `CHUNK_GameLogic` (a live object's `position` - the transform's
translation column, three f32 in place), and `CHUNK_TacticalView` (the camera angle + look-at
position). Everything else in the dict (references, chunk table) is a read-only view and is
ignored.

BFME saves store *absolute* file offsets inside their nested blocks, so an edit that changed a
chunk's byte length would shift every later chunk and invalidate those offsets - an empirically
corrupt save. `apply_json` therefore requires each re-encoded chunk to keep its exact byte
length and raises `ValueError` otherwise: a timestamp change, a game-mode change or a
same-length rename apply cleanly, while a different-length rename is refused rather than
silently corrupting the file.
"""

import json
from dataclasses import replace
from datetime import datetime
from typing import Any

from sage_save.chunks import (
    decode_campaign,
    decode_game_logic,
    decode_game_state,
    decode_game_state_map,
    decode_players,
    decode_tactical_view,
    encode_campaign,
    encode_game_logic,
    encode_game_state,
    encode_game_state_map,
    encode_players,
    encode_tactical_view,
    set_object_position,
)
from sage_save.save import Chunk, SaveFile


def _replace_payload(chunks: list[Chunk], name: str, new_payload: bytes) -> None:
    """Swap the payload of the named chunk in place, refusing a byte-length change."""
    for index, chunk in enumerate(chunks):
        if chunk.name == name:
            if len(new_payload) != len(chunk.payload):
                raise ValueError(
                    f"editing {name} changed its size ({len(chunk.payload)} -> "
                    f"{len(new_payload)} bytes); BFME saves store absolute offsets, so only "
                    "length-preserving edits (timestamp, game mode, same-length rename) are "
                    "supported"
                )
            chunks[index] = Chunk(chunk.name, new_payload, chunk.offset)
            return
    raise ValueError(f"save has no {name}")


def apply_json(save: SaveFile, data: dict[str, Any]) -> SaveFile:
    """Return a new save with the editable fields in `data` applied. Only `game_state`,
    `game_state_map`, `campaign` and `tactical_view` are written; edits must preserve each chunk's
    byte length (float coordinates/angles and same-length strings qualify)."""
    chunks = list(save.chunks)

    game_state = data.get("game_state")
    if game_state:
        chunk = save.chunk("CHUNK_GameState")
        if chunk is None:
            raise ValueError("save has no CHUNK_GameState")
        header = decode_game_state(chunk)
        saved_at = header.saved_at
        if game_state.get("saved_at"):
            saved_at = datetime.fromisoformat(game_state["saved_at"])
        header = replace(
            header,
            description=game_state.get("description", header.description),
            map_name=game_state.get("map_name", header.map_name),
            user_name=game_state.get("user_name", header.user_name),
            saved_at=saved_at,
        )
        _replace_payload(chunks, "CHUNK_GameState", encode_game_state(header))

    game_state_map = data.get("game_state_map")
    if game_state_map:
        chunk = save.chunk("CHUNK_GameStateMap")
        if chunk is None:
            raise ValueError("save has no CHUNK_GameStateMap")
        gsm = decode_game_state_map(chunk)
        gsm = replace(
            gsm,
            save_map_name=game_state_map.get("save_map_name", gsm.save_map_name),
            pristine_map_name=game_state_map.get("pristine_map_name", gsm.pristine_map_name),
            game_mode=game_state_map.get("game_mode", gsm.game_mode),
        )
        _replace_payload(chunks, "CHUNK_GameStateMap", encode_game_state_map(gsm, chunk.payload))

    campaign_data = data.get("campaign")
    if campaign_data:
        chunk = save.chunk("CHUNK_Campaign")
        if chunk is None:
            raise ValueError("save has no CHUNK_Campaign")
        campaign = decode_campaign(chunk)
        campaign = replace(
            campaign,
            current_campaign=campaign_data.get("current_campaign", campaign.current_campaign),
        )
        _replace_payload(chunks, "CHUNK_Campaign", encode_campaign(campaign))

    logic_data = data.get("game_logic")
    if logic_data and logic_data.get("objects"):
        chunk = save.chunk("CHUNK_GameLogic")
        if chunk is None:
            raise ValueError("save has no CHUNK_GameLogic")
        state = decode_game_logic(chunk)
        by_id = {obj.object_id: index for index, obj in enumerate(state.objects)}
        for entry in logic_data["objects"]:
            if entry.get("position") is None:
                continue
            index = by_id.get(entry.get("object_id"))
            if index is None:
                raise ValueError(f"save has no object with id {entry.get('object_id')!r}")
            x, y, z = entry["position"]
            state.objects[index] = set_object_position(
                state.objects[index], (float(x), float(y), float(z))
            )
        _replace_payload(chunks, "CHUNK_GameLogic", encode_game_logic(state))

    players_data = data.get("players")
    if players_data:
        chunk = save.chunk("CHUNK_Players")
        if chunk is None:
            raise ValueError("save has no CHUNK_Players")
        players_state = decode_players(chunk)
        by_index = {p.index: p for p in players_state.players}
        for entry in players_data.get("players", []):
            player = by_index.get(entry.get("index"))
            if player is None:
                raise ValueError(f"save has no player with index {entry.get('index')!r}")
            if "money" in entry:
                player.money = int(entry["money"])  # a u32 in place: length-preserving
        _replace_payload(chunks, "CHUNK_Players", encode_players(players_state))

    view_data = data.get("tactical_view")
    if view_data:
        chunk = save.chunk("CHUNK_TacticalView")
        if chunk is None:
            raise ValueError("save has no CHUNK_TacticalView")
        view = decode_tactical_view(chunk)
        position = view.position
        if view_data.get("position") is not None:
            x, y, z = view_data["position"]
            position = (float(x), float(y), float(z))
        view = replace(view, angle=view_data.get("angle", view.angle), position=position)
        _replace_payload(chunks, "CHUNK_TacticalView", encode_tactical_view(view))

    return SaveFile(save.header, chunks)


def apply_json_text(save: SaveFile, text: str) -> SaveFile:
    """`apply_json` from a JSON string."""
    return apply_json(save, json.loads(text))
