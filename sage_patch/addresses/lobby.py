"""The LAN lobby the shell drives: main menu, `AptLanLobby`, `TheLAN` and the LAN setup strategy.

Read statically. The lobby screen runs
the whole LAN flow from one update - the games list, the match setup it embeds, and the buttons,
each of which only stores a state the next update acts on - so a patch that drives it presses
buttons by storing the same states.
"""

from __future__ import annotations

__all__ = [
    "ASCII_STRING_TO_LOWER",
    "COMMAND_LINE_TO_ARGV_W_IAT",
    "GET_COMMAND_LINE_W_IAT",
    "INET_ADDR_IAT",
    "LAN_API_GAME_LIST",
    "LAN_API_MY_GAME",
    "LAN_API_PENDING_ACTION",
    "LAN_API_REQUEST_GAME_JOIN",
    "LAN_GAME_INFO_GET_LOCAL_SLOT",
    "LAN_GAME_INFO_IS_HOST",
    "LAN_GAME_INFO_NEXT",
    "LAN_LOBBY_BUSY",
    "LAN_LOBBY_CLOSING",
    "LAN_LOBBY_COMMIT_NAME",
    "LAN_LOBBY_CURRENT",
    "LAN_LOBBY_MODAL",
    "LAN_LOBBY_NAME_ENTRY",
    "LAN_LOBBY_SETUP",
    "LAN_LOBBY_STATE",
    "LAN_LOBBY_STATE_CREATE",
    "LAN_LOBBY_STATE_IDLE",
    "LAN_LOBBY_STATE_JOINING",
    "LAN_LOBBY_STATE_START",
    "LAN_LOBBY_UPDATE",
    "LAN_LOBBY_UPDATE_ENTRY",
    "LAN_LOBBY_UPDATE_RESUME",
    "LAN_SETUP_STRATEGY_ACCEPT",
    "LAN_SETUP_STRATEGY_COLOR",
    "LAN_SETUP_STRATEGY_MAP",
    "LAN_SETUP_STRATEGY_START_POS",
    "LAN_SETUP_STRATEGY_TEAM",
    "LAN_SETUP_STRATEGY_TEMPLATE",
    "LAN_SETUP_STRATEGY_VTABLE",
    "MAIN_MENU_STATE",
    "MAIN_MENU_STATE_IDLE",
    "MAIN_MENU_STATE_TRANSITION",
    "MAIN_MENU_TARGET",
    "MAIN_MENU_TARGET_LAN",
    "MAIN_MENU_UPDATE",
    "MAIN_MENU_UPDATE_ENTRY",
    "MAIN_MENU_UPDATE_RESUME",
    "MAP_CACHE_FIND",
    "MP_SETUP_GAME_INFO_CHANGED",
    "THE_LAN",
    "THE_MAP_CACHE",
    "WCSICMP_IAT",
    "WIDE_CHAR_TO_MULTI_BYTE_IAT",
    "WINDOW_SET_TEXT",
]

#: Imports the cave calls through their IAT slot, `call dword [slot]`. `CommandLineToArgvW` and
#: `GetCommandLineW` are stdcall; `_wcsicmp` is cdecl; `WideCharToMultiByte` and `inet_addr` are
#: stdcall.
GET_COMMAND_LINE_W_IAT = 0x00BD0168
COMMAND_LINE_TO_ARGV_W_IAT = 0x00BD07A0
WCSICMP_IAT = 0x00BD06FC
WIDE_CHAR_TO_MULTI_BYTE_IAT = 0x00BD0164
INET_ADDR_IAT = 0x00BD097C

#: `AptMainMenu::update`, vtable `0x00C7CDE0` slot 5, `thiscall` on the menu. Its first instruction
#: is the five-byte `mov eax, <EH record>` of an `EH_PROLOG` frame - the hook window.
MAIN_MENU_UPDATE = 0x0091C2FC
MAIN_MENU_UPDATE_ENTRY = bytes.fromhex("b8cd9bba00")
MAIN_MENU_UPDATE_RESUME = 0x0091C301
#: The menu's state machine. State 0 is the idle menu; 9 leaves for `MAIN_MENU_TARGET`, which the
#: update dispatches through the table at `0x0091C70B`. The `AptMainMenu::LAN` command
#: (`0x0091C743`) stores 9 and 6 when the firewall pop-up is not due (`0x0091C851`); target 6 calls
#: `0x0091B2ED` and loads the LAN screen through the callback `0x0091AD10`.
MAIN_MENU_STATE = 0x288
MAIN_MENU_TARGET = 0x28C
MAIN_MENU_STATE_IDLE = 0
MAIN_MENU_STATE_TRANSITION = 9
MAIN_MENU_TARGET_LAN = 6

#: `AptLanLobby::update`, the lobby screen's vtable entry at `0x00C54720`, `thiscall` on the screen.
#: It updates `TheLAN` (vtable `+0x28`) and then acts on `LAN_LOBBY_STATE`.
LAN_LOBBY_UPDATE = 0x008490E0
LAN_LOBBY_UPDATE_ENTRY = bytes.fromhex("b83ad7b900")
LAN_LOBBY_UPDATE_RESUME = 0x008490E5
#: The lobby screen that is up, stored by its command registration (`0x00848D29`).
LAN_LOBBY_CURRENT = 0x00DE8D90
#: Screen fields. `CLOSING` set makes the update skip everything (`0x008490F3`). `STATE` is the
#: button state machine; each button stores a state (`AptLanLobby::OnCreateGameBttn` 1 -> 2,
#: `OnJoinGameBttn` 1 -> 7, `OnStartGameBttn` -> 5, unconditionally) and the update acts on it.
#: `NAME_ENTRY` is the nickname text box, `SETUP` the embedded `MpGameSetup`.
LAN_LOBBY_CLOSING = 0x6C0
LAN_LOBBY_STATE = 0x6A4
LAN_LOBBY_NAME_ENTRY = 0x6B4
LAN_LOBBY_SETUP = 0x288
LAN_LOBBY_STATE_IDLE = 1
LAN_LOBBY_STATE_CREATE = 2
LAN_LOBBY_STATE_START = 5
LAN_LOBBY_STATE_JOINING = 8
#: What state 7 (Join) does before `RequestGameJoin`, at `0x00849317`: `thiscall (bool)` on the
#: screen, `ret 4`, called with 0; then `LAN_LOBBY_BUSY(1, 1)`, cdecl.
LAN_LOBBY_MODAL = 0x00848B39
LAN_LOBBY_BUSY = 0x00917C2D
#: The nickname box's commit: reads `NAME_ENTRY`'s text (the screen's default name when empty),
#: stores it and sends it with `TheLAN->RequestSetName`. `thiscall` on the screen, no arguments.
LAN_LOBBY_COMMIT_NAME = 0x00847383
#: `GadgetSetText(GameWindow *, UnicodeString)` - `GEM_SET_TEXT` (`0x4030`) through the window
#: manager. cdecl, the string by value and destroyed by the callee; the lobby's init uses it to
#: fill `NAME_ENTRY` (`0x0084805B`).
WINDOW_SET_TEXT = 0x006C236B

#: `TheLAN` (`LANAPI *`), created by the lobby screen's init (`0x00847F3E`) and deleted with it.
THE_LAN = 0x00DE4394
#: `LANAPI` fields: the games heard announced (a list through `LAN_GAME_INFO_NEXT`), the pending
#: join/create (`RequestGameJoin` refuses while it is not 0), and the game this client sits in.
LAN_API_GAME_LIST = 0x10
LAN_API_PENDING_ACTION = 0x28
LAN_API_MY_GAME = 0x44
#: `LANAPI::RequestGameJoin(LANGameInfo *, IPAddress *to)`, vtable `0x00C54CE0` `+0x40`
#: (`0x0084CB34`, `ret 8`). The Join button passes a zeroed `{u32 ip; u16 port}`: broadcast.
LAN_API_REQUEST_GAME_JOIN = 0x40

#: `LANGameInfo` (`0xFCC` bytes, a `GameInfo` first): the next game in `TheLAN`'s list.
LAN_GAME_INFO_NEXT = 0xFBC
#: `LANGameInfo` vtable `+0x34`: the local player's slot, -1 when not seated (`0x008492BC`).
LAN_GAME_INFO_GET_LOCAL_SLOT = 0x34
#: `LANGameInfo::amIHost`, `thiscall`, returns `al`.
LAN_GAME_INFO_IS_HOST = 0x0084A46D

#: The LAN match-setup strategy the embedded `MpGameSetup` asks for every seat change
#: (`MP_SETUP_STRATEGY`). Each setter is `thiscall (GameSlot *, Int) -> Bool`, `ret 8`: a host sets
#: the slot and broadcasts the options, a client sets it locally and sends `PlayerTemplate=%d`,
#: `Color=%d`, `StartPos=%d` or `Team=%d` to the host. `ACCEPT` is `(Bool)`, `ret 4`, a client's
#: Ready; `MAP` is `(const AsciiString *)`, `ret 4`, host only, and looks the map up itself.
LAN_SETUP_STRATEGY_VTABLE = 0x00C546A8
LAN_SETUP_STRATEGY_ACCEPT = 0x0C
LAN_SETUP_STRATEGY_COLOR = 0x10
LAN_SETUP_STRATEGY_MAP = 0x1C
LAN_SETUP_STRATEGY_TEMPLATE = 0x28
LAN_SETUP_STRATEGY_START_POS = 0x2C
LAN_SETUP_STRATEGY_TEAM = 0x30

#: `MpGameSetup`'s "the game info changed" - raises the three redraw flags its update consumes
#: (`+0x2C2`, `+0x2B9`, `+0x2BA`). `thiscall`, no arguments.
MP_SETUP_GAME_INFO_CHANGED = 0x0084000E

#: `TheMapCache` and its lookup: `thiscall (AsciiString)` by value, destroyed by the callee,
#: `ret 4`, returning the `MapMetaData` or NULL. Keys are lowercase.
THE_MAP_CACHE = 0x00DE4B74
MAP_CACHE_FIND = 0x00703C91
#: `AsciiString::toLower`, `thiscall`, in place.
ASCII_STRING_TO_LOWER = 0x004363B0
