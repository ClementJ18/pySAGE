"""The lookups: name to id, template to static fact, hero to revive slot.

An observation is deliberately small - an object names its `ThingTemplate` and stops there -
and an order carries integers rather than names. These modules are both halves of that join,
and they are separate from `sage_live.api` because two of them need a game tree on disk:

| module | answers | needs an install |
|---|---|---|
| `naming` | `"MordorFighterHorde"` -> this build's thing id | no |
| `heroes` | which revive slot a producer offers, and where a hero sits in the list | no |
| `resolve` | the same four id spaces, reconstructed from the ini tree | **yes** |
| `statics` | what `KindOf` says a template is: plot, victory-counting, horde member | **yes** |

`resolve` and `statics` import `sage_ini`, so they are **not** re-exported here or from the
package root - import them from their own module, the same split `sage_replay` uses:

```python
from sage_live.utils.statics import Statics
from sage_live.utils.resolve import Resolver
```

Both satisfy the protocols the session depends on (`NameLookup`, `ReviveLookup`), so a
session gains them by assignment and imports neither: `session.names = Resolver.from_root(...)`.

**Express policies over code names, never raw ids.** Edain renumbers its tables every
release, so an id baked into a policy silently means something different after an update,
while a name either resolves or fails loudly.
"""

from __future__ import annotations

from sage_live.utils.heroes import ReviveLookup, ReviveSlot, revive_index
from sage_live.utils.naming import (
    LiveNames,
    NameLookup,
    NoNameLookup,
    UnknownDefinition,
    nearby,
)

__all__ = [
    "LiveNames",
    "NameLookup",
    "NoNameLookup",
    "ReviveLookup",
    "ReviveSlot",
    "UnknownDefinition",
    "nearby",
    "revive_index",
]
