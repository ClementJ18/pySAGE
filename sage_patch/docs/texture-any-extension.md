# A model's texture name and its extension

**Symptom.** A W3D mesh that names its texture `foo.tga` draws textured. The same mesh naming it
`foo.dds` - the file that actually ships - draws without it, and so does one naming `foo.png` or
plain `foo`.

**Cause.** The texture is looked up by the authored name, verbatim, and the asset cache holds
every texture under a `.tga` name whatever file provides it. Only one loader bends the name at
all, and it bends it only when the name already ends in `.tga`.

Static reading of build 2.01.2614.37001; not yet confirmed in a running game.

## 1. The name the cache knows

`asset.dat` lists each texture as `<stem>.tga`, also when the source file is a `.dds`
(`sage_asset/builder.py` reproduces this: the entry name is `file.stem + ".tga"`). The cache
answers "do you hold this name" through `ASSET_CACHE_HAS_ASSET` (`0x00A32D80`), a `cdecl (const
char *) -> bool` on the singleton at `0x00DEF75C`, false while there is no cache.

## 2. The getter

Every texture request goes through one function, `0x00532875` - `cdecl (TexturePtr *out, const
char *name, a3, a4)`, returning `out`, with 83 direct callers:

```
00532875  mov  eax, 0xb79b0f           ; EH handler
0053287a  call 0xa3cef0                ; EH_PROLOG
...
00532887  mov  esi, [ebp+0xc]          ; name
0053288a  test esi, esi
0053288c  jne  0x532898                ; a null name answers a null texture
...
0053289c  push esi
0053289d  push eax
0053289e  call 0xa32ee0                ; look the name up in the cache
...
005328e0  push esi
005328e1  call 0x532813                ; not found: construct a texture of that name
```

Nothing between the argument and the lookup touches the name.

## 3. The one place an extension is considered

The W3D texture chunk loader (`0x00532AE7`, chunk `0x31`; name sub-chunk `0x32`, info `0x33`)
reads the name into `[ebp-0x124]`, finds its last `.` and then:

```
00532b93  push 0xbdc7ec                ; ".tga"
00532b98  push esi                     ; the extension
00532b99  call [0xbd051c]              ; _strcmpi
00532ba3  jne  0x532c18                ; anything but .tga: the name is used as written
00532bc7  push 0xbdc7bc                ; ".dds"
00532bd9  call 0xa32d80                ; ASSET_CACHE_HAS_ASSET(<stem>.dds)
00532be5  push 0xbdc7b4                ; ".jpg", tried the same way
00532c03  ...                          ; whichever the cache holds replaces the name
00532cc7  call 0x532875                ; the getter
```

So a `.tga` name is retried as `.dds` and `.jpg`, for a hand-built `asset.dat` that indexes those
names, and falls back to itself. A name with any other extension skips the block and reaches the
getter unchanged - where `foo.dds` is not a name the cache holds.

The mesh loader's own direct reads (`0x0058A195`, `0x0058A2D1`) hand the getter a name straight
out of the chunk with no extension handling at all.

## 4. The patch

**Patch: `texture-any-extension`**. The getter's first instruction (five bytes at `0x00532875`)
becomes a `jmp` to a wrapper in a new `.texext` section. The wrapper has the getter's signature:

1. a null name, or one `ASSET_CACHE_HAS_ASSET` already knows, goes through as written;
2. otherwise the name is copied to a buffer in the wrapper's frame and everything from its last
   `.` on is overwritten with `.tga` (a name with no `.` has it appended);
3. if the cache holds that name, the getter is called with the buffer; if not, with the authored
   name.

The getter proper is then *called* through a two-instruction trampoline - the displaced `mov eax,
0xb79b0f` and a `jmp 0x0053287A` - because the buffer has to outlive the stock body, which reads
the name more than once.

Hooking the getter rather than the chunk loader's `.tga` test covers every caller, not just chunk
`0x31`. A name of `0x104` characters or more is not rewritten. A `.` that belongs to a directory
rather than to the file name produces a name the cache does not hold, which is case 3's stock arm.

`tests/sage_patch/test_texture_any_extension.py` runs the wrapper under Unicorn with the CRT
helpers and the cache lookup answered from Python: each kind of name, the name handed to the stock
body, the four arguments, the stack and the callee-saved registers.

## 5. Open

- Not played. The check: export a model whose texture chunk names `<stem>.dds`, add it to a unit,
  and compare with the same model naming `<stem>.tga`.
- Whether `ASSET_CACHE_HAS_ASSET` matches names case-insensitively is not read here; the wrapper
  asks it exactly what the chunk loader asks it.
- A texture that is in no `asset.dat` and loads from a loose file is untouched: with no cache
  entry under either name, the authored name goes through.
