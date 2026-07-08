"""Convert a parsed save into a JSON-serializable dict (`save_to_dict`) or JSON text
(`save_to_json`).

The export gathers everything the decoders currently understand — the container header and
chunk table, the `GameState` browser header, the `GameStateMap` map summary, `Campaign`, the
`GameLogic` frame + template table + object index + behavior-module-tag frequency, the
`GameClient` frame + drawable count with its attached/unattached split, the `TacticalView`
camera, and the harvested cross-reference names (object templates, upgrades, sciences) — into one
plain structure. The embedded map is summarised by size only, never
inlined; pass `include_objects=False` for a compact export that drops the per-object list
(keeping the counts, the module-tag summary and the reference summary).
"""

import json
from collections import Counter
from typing import Any

from sage_save.chunks import (
    decode_campaign,
    decode_game_client,
    decode_game_logic,
    decode_game_state,
    decode_game_state_map,
    decode_living_world_logic,
    decode_object_prefix,
    decode_players,
    decode_script_engine,
    decode_tactical_view,
    living_world_object_templates,
    object_modules,
    object_veterancy_level,
)
from sage_save.save import SaveFile
from sage_save.xref import harvest_references


def save_to_dict(save: SaveFile, *, include_objects: bool = True) -> dict[str, Any]:
    """A JSON-serializable view of everything decoded from `save`."""
    data: dict[str, Any] = {
        "container": {
            "id": save.header.container_id,
            "values": [save.header.value1, save.header.value2],
        },
        "chunks": [
            {"name": c.name, "version": c.version, "size": len(c.payload)} for c in save.chunks
        ],
    }

    state_chunk = save.chunk("CHUNK_GameState")
    if state_chunk is not None:
        header = decode_game_state(state_chunk)
        data["game_state"] = {
            "version": header.version,
            "description": header.description,
            "saved_at": header.saved_at.isoformat() if header.saved_at else None,
            "map_name": header.map_name,
            "hero_name": header.hero_name,
            "user_name": header.user_name,
        }

    map_chunk = save.chunk("CHUNK_GameStateMap")
    if map_chunk is not None:
        gsm = decode_game_state_map(map_chunk)
        data["game_state_map"] = {
            "version": gsm.version,
            "save_map_name": gsm.save_map_name,
            "pristine_map_name": gsm.pristine_map_name,
            "game_mode": gsm.game_mode,
            "embedded_map_bytes": len(gsm.map_data),
        }

    campaign_chunk = save.chunk("CHUNK_Campaign")
    if campaign_chunk is not None:
        campaign = decode_campaign(campaign_chunk)
        data["campaign"] = {
            "version": campaign.version,
            "active": campaign.active,
            "current_campaign": campaign.current_campaign,
            "mission_number": campaign.mission_number,
            "campaign_flag": campaign.campaign_flag,
            "heroes": [
                {
                    "name": h.name,
                    "experience": h.experience,
                    "rank": h.rank,
                    "health": h.health,
                    "upgrades": h.upgrades,
                }
                for h in campaign.heroes
            ],
        }

    logic_chunk = save.chunk("CHUNK_GameLogic")
    if logic_chunk is not None:
        logic = decode_game_logic(logic_chunk)
        section: dict[str, Any] = {
            "version": logic.version,
            "frame": logic.frame,
            "template_count": len(logic.templates),
            "object_count": len(logic.objects),
            "templates": {str(tid): name for tid, name in sorted(logic.templates.items())},
        }
        module_tags: Counter[str] = Counter(
            block.name
            for o in logic.objects
            for block in object_modules(o)
            if block.name is not None and block.depth == 0
        )
        section["module_tags"] = dict(module_tags.most_common())
        if include_objects:
            section["objects"] = [
                {
                    "object_id": o.object_id,
                    "template_id": o.template_id,
                    "template": o.template_name,
                    "position": list(decode_object_prefix(o).position),
                    "veterancy": object_veterancy_level(o),
                }
                for o in logic.objects
            ]
        data["game_logic"] = section

    client_chunk = save.chunk("CHUNK_GameClient")
    if client_chunk is not None:
        client = decode_game_client(client_chunk)
        # Every drawable renders one live GameLogic object; an `object_id` of 0xFFFFFFFF marks a
        # client-only drawable with no logic object behind it (none occur across the corpus).
        unattached = sum(1 for d in client.drawables if d.object_id == 0xFFFFFFFF)
        data["game_client"] = {
            "version": client.version,
            "frame": client.frame,
            "template_count": len(client.templates),
            "drawable_count": len(client.drawables),
            "attached": len(client.drawables) - unattached,
            "unattached": unattached,
        }

    players_chunk = save.chunk("CHUNK_Players")
    if players_chunk is not None:
        players = decode_players(players_chunk)
        data["players"] = {
            "version": players.version,
            "players": [
                {
                    "index": p.index,
                    "money": p.money,
                    "upgrades": [{"name": u.name, "status": u.status} for u in p.upgrades],
                    "upgrades_in_progress": p.upgrades_in_progress,
                    "upgrades_completed": p.upgrades_completed,
                    "sciences_disabled": p.sciences_disabled,
                    "sciences_hidden": p.sciences_hidden,
                    "team_ids": p.team_ids,
                }
                for p in players.players
            ],
        }

    script_chunk = save.chunk("CHUNK_ScriptEngine")
    if script_chunk is not None:
        script = decode_script_engine(script_chunk)
        data["script_engine"] = {
            "version": script.version,
            "counters": [
                {
                    "scope": c.scope,
                    "name": c.name,
                    "value": c.value,
                    "is_countdown_timer": c.is_countdown_timer,
                }
                for c in script.counters
            ],
            "flags": [{"scope": f.scope, "name": f.name, "value": f.value} for f in script.flags],
            "named_objects": [
                {"name": name, "object_id": object_id} for name, object_id in script.named_objects
            ],
            "scoped_named_objects": [
                {"scope": scope, "name": name, "object_id": object_id}
                for scope, name, object_id in script.scoped_named_objects
            ],
            # keyed by player-list slot index; the "Player_N" scope strings above are script
            # player *names* and need not line up with these slots
            "player_sciences": {
                f"slot_{i}": sciences
                for i, sciences in enumerate(script.player_sciences)
                if sciences
            },
            "difficulty": script.difficulty,
        }

    lwl_chunk = save.chunk("CHUNK_LivingWorldLogic")
    if lwl_chunk is not None:
        lwl = decode_living_world_logic(lwl_chunk)
        if lwl.names:  # omit the empty vanilla-skirmish constant (no living world)
            # `LWA:*` are living-world army-type references, distinctive enough to split out;
            # `object_templates` are the army rosters' units/heroes (the `02 01`-signature subset
            # that resolves as ini objects); the rest of the roster (players, army instances, icons,
            # banners, regions) is a flat name view — the record structure isn't walked yet.
            data["living_world"] = {
                "version": lwl.version,
                "name_count": len(lwl.names),
                "armies": [n for n in lwl.names if n.startswith("LWA:")],
                "object_templates": living_world_object_templates(lwl_chunk.payload),
                "names": lwl.names,
            }

    view_chunk = save.chunk("CHUNK_TacticalView")
    if view_chunk is not None:
        view = decode_tactical_view(view_chunk)
        data["tactical_view"] = {
            "version": view.version,
            "angle": view.angle,
            "position": list(view.position),
        }

    data["references"] = [
        {"kind": r.kind, "name": r.name, "count": r.count, "fatal": r.fatal}
        for r in harvest_references(save)
    ]
    return data


def save_to_json(save: SaveFile, *, indent: int | None = 2, include_objects: bool = True) -> str:
    """`save_to_dict` rendered as JSON text (`indent=None` for a compact single line)."""
    return json.dumps(save_to_dict(save, include_objects=include_objects), indent=indent)
