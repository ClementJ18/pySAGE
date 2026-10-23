"""Global weather and the inlined RTS3DScene fog submission in RotWK 2.01.2614.37001.

The NONE/CLOUDY/RAINY/CLOUDYRAINY/SUNNY system is separate from GlobalData's
NORMAL/SNOWY/DESERT weather. These fingerprints come from game.dat.backup, not BFME2 VAs.
"""

__all__ = [
    "GLOBAL_WEATHER_CLOUDY",
    "GLOBAL_WEATHER_CURRENT",
    "THE_GLOBAL_WEATHER_SYSTEM",
    "WEATHER_FOG_ANCHORS",
    "WEATHER_FOG_ENABLE",
    "WEATHER_FOG_HOOK",
    "WEATHER_FOG_HOOK_BYTES",
    "WEATHER_FOG_RESUME",
    "WEATHER_FOG_PROJECTION_OVERRIDE",
    "WEATHER_FOG_STATIC_LOD",
    "WEATHER_FOG_OBJECT_HOOK_BYTES",
    "WEATHER_FOG_SCENE_RGB_HOOK",
    "WEATHER_FOG_OBJECT_RGB_HOOK",
    "WEATHER_FOG_GHOST_RGB_HOOK",
    "WEATHER_FOG_MESH_GATE_HOOK",
    "WEATHER_FOG_MESH_ENABLED",
    "WEATHER_FOG_SCENE_EXIT_HOOK",
    "GLOBAL_WEATHER_FOGGY",
    "GLOBAL_WEATHER_SENTINEL",
    "GLOBAL_WEATHER_NAMES",
    "GLOBAL_WEATHER_TIMER",
    "FOGGY_NATIVE_HOOK_BYTES",
    "FOGGY_NATIVE_ANCHORS",
    "FOGGY_PARSER_TABLE_HOOK",
    "FOGGY_PARSER_LIMIT_HOOK",
    "FOGGY_VISUAL_HOOK",
    "FOGGY_SOUND_HOOK",
    "FOGGY_TEXTURE_HOOK",
    "FOGGY_WB_ANCHORS",
    "FOGGY_WB_HOOK_BYTES",
    "FOGGY_WB_TABLE",
    "FOGGY_WB_TABLE_HOOK",
    "FOGGY_WB_LIMIT_HOOK",
]

THE_GLOBAL_WEATHER_SYSTEM = 0x00DE772C
GLOBAL_WEATHER_CURRENT = 0x10
GLOBAL_WEATHER_CLOUDY = 1
GLOBAL_WEATHER_FOGGY = 6
GLOBAL_WEATHER_SENTINEL = 5
GLOBAL_WEATHER_NAMES = 0x00DB0074
GLOBAL_WEATHER_TIMER = 0x28
WEATHER_FOG_ENABLE = 0x00DD3461
WEATHER_FOG_HOOK = 0x00471913
WEATHER_FOG_HOOK_BYTES = bytes.fromhex("a26134dd00")
WEATHER_FOG_RESUME = 0x00471918
WEATHER_FOG_PROJECTION_OVERRIDE = 0x00DD3445
WEATHER_FOG_STATIC_LOD = 0x00D9B058
WEATHER_FOG_SCENE_RGB_HOOK = 0x0046FEC3
WEATHER_FOG_OBJECT_RGB_HOOK = 0x0046F557
WEATHER_FOG_GHOST_RGB_HOOK = 0x0046FA6D
WEATHER_FOG_MESH_GATE_HOOK = 0x00546C33
WEATHER_FOG_MESH_ENABLED = 0x00546C3C
WEATHER_FOG_SCENE_EXIT_HOOK = 0x00471A40

# Whole, position-independent instructions. RGB is copied into RenderInfo+8/0C/10;
# the ghost path subsequently applies the engine's original shroud-color scale.
WEATHER_FOG_OBJECT_HOOK_BYTES: dict[int, bytes] = {
    WEATHER_FOG_SCENE_RGB_HOOK: bytes.fromhex("8b4f208948088b4f2489480c8b4f28894810"),
    WEATHER_FOG_OBJECT_RGB_HOOK: bytes.fromhex("8b4e208948088b4e2489480c8b4e28894810"),
    WEATHER_FOG_GHOST_RGB_HOOK: bytes.fromhex("f30f104628f30f104e24f30f105620"),
    WEATHER_FOG_MESH_GATE_HOOK: bytes.fromhex("80bdbd00000000"),
    WEATHER_FOG_SCENE_EXIT_HOOK: bytes.fromhex("5f5e5bc9c20400"),
}

# The setup proves XMM1/start/[ebp-14], XMM0/end/[ebp-18], RGB pointer/[ebp-10].
# The continuation packs RGB and submits the same ranges to the renderer. [ebp-1c]
# is a live scene pointer loaded later, and must never be used as a fog temporary.
WEATHER_FOG_ANCHORS: dict[int, bytes] = {
    # Existing scheduler evidence pins the dereferenced GameLogic frame source.
    0x00850C32: bytes.fromhex("a12c41de008b5040"),
    0x0062B925: bytes.fromhex("a12c41de008b4040"),
    0x0090F92C: bytes.fromhex("8a8124010000c3"),
    0x006329CD: bytes.fromhex("8b0d2c41de0053e853cf2d00"),
    0x004717CC: bytes.fromhex("803d4534dd0000750b33c040390558b0d9007d0232c0"),
    0x004718E2: bytes.fromhex(
        "0f57d2f30f104730f30f104f2c8365fc008d47208945f08a471c"
        "f30f1155f8f30f1015a888bd00f30f1145e8f30f114dec"
    ),
    WEATHER_FOG_RESUME: bytes.fromhex(
        "f30f1155f483ec149b9bd97c24108b4424108bf825fff3ffff0d000c00002bf87406"
        "890424d92c248b75f0d945f4d906d94604d94608d945f8d9c4dcccdccbdccadec9"
        "db1c24db5c2404db5c2408db5c240c8b0c248b4424048b5424088b5c240cc1e118"
        "c1e310c1e2080bc10bc30bc2ddd883ff0074059bd96c241083c4148945fcff75ec"
        "8b45fc6a24a36434dd00f30f110d6834dd00f30f11056c34dd00c605d4b2d90001"
        "e8413fffffff75e86a25e8373fffff"
    ),
    0x004719EB: bytes.fromhex("8b0d6443de008b75e4884168"),
    # Setter: compares/writes current weather at +10, independently of the renderer.
    0x0071A024: bytes.fromhex("8b442404394110741f8941108b44240c8941288b442408"),
    # FreezingRainSpecialPower's caller resolves the actual RotWK singleton address.
    0x00897B38: bytes.fromhex("ff73308b0d2c77de00ff737050e8da24e8ff"),
    0x00DB0074: bytes.fromhex("8415bd00c80cbd00c00cbd00b40cbd00ac0cbd00"),
    0x00BD1584: b"NONE\0",
    0x00BD0CC8: b"CLOUDY\0",
    0x00BD0CC0: b"RAINY\0",
    0x00BD0CB4: b"CLOUDYRAINY\0",
    0x00BD0CAC: b"SUNNY\0",
    0x00BD88A8: bytes.fromhex("00007f43"),  # 255.0f, used by native RGB conversion
}

# RotWK object routing, blend-aware shader selection and shared FX fog bindings.
WEATHER_FOG_ANCHORS.update(
    {
        0x00537B88: bytes.fromhex("257253001e7253001072530019725300"),
        # Scene::Flush drains the native mesh renderer before the scene epilogue.
        0x00470F44: bytes.fromhex("b8282fb700e8a2bf5c0081eca00300005357ff75088bf9897dece81d5e0a00"),
        0x0046F527: bytes.fromhex(
            "803d6134dd0000a16443de000fb688e90b00000fb680e80b0000f30f2ac88b4508f30f2ac1f30f5e"
            "c1f30f1145ec7412"
        ),
        0x0046FA58: bytes.fromhex("8b45088d8e8c030000894828803d6134dd0000742d"),
        0x0046FA7C: bytes.fromhex("f30f5945ecf30f594decf30f5955ecf30f115008f30f11480cf30f114010"),
        0x0046FEB7: bytes.fromhex("803d6134dd00008b45087412"),
        0x0046FED5: bytes.fromhex("39b7ec0700007509ff308b17"),
        0x00471A2C: bytes.fromhex("ff75088b068bceff505cff75088bcee804f5ffff"),
        0x00546C2A: bytes.fromhex("803d6134dd00007476"),
        0x00546C3A: bytes.fromhex(
            "7419f6c4037568688cbcbd008d4c2420e89110ffff8b44241ceb0cf6c403744f80e4fc8944241c80"
            "3dd4b2d9000075083b051840dd007437800d351fdd0080a31840dd00a1c4aedb006a008d4c24146a"
            "0089442418e86cdb4d008a0d68e7de008b542410880a8d4c2410e887da4d00"
        ),
        0x00537CE0: bytes.fromhex(
            "8b018bd0c1ea0e83e20383fa03775aff24954c7d53008bd080e2e080fa40754980cc038901c20400"
            "8bd0c1ea0583e20783ea00742c83ea01740583ea02752a80e4fe80cc028901c204008bd081e2e000"
            "000080faa0eb088bd080e2e080fa80750880e4fd80cc018901c20400f67c5300087d53002a7d5300"
            "377d5300"
        ),
        0x005371D5: bytes.fromhex(
            "a1bc34dd00f644242103747880b8ac020000007451803d6134dd000074488b45008b3d6434dd00c1"
            "e80883e00333f683f803771eff2485887b530033ffbe01000000eb0ebfffffff00be01000000eb02"
            "33f6566a1ce8d5e6f2ff83c4083bf37410576a22eb03536a1ce8c1e6f2ff83c40881642420fffcff"
            "ff0f842a090000"
        ),
        0x0054B6E4: bytes.fromhex(
            "803d6134dd00007427f30f104308f30f104b0cf30f105310f30f118614030000f30f118e18030000"
            "f30f11961c030000"
        ),
        0x0054A0C9: bytes.fromhex(
            "803d6134dd0000a16434dd00a3ec90dd000f84d6000000f30f108614030000f30f1145e0f30f1086"
            "18030000f30f1145e4f30f10861c030000f30f1145e8"
        ),
        0x0058B5C8: bytes.fromhex(
            "0fb6156134dd008b4424048b0852ff74240c50ff5158c3558bec83ec1466a16634dd00f30f100520"
            "19bd000fb6ccf30f2ac9b9ff000000f30f59c823c1f30f2ad0a16434dd000fb6d423c185c08945fc"
            "f30f2adaf30f59d0db45fcf30f59d87d06d8059886bd008b4508d80d2019bd008b088d55ec52d95d"
            "f4ff750cf30f1155ec50f30f115df0f30f114df8ff9188000000c9c38b442404d9056834dd008b08"
            "51d91c24ff74240c50ff5178c38b442404d9056c34dd008b0851d91c24ff74240c50ff5178c3"
        ),
    }
)

WEATHER_FOG_ANCHORS[0x0054A107] = bytes.fromhex(
    "0f57c053f30f1145f8f30f1005a888bd008d4de057894df0f30f1145f4c745fc0000000083ec149b"
    "9bd97c24108b4424108bf825fff3ffff0d000c00002bf87406890424d92c248b75f0d945f4d906d9"
    "4604d94608d945f8d9c4dcccdccbdccadec9db1c24db5c2404db5c2408db5c240c8b0c248b442404"
    "8b5424088b5c240cc1e118c1e310c1e2080bc10bc30bc2ddd883ff0074059bd96c241083c4148945"
    "fc8b55fc8b75ec5f89156434dd005b"
)

# Native GlobalWeatherType extension; all locations are verified RotWK VAs.
FOGGY_PARSER_TABLE_HOOK = 0x00896701
FOGGY_PARSER_LIMIT_HOOK = 0x0089671F
FOGGY_VISUAL_HOOK = 0x00497D2F
FOGGY_SOUND_HOOK = 0x00719E0F
FOGGY_TEXTURE_HOOK = 0x00496F4D

FOGGY_NATIVE_HOOK_BYTES: dict[int, bytes] = {
    FOGGY_PARSER_TABLE_HOOK: bytes.fromhex("687400db00"),
    FOGGY_PARSER_LIMIT_HOOK: bytes.fromhex("83f805"),
    FOGGY_VISUAL_HOOK: bytes.fromhex("8b48103bcb"),
    FOGGY_SOUND_HOOK: bytes.fromhex("8b46108d44c630"),
    FOGGY_TEXTURE_HOOK: bytes.fromhex("3958107503"),
}

# Lighting consumers, native lifecycle and serialization are also fingerprinted.
FOGGY_NATIVE_ANCHORS: dict[int, bytes] = {
    # Case-insensitive NULL-terminated lookup and its throwing wrapper.
    0x0042B914: bytes.fromhex(
        "558bec51518b4510568b750c85f657c60000744f833e00744a33ffff7508ff36ff151c05bd0085c0"
        "5959742783c60447833e0075e6807d14007424ff75088d45f868543bbd006a0350e85f3a000083c4"
        "10eb238b4510c600018bc75f5ec9c333c0ebf8681c3bbd008d45f86a0250e83a3a000083c40c6800"
        "70d1008d45f850e86c146100cc558bec83ec0c6a008d45ff50ff750cc645ff00ff7508e860ffffff"
        "83c410807dff007524ff75088d45f468543bbd006a0350e8f139000083c410680070d1008d45f450"
        "e823146100c9c208"
    ),
    0x00469108: bytes.fromhex(
        "8b0d243cde0085c90f848e0000008b01ff503c84c074718b0d243cde008b018d55a452ff5048f30f"
        "10050819bd00f30f5c008b0d243cde00f30f5945c88b018d55b052f30f1145c8ff5048f30f100508"
        "19bd00f30f5c40048b0d243cde00f30f5945cc8b018d55bc52f30f1145ccff5048f30f10050819bd"
        "00f30f5c4008f30f5945d0f30f1145d0"
    ),
    # Scene lighting consumes the real cloud singleton and virtual RGB getter.
    0x004713C0: bytes.fromhex(
        "8b0d243cde003bcbf30f1145e0f30f1145e4f30f1145e874438b01ff503c84c0743a8b0d243cde00"
        "8b018d55d452ff5048f30f10050819bd000f28c8f30f5c48080f28d0f30f5c5004f30f5c00f30f11"
        "45e0f30f1155e4f30f114de8"
    ),
    0x00494794: bytes.fromhex("83b9c0000000000f95c0c3"),
    0x00494D4A: bytes.fromhex("8b44240481c1d4000000d901d9188b51048950048b4908894808c20400"),
    0x00494DBA: bytes.fromhex(
        "b8ae43b700e82c815a0083ec40538bd98b83c000000085c00f844304000083f80256578d7de48d73"
        "30a5a5a50f85ab0300003983bc00000075098d733c8d7de4a5a5a58b0d2c77de0085c97407e8d84d"
    ),
    0x00494DFD: bytes.fromhex("8b0d2c77de0085c97407e8d84d2800eb0232c084c00f8453030000"),
    0x0049516B: bytes.fromhex(
        "f30f1045e4f30f1183d4000000f30f1045e8f30f1183d8000000f30f1045ecf30f1183dc000000e9"
        "8200000083bbbc00000002db83c4000000dc0d90e1bd00dc2d982cbd00d95df075098d733c8d7de4"
        "a5a5a5f30f1045e4f30f5945f0f30f1183d4000000f30f1045e8f30f5945f0f30f1183d8000000f3"
        "0f1045ecf30f5945f0f30f1183dc0000008b0d8843de008b01ff507c6a0a33d259f7f185d2750f8b"
        "0dec78dc008b0152ff90240200005f5e8b4df45b64890d00000000c9c3"
    ),
    0x0049525D: bytes.fromhex("33db43"),
    0x00496F48: bytes.fromhex("a12c77de00"),
    0x00496F52: bytes.fromhex("57eb03ff75a856e8f27e0800"),
    # Client-frame gate; hooks start immediately after this range.
    0x00497D00: bytes.fromhex(
        "53568bf18b0d8843de008b01ff507c33db8d8e0001000032d243390175028ad384d289010f855101"
        "0000a12c77de00"
    ),
    0x00497D34: bytes.fromhex(
        "5557751b8dbebc000000391f74278b068bceff5038899ec0000000891feb168d86bc000000391875"
        "0cc786c00000000300000089088b0d2c77de0033ed3bcd7407e86a1e2800eb0232c084c00f859f00"
        "00008d86c80000008038000f84900000000f57c0c600008d86d400000089aecc000000f30f1186d0"
        "00000089ae04010000f30f1100f30f114004f30f114008807e5c0074248b0d7475dc008d86e00000"
        "0050e89160fdffa13cb8dc003bc574098b8ef80000008948048b0d7475dc00538dbeec00000057e8"
        "a960fdff0f57c08d86e0000000f30f1100f30f114004f30f114008f30f1107f30f114704f30f1147"
        "086a0259390d9c98d90075408b86c00000003bc375168d86c4000000ff0839287f2a8928898ec000"
        "0000eb2083f803751b8d86c4000000ff008b10b9ff0000003bd17c08890889aec00000005f5d8bce"
        "5e5be93fcfffff5e5bc3"
    ),
    # DarkeningFactor / DarkeningFactorRain copied from the active CloudEffect settings.
    0x00614CED: bytes.fromhex("8d7b30bee03cde00d95b2ca5a5a58d7b3cbeec3cde00a5a5a5"),
    0x00647052: bytes.fromhex(
        "8b068bceff90bc0000003bc3a3243cde0074228b108bc8ff5204518965f08bcc683c47c000e86404"
        "dfff8b0d243cde00e8f87be2ff"
    ),
    # GameClient update dispatches CloudEffectManager through slot +28.
    0x00648594: bytes.fromhex("8b0d243cde0085c974058b01ff5028"),
    0x00670A06: bytes.fromhex(
        "83ec0c568bf18b0d243cde0085c974338b01ff503c84c0742a8b0d243cde008b018d54240452ff50"
        "488bc88b118d869000000089108b51048950048b4908894808eb0233c05e83c40cc3"
    ),
    0x006DFAE0: bytes.fromhex(
        "a12c77de008bc883c00cf7d91bc95323c851518965fc8bcc68b8a4c100e8de79d5ff8bce"
    ),
    # GlobalWeatherType passes its label and a four-byte value to XferEnum.
    0x0070777F: bytes.fromhex("8b4c24048b016a04ff74240c68ace0c100ff9094000000c3"),
    0x00707797: bytes.fromhex(
        "8b4c24048b016a04ff74240c68c0e0c100ff9094000000c38b4c24048b016a04ff74240c68dce0c1"
        "00ff9094000000c3"
    ),
    0x00719BE4: bytes.fromhex("8b411085c07c0a83f8057d058a44c134c332c0c3"),
    # Audio stops the previous handle before the bounded-index hook.
    0x00719DEE: bytes.fromhex("b8d1ecb800e8f830320081ec88000000568bf18b0dfc42de00ff76148b01ff506c"),
    0x00719E16: bytes.fromhex(
        "c746140100000083380074366a00508d8d6cffffffe82e0bfcff8b0dfc42de008b018365fc008d95"
        "6cffffff52ff5064834dfcff8d8d6cffffff894614e8730dfcff8b4df45e64890d00000000c9c3"
    ),
    0x00719EBE: bytes.fromhex(
        "b804edb800e82830320051568bf1578975f0e8a4a7e9ff33ff897dfcc7460cb015bd008d4e1cc645"
        "fc01c706ac2dc200c7460c9c2dc200897e10c7461401000000897e18e868a10400897e20685d9c71"
        "0068539c71006a056a088d463050c645fc03897e28897e2ce8633332008d4e58e885240e008b4df4"
        "5f8bc65e64890d00000000c9c3"
    ),
    # Native setter: actual weather ID, duration and sound refresh.
    0x0071A024: bytes.fromhex(
        "8b442404394110741f8941108b44240c8941288b4424088b15a846de00898298000000e8a2fdffffc20c00"
    ),
    # Native logic update expires the duration back to NONE.
    0x0071A09E: bytes.fromhex(
        "568bf18b462c85c08d48ff894e2c740b85c975078bcee896ffffff8b462885c08d48ff894e28740e"
        "85c9750a5151518bcee850ffffff5ec3"
    ),
    0x0071A0D6: bytes.fromhex("83c1f4e910fdffff"),
    # Snapshot this is WeatherSystem+0C; current ID at +4, timers at +1C/+20.
    0x0071A2E3: bytes.fromhex(
        "558bec51568bf1578b7d088b078d4dfc518bcfc645fc01c645fd04ff50288d46045057e874d4feff"
        "59598b0dfc42de008b018d56085257ff90600100008d460c5057e86dd4feff5959578d4e10e8aa9b"
        "04008b078d4e14518bcfff506c836508008d45085057e861d4feff807dfd025959720b8b078d4e18"
        "518bcfff5078807dfd0372168b078d4e1c518bcfff50788b078d4e20518bcfff5078807dfd04720b"
        "578d4e4ce81bfeffffeb296a0483c64c6a0056e88d2b32008b4d0883c40c85c9741233d28bc183e1"
        "1f42c1e805d3e28d048609105f5ec9c2"
    ),
    0x008966F9: bytes.fromhex("558bec51518b4d08"),
    0x00896706: bytes.fromhex("6a00e89275b9ff8b4d0850e88352b9ff85c08b4d1089017c05"),
    0x00896722: bytes.fromhex(
        "7e225168144ac6008d45f86a0350e88c8cb9ff83c410680070d1008d45f850e8be661a00c9c3"
    ),
    0x00897B2C: bytes.fromhex("8b436483f8050f84dc010000ff73308b0d2c77de00ff737050e8da24e8ff"),
    # Generic enum transfer checks size 1..4, without an enum-value upper bound.
    0x00A1F8B5: bytes.fromhex(
        "558bec51518b451085c0568bf1745083f804774b48742d48741e48740f4875386a04ff750c683475"
        "6e65eb226a03ff750c6833756e65eb166a02ff750c6832756e65eb0a6a01ff750c6831756e658b06"
        "8bceff90980000008bc65ec9c20c006a008d45f86a0450e82d07000083c40c681c8ad1008d45f850"
        "e8d2d40100cc"
    ),
    0x00A3CEF0: bytes.fromhex("6aff5064a100000000508b44240c64892500000000896c240c8d6c240c50c3"),
    0x00BD1908: bytes.fromhex("0000803f"),
    0x00BD2C98: bytes.fromhex("000000000000f03f"),
    0x00BDE130: bytes.fromhex(
        "e47c4900bff363009a4b5b00bff36300c1ea7f00eb889100971e85003c3a9f00bff363001b4e6100"
        "007d4900c1ea7f00bff363003c3a9f00714c6100944749005c464900954649004a4d4900434d4900"
    ),
    0x00BDE190: bytes.fromhex("101010101010703f"),
    0x00BF3C74: bytes.fromhex("4d4f554e54454400"),
    0x00BFB728: bytes.fromhex("182ebe0099ef42000000000020000000b4b9bf0099ef4200000000002c000000"),
    0x00C22D9C: bytes.fromhex("499f7100d6a07100439f7100e3a27100"),
    # ChangeWeather field descriptor: behavior ModuleData offset +64.
    0x00C64F80: bytes.fromhex("9c4bc600f96689000000000064000000"),
    # Original unterminated weather names plus adjacent table; never overwritten.
    0x00DB0074: bytes.fromhex(
        "8415bd00c80cbd00c00cbd00b40cbd00ac0cbd00743cbf00643cbf005c3cbf0000000000"
    ),
}

# GameClient factory receiver and its real +7C client-frame getter.
FOGGY_NATIVE_ANCHORS.update(
    {
        0x0044BCD4: bytes.fromhex("568bf1e810c51f00c706e0a6bd00c7460ccca6bd008bc65ec3"),
        0x0044BEC3: bytes.fromhex(
            "b89815b700e823105f00516808010000e80838feff598bc8894df033c03bc88945fc7405"
            "e8798d04008b4df464890d00000000c9c3"
        ),
        0x00BDA75C: bytes.fromhex("1a9f9f00"),
        0x00BDA79C: bytes.fromhex("c3be4400"),
        0x009F9F1A: bytes.fromhex("8b4110c3"),
    }
)

# RotWK Worldbuilder.exe.backup, SHA256 005971be...05ec65d; its own ChangeWeather parser.
FOGGY_WB_TABLE = 0x0223A2AC
FOGGY_WB_TABLE_HOOK = 0x011FA12C
FOGGY_WB_LIMIT_HOOK = 0x011FA154
FOGGY_WB_HOOK_BYTES: dict[int, bytes] = {
    FOGGY_WB_TABLE_HOOK: bytes.fromhex("68aca22302"),
    FOGGY_WB_LIMIT_HOOK: bytes.fromhex("833805"),
}
FOGGY_WB_ANCHORS: dict[int, bytes] = {
    0x011FA120: bytes.fromhex("558bec83ec0c8b45108945fc"),
    0x011FA131: bytes.fromhex(
        "6a008b4d08e8b5804dff508b4d08e8bc454dff8b4dfc89018b55fc833a007c088b45fc"
    ),
    0x011FA157: bytes.fromhex(
        "7e258b4d1051686c22f4016a038d55f452e873b44dff83c41068b01d10028d45f450e89c954c008be55dc3"
    ),
    # ChangeWeather -> callback 011FA120, behavior offset +64.
    0x01F426F0: bytes.fromhex("0c23f40120a11f010000000064000000"),
    FOGGY_WB_TABLE: bytes.fromhex(
        "f4c0dd0154dce2014cdce20140dce20138dce201eccfdf01dccfdf01d4cfdf0100000000"
    ),
}
