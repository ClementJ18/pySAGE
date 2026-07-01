"""Typed game-object layer over the AST. An `IniObject` subclass declares its fields as
annotations (`BuildCost: Int = 0`); values are stored raw and converted lazily on first
read, so a bad value only surfaces when something asks for it. Cross-references resolve
through the `Game` tables at access time.
"""

import re
from typing import Self

from sage_ini.parser.ast import Attribute, Block
from sage_ini.parser.diagnostics import Severity
from sage_ini.suggest import suggestion_hint

__all__ = [
    "IniObject",
    "Module",
    "NestedAttribute",
    "Nugget",
    "Behavior",
    "Draw",
    "REGISTRY",
    "get_class",
    "resolve_annotation",
    "classify_subblock",
    "is_multivalued",
    "Multivalued",
    "MarkerGroup",
    "MarkerGroupItem",
]

# Split a header label into tokens, keeping a `"quoted name"` (a name written
# with spaces, like `FontDefaultSettings "Courier New"`) as a single token.
_LABEL_TOKEN = re.compile(r'"[^"]*"|\S+')


def _label_tokens(label: str) -> list[str]:
    return _LABEL_TOKEN.findall(label)


REGISTRY: dict[str, type["IniObject"]] = {}


def get_class(name: str) -> type["IniObject"] | None:
    return REGISTRY.get(name)


def resolve_annotation(annotation):
    """A field annotation is either a converter object or a class name string. A field may
    also be declared `Annotated[PyType, converter]` — the `PyType` is there only so the IDE
    sees the value's real type; the converter (the first metadata entry) is what runs."""
    if hasattr(annotation, "__metadata__"):
        annotation = annotation.__metadata__[0]
    if isinstance(annotation, str):
        return REGISTRY[annotation]
    return annotation


class Multivalued:
    """Marker base for a converter that consumes a repeated key's *whole* value list (one
    element per occurrence), instead of the last-wins scalar default. Subclassing declares
    the contract; nothing reads a magic attribute."""


def is_multivalued(converter) -> bool:
    """Whether a resolved converter consumes a repeated key's whole value list, whether it
    is a class or a configured instance (`List[...]`)."""
    cls = converter if isinstance(converter, type) else type(converter)
    return issubclass(cls, Multivalued)


def _store_field(fields: dict, key: str, value: str) -> None:
    """Record a field value; a repeated key collects its values into a list."""
    if key in fields:
        if not isinstance(fields[key], list):
            fields[key] = [fields[key]]
        fields[key].append(value)
    else:
        fields[key] = value


class MarkerGroupItem:
    """One item in a marker-grouped attribute run while it is being built: `marker`/`value`
    are the key that opened it and its raw value, `fields` the grouped keys that followed.
    A typed `MarkerGroup` converts it once complete (see `MarkerGroup.finalize`)."""

    def __init__(self, marker: str, value: str, span=None):
        self.marker = marker
        self.value = value
        self.span = span  # the marker line, for diagnostics on the shape type
        self.fields: dict[str, object] = {}
        self.field_spans: dict[str, object] = {}

    def __repr__(self):
        return f"<{self.marker}={self.value!r} {self.fields}>"


class MarkerGroup:
    """Partition an ordered run of sibling attributes into items by marker keys, for blocks
    with no `End` (SAGE's geometry): a marker key starts a new item and the grouped keys that
    follow write to it, so repeated keys aren't collapsed to their last value.

    `item` is the typed class each completed item becomes (via a `from_raw(game,
    MarkerGroupItem)` classmethod); the default keeps raw `MarkerGroupItem`s.
    """

    def __init__(self, markers, keys, item=MarkerGroupItem):
        self.markers = tuple(markers)
        self.keys = frozenset(keys)
        self.item = item

    def finalize(self, game, items: list) -> list:
        """Type the raw accumulators once their ordered run is fully read."""
        if self.item is MarkerGroupItem:
            return items
        return [self.item.from_raw(game, raw) for raw in items]


def classify_subblock(block: Block) -> tuple[str, type["IniObject"] | None]:
    """The type name and class of a child block, or (name, None) if untyped. A module-style
    header (`Behavior = AutoHealBehavior Tag`) names its type in the first label token; a
    named block is typed by the block name itself. A `Name = label` block whose first token is
    not a class but whose *name* is a `keyed_by_label` class (`ModelConditionState = DAMAGED`)
    is typed by the name, the label being its key rather than a class.

    The engine treats `=` as a skippable token, so `Behavior LifetimeUpdate Tag` (no `=`) is the
    same module slot as `Behavior = LifetimeUpdate Tag`. The `=`-less form is only read as a slot
    when the value token is a module *of that slot* (a subclass of the slot class); this keeps a
    name clash like `BuildingNugget SpawnArmy NuggetTag_*` (where `SpawnArmy` happens to match an
    unrelated definition class) typed as the `BuildingNugget` it is."""
    if block.uses_equals and block.label:
        first = block.label.split(maxsplit=1)[0]
        cls = REGISTRY.get(first)
        if cls is not None:
            return first, cls  # module slot: the first token names the class
        named = REGISTRY.get(block.name)
        if named is not None and named.keyed_by_label:
            return block.name, named  # label-keyed block: the name is the class
        return first, None  # unknown first token, not a keyed block: a typo or unmodeled
    if block.label:
        first = block.label.split(maxsplit=1)[0]
        cls = REGISTRY.get(first)
        slot = REGISTRY.get(block.name)
        if cls is not None and slot is not None and issubclass(cls, slot):
            return first, cls  # `=`-less module slot (`Behavior LifetimeUpdate Tag`)
    return block.name, REGISTRY.get(block.name)


class IniObject:
    key: str | None = None  # Game table this object registers into; None = unstored
    # Whether a label names a unique definition (last-wins) or a shared category that
    # legitimately repeats (a collection type like `AIBase`). The duplicate-definition lint
    # rule reads this to avoid flagging intended repeats.
    unique_name: bool = True
    # How many leading label tokens a header consumes: the name alone (`Object Foo`), or
    # name + parent for a `ChildObject`. Extra tokens on a non-`=` header are engine-ignored
    # leftovers, flagged by `validate`.
    header_arity: int = 1
    # Whether this block is typed by its *name* with the label as a key, not by the label's
    # first token as a class. `ModelConditionState = DAMAGED` is the `ModelConditionState`
    # class keyed by the condition `DAMAGED`, unlike a module slot (`Behavior = AutoHeal...`)
    # whose first token names the class. Read by `classify_subblock`.
    keyed_by_label: bool = False
    # Whether the `=` form of this block's header is engine-tolerated but wrong: the block
    # takes a plain `Block Tag` header, so a `Block = Tag` still parses (via keyed_by_label)
    # but the `=` does nothing and is flagged by the `spurious-block-label` rule.
    equals_is_spurious: bool = False
    # Whether digit-keyed fields (`1 = Command_X`, `2 = ...`) are a valid dynamic slot list on
    # this block (CommandSet/ButtonSet read them straight from `_fields`). Set so the
    # `unknown-attribute` coverage rule does not flag the numbered slots, which can never be
    # declared as Python annotations.
    numbered_slots: bool = False
    # The Game table the digit-keyed slots reference, when `numbered_slots` is on (CommandSet,
    # ButtonSet … list command buttons). The slots are dynamic, so no typed field carries them;
    # the cross-reference graph reads this to count `1 = Command_X` as an edge to the button,
    # without which every button only a command set names would read as unreferenced.
    numbered_slot_ref: str | None = None
    # Whether this block can be written as a bare one-line directive with no body or `End`
    # (`ClearNuggets`), not just the usual `Header ... End` form. The parser already keeps such a
    # name from opening a block (it is a bare value key); `from_block` then routes the resulting
    # bare attribute into the right nested group as a body-less instance of this class.
    bare_directive: bool = False
    # Real INI keys that are not valid Python identifiers (e.g. `HoleHealthRegen%PerSecond`),
    # mapped to the annotation that types them. A subclass declares these; the stored field is
    # renamed to the annotation on load, so conversion, attribute access and the coverage rule
    # all see one canonical name. Accumulated down the MRO into `_field_aliases`.
    field_aliases: dict[str, str] = {}
    _header_extras: tuple = ()
    _uses_equals: bool = False  # whether the header was written `Name = Label` (see from_block)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        REGISTRY[cls.__name__] = cls

        # Defaults written in the class body (`Cost: Int = 0`) would shadow __getattr__;
        # move them into _own_defaults and strip them so reads route through lazy conversion.
        own_annotations = cls.__dict__.get("__annotations__", {})
        own_defaults = {}
        for field in list(own_annotations):
            if field in cls.__dict__:
                own_defaults[field] = cls.__dict__[field]
                delattr(cls, field)
        cls._own_defaults = own_defaults

        fieldspec: dict[str, object] = {}
        defaults: dict[str, object] = {}
        nested: dict[str, list[str | type]] = {}
        groups: dict[str, MarkerGroup] = {}
        aliases: dict[str, str] = {}
        for base in reversed(cls.__mro__):
            fieldspec.update(getattr(base, "__annotations__", {}))
            defaults.update(base.__dict__.get("_own_defaults", {}))
            nested.update(base.__dict__.get("nested_attributes", {}))
            groups.update(base.__dict__.get("marker_groups", {}))
            aliases.update(base.__dict__.get("field_aliases", {}))
        # A nested or marker group may carry a `list[...]` annotation purely so the IDE knows
        # its element type; it's served by its own `__getattr__` branch, not lazy conversion,
        # so keep it out of the converter fieldspec (which other passes treat as raw fields).
        for grouped in nested.keys() | groups.keys():
            fieldspec.pop(grouped, None)
        cls._fieldspec = fieldspec
        cls._defaults = defaults
        cls._nested = nested
        cls._marker_groups = groups
        cls._field_aliases = aliases

        # Reverse maps for from_block: which group a key opens vs. extends.
        starts: dict[str, str] = {}
        members: dict[str, str] = {}
        for name, group in groups.items():
            for marker in group.markers:
                starts[marker] = name
            for key in group.keys:
                members[key] = name
        cls._marker_starts = starts
        cls._marker_members = members

    _fieldspec: dict[str, object] = {}
    _defaults: dict[str, object] = {}
    _nested: dict[str, list[str | type]] = {}
    _marker_groups: dict[str, MarkerGroup] = {}
    _marker_starts: dict[str, str] = {}
    _marker_members: dict[str, str] = {}
    _field_aliases: dict[str, str] = {}

    def __init__(
        self,
        name,
        game,
        fields,
        extras,
        nested_data=None,
        modules=None,
        span=None,
        field_spans=None,
        marker_grouped=None,
        field_span_lists=None,
    ):
        self.name = name
        self._game = game
        self._fields = fields
        self._extras = extras
        self._nested_data = nested_data if nested_data is not None else {}
        self._modules = modules if modules is not None else []
        self._marker_grouped = marker_grouped if marker_grouped is not None else {}
        self.span = span
        self._field_spans = field_spans if field_spans is not None else {}
        # Every occurrence's span for a key, in source order. `_field_spans` keeps only the
        # first; a repeated field (e.g. `RespawnEntry`) needs each line to land its own
        # diagnostic instead of stacking them all on the first entry.
        self._field_span_lists = field_span_lists if field_span_lists is not None else {}
        game.register(self)

    def field_spans(self, name) -> list:
        """Every span recorded for `name`, in source order — one per occurrence of a repeated
        key. Falls back to the single first-occurrence span, then the block span, so the result
        is never empty for a present field."""
        spans = self._field_span_lists.get(name)
        if spans:
            return list(spans)
        single = self._field_spans.get(name, self.span)
        return [single] if single is not None else []

    @property
    def extras(self) -> list:
        """Child nodes with no typed home (unknown sub-blocks, comments, ...)."""
        return self._extras

    @property
    def modules(self) -> list:
        """Typed sub-objects not claimed by a declared nested group."""
        return self._modules

    @property
    def fields(self) -> dict:
        """Raw, unconverted field values as read from the block."""
        return dict(self._fields)

    def numbered_slot_targets(self):
        """The registered objects this block's digit-keyed slots (`1 = Command_X`) reference,
        resolved through `numbered_slot_ref` (None when the block has no such slots). The
        cross-reference graph reads this so a command button a command set names counts as
        referenced; a slot naming nothing known is skipped."""
        if not self.numbered_slots or self.numbered_slot_ref is None:
            return
        for slot, name in self._fields.items():
            if not slot.isdigit() or not isinstance(name, str):
                continue
            obj, _ = self._game.lookup(self.numbered_slot_ref, name)
            if obj is not None:
                yield obj

    @classmethod
    def object_name(cls, block: Block) -> str:
        if block.label is None:
            return block.name
        # A `Type = ...` module header keeps its whole label (`Type Tag`); a `Keyword Name`
        # definition is named by its first token, the rest being leftovers.
        if block.uses_equals:
            return block.label
        tokens = _label_tokens(block.label)
        return tokens[0] if tokens else block.name

    @classmethod
    def header_extras(cls, block: Block) -> tuple:
        """Label tokens past the ones the header consumes (ignored by the engine). Only a
        registered definition names itself by its label, so only it has leftovers to flag."""
        if block.label is None or block.uses_equals or cls.key is None:
            return ()
        return tuple(_label_tokens(block.label)[cls.header_arity :])

    @classmethod
    def _group_for(cls, type_name: str, sub_cls: type, field_name: str | None = None) -> str | None:
        """The nested-group name a typed sub-block belongs to, or None. A `Field = Type` block
        whose field name is itself a declared group routes there first, so several fields can
        share one block type (e.g. `Radius`/`Opacity`/`Angle` all `FCurve`); otherwise the
        group is chosen by the block's type."""

        def allows(allowed) -> bool:
            for entry in allowed:
                if isinstance(entry, str):
                    if entry in (type_name, sub_cls.__name__):
                        return True
                elif issubclass(sub_cls, entry):
                    return True
            return False

        if field_name in cls._nested and allows(cls._nested[field_name]):
            return field_name
        for group, allowed in cls._nested.items():
            if allows(allowed):
                return group
        return None

    @classmethod
    def _bare_directive_group(cls, key: str) -> 'tuple[type["IniObject"], str] | None':
        """`(class, nested-group)` when `key` names a registered bare one-line directive block
        (`ClearNuggets`) that belongs to one of this block's nested groups, else None — so a
        body-less directive routes to the same group its `... End` form would."""
        directive_cls = REGISTRY.get(key)
        if directive_cls is None or not getattr(directive_cls, "bare_directive", False):
            return None
        group = cls._group_for(key, directive_cls, key)
        return (directive_cls, group) if group is not None else None

    @classmethod
    def from_block(cls, game, block: Block) -> "IniObject":
        fields: dict[str, object] = {}
        field_spans: dict[str, object] = {}
        field_span_lists: dict[str, list] = {}
        extras: list = []
        nested_data: dict[str, list] = {group: [] for group in cls._nested}
        marker_grouped: dict[str, list] = {group: [] for group in cls._marker_groups}
        modules: list = []
        for child in block.children:
            if isinstance(child, Attribute):
                # A non-identifier engine key (`HoleHealthRegen%PerSecond`) is renamed to the
                # field that types it; ordinary keys pass through unchanged. Aliased keys are
                # never marker keys, so this leaves the marker-group paths untouched.
                key = cls._field_aliases.get(child.key, child.key)
                group = cls._marker_starts.get(key)
                if group is not None:
                    marker_grouped[group].append(MarkerGroupItem(key, child.value, child.span))
                    continue
                group = cls._marker_members.get(key)
                if group is not None and marker_grouped[group]:
                    # A grouped key before its first marker falls through to flat storage.
                    item = marker_grouped[group][-1]
                    _store_field(item.fields, key, child.value)
                    item.field_spans.setdefault(key, child.span)
                    continue
                directive = cls._bare_directive_group(key)
                if directive is not None:
                    # A bare one-line directive block (`ClearNuggets`): build a body-less instance
                    # and route it into its nested group, the same place its `... End` form lands.
                    directive_cls, group = directive
                    nested_data[group].append(
                        directive_cls.from_block(
                            game,
                            Block(name=key, label=None, uses_equals=False, span=child.span),
                        )
                    )
                    continue
                _store_field(fields, key, child.value)
                field_spans.setdefault(key, child.span)
                field_span_lists.setdefault(key, []).append(child.span)
                continue
            if isinstance(child, Block):
                type_name, sub_cls = classify_subblock(child)
                if sub_cls is not None:
                    sub = sub_cls.from_block(game, child)
                    group = cls._group_for(type_name, sub_cls, child.name)
                    if group is not None:
                        nested_data[group].append(sub)
                    else:
                        modules.append(sub)
                    continue
            extras.append(child)
        for name, spec in cls._marker_groups.items():
            marker_grouped[name] = spec.finalize(game, marker_grouped[name])
        obj = cls(
            cls.object_name(block),
            game,
            fields,
            extras,
            nested_data,
            modules,
            span=block.span,
            field_spans=field_spans,
            marker_grouped=marker_grouped,
            field_span_lists=field_span_lists,
        )
        obj._header_extras = cls.header_extras(block)
        obj._uses_equals = block.uses_equals
        return obj

    def validate(self, diagnostics) -> None:
        """Drive lazy conversion of every present field, recording a bad value as a diagnostic
        instead of raising. Recurses into nested groups and modules."""
        if self._header_extras:
            extras = " ".join(self._header_extras)
            diagnostics.add(
                "extra-header-tokens",
                f"{type(self).__name__} {self.name!r} header has extra tokens {extras!r}; "
                "the engine names the object by the first token and ignores the rest",
                self.span,
                Severity.WARNING,
                extra={
                    "type": type(self).__name__,
                    "name": self.name,
                    "extras": list(self._header_extras),
                },
            )
        fieldspec = type(self)._fieldspec
        for name in fieldspec:
            if name not in self._fields:
                continue
            span = self._field_spans.get(name, self.span)
            self._game._pending_warnings.clear()
            try:
                getattr(self, name)
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                diagnostics.add(
                    "conversion-error",
                    f"{type(self).__name__}.{name}: {exc}",
                    span,
                    extra={"type": type(self).__name__, "field": name, "error": str(exc)},
                )
            else:
                for code, message, extra in self._game._pending_warnings:
                    diagnostics.add(
                        code,
                        f"{type(self).__name__}.{name}: {message}",
                        span,
                        Severity.WARNING,
                        extra={"type": type(self).__name__, "field": name, **extra},
                    )
            self._game._pending_warnings.clear()
        for items in self._nested_data.values():
            for item in items:
                item.validate(diagnostics)
        for items in self._marker_grouped.values():
            for item in items:
                if isinstance(item, IniObject):  # typed shapes; raw items have no fields to drive
                    item.validate(diagnostics)
        for module in self._modules:
            module.validate(diagnostics)

    @classmethod
    def convert(cls, game, value) -> Self:
        """Cross-reference: resolve a name to the registered instance."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str) and len(value.split()) > 1:
            # A scalar reference is a single token; the engine reads the first and ignores
            # the rest. Resolve the leading name and flag the remainder rather than fail.
            first = value.split()[0]
            warn = getattr(game, "warn", None)
            if warn is not None:
                warn(
                    "ignored-trailing-tokens",
                    f"{cls.__name__} reference {value!r} has trailing tokens; using {first!r}",
                    {"value": value, "used": first},
                )
            value = first
        obj, canonical = game.lookup(cls.key, value)
        if obj is None:
            hint, _ = suggestion_hint(value, game.tables.get(cls.key, {}))
            raise KeyError(f"no {cls.__name__} named {value!r}.{hint}")
        if canonical != value:
            warn = getattr(game, "warn", None)
            if warn is not None:
                warn(
                    "reference-case",
                    f"{cls.__name__} reference {value!r} should be {canonical!r} (case mismatch)",
                    {"given": value, "canonical": canonical, "key": cls.key},
                )
        return obj

    def __getattr__(self, name):
        # Only reached when normal lookup fails; internal/dunder names never route here.
        if name.startswith("_"):
            raise AttributeError(name)
        if name in type(self)._nested:
            return self._nested_data.get(name, [])
        if name in type(self)._marker_groups:
            return self._marker_grouped.get(name, [])
        fieldspec = type(self)._fieldspec
        if name not in fieldspec:
            raise AttributeError(name)
        if name not in self._fields:
            return self._defaults.get(name)
        converter = resolve_annotation(fieldspec[name])
        value = self._fields[name]
        # A scalar key written more than once keeps its last occurrence; container
        # converters consume the whole list.
        if isinstance(value, list) and not is_multivalued(converter):
            value = value[-1]
        return converter.convert(self._game, value)

    def __repr__(self):
        return f"<{type(self).__name__} {self.name}>"


class Module(IniObject):
    """A sub-object attached to an Object (behaviors, bodies, draws)."""

    key = None

    @property
    def tag(self) -> str | None:
        """The module's `ModuleTag_*` identifier — the second header token of
        `Behavior = AutoHealBehavior ModuleTag_01` — or None when the header omits it."""
        parts = self.name.split()
        return parts[1] if len(parts) > 1 else None


class NestedAttribute(IniObject):
    """A structured sub-block that is not a standalone game object."""

    key = None


class Nugget(NestedAttribute):
    """A weapon/effect payload component."""

    key = None


class Behavior(Module):
    key = None

    @property
    def trigger(self):
        if "SpecialPowerTemplate" in self._fields:
            return self.SpecialPowerTemplate
        if "TriggeredBy" in self._fields:
            return self.TriggeredBy
        return None


class Draw(Module):
    key = None

    # The model/animation state blocks a W3D draw module carries. Declared on the base so any
    # draw recognizes them; the concrete state classes live in `sage_ini.model.draw`.
    nested_attributes = {
        "DefaultModelConditionState": ["DefaultModelConditionState"],
        "ModelConditionState": ["ModelConditionState"],
        "ConditionState": ["ModelConditionState"],
        "DefaultConditionState": ["DefaultModelConditionState"],
        "AliasConditionState": ["ModelConditionState"],
        "DefaultAnimationState": ["DefaultAnimationState"],
        "IdleAnimationState": ["IdleAnimationState"],
        "AnimationState": ["AnimationState"],
        "TransitionState": ["TransitionState"],
        "LodOptions": ["LodOptions"],
    }
