"""Duplicate-chunk detection: find ini content repeated verbatim in two or more places,
worth extracting into a shared `#include` file. Two detectors run over the parsed AST:

- whole blocks: any `Block` or `ScriptBlock` (top-level `Object` or nested `Behavior`
  module alike) whose normalized form appears at 2+ places;
- sibling runs: maximal contiguous runs of sibling nodes (attributes, macro defs, nested
  blocks) repeated across block bodies - the classic shape a shared `.inc` factors out.

Matching is exact modulo formatting: two chunks match iff their canonical printed text is
identical after dropping comments and blank lines (the parser already collapses whitespace).
All sizes and thresholds are measured in those normalized lines. Spans always point at the
original source.

Documented limitations: matching is textual, so bodies that differ only in a label or
ModuleTag (`Behavior = ActiveBody ModuleTag_07`) never match (a label-insensitive mode is
future work), and a matched chunk that reads a macro `#define`d differently at each site is
flagged even though its meaning differs - the report is a candidate list, not a proof. A run
never crosses an `#include`: already-factored content is left alone.
"""

from collections import defaultdict
from dataclasses import dataclass, replace

from sage_ini.parser.ast import (
    BlankLine,
    Block,
    Comment,
    Include,
    IniDocument,
    Node,
    ScriptBlock,
    line_count,
)
from sage_ini.parser.location import Span
from sage_ini.parser.printer import print_nodes
from sage_ini.walk import walk_nodes

__all__ = ["Cluster", "canonical_text", "find_duplicates", "normalize_nodes"]

# Refinement stops extending a run past this many nodes: bounds the pathological case of
# very long identical sibling sequences without affecting real findings (a run this size
# is reported anyway, just not grown further).
MAX_RUN_TOKENS = 2000


def normalize_nodes(nodes: list[Node]) -> list[Node]:
    """The comparison form of a node list: comments and blank lines dropped (including
    trailing comments on kept nodes), recursively. Spans are preserved, so a normalized
    tree still reports original source positions."""
    normalized: list[Node] = []
    for node in nodes:
        if isinstance(node, (Comment, BlankLine)):
            continue
        if isinstance(node, Block):
            node = replace(
                node, comment=None, end_comment=None, children=normalize_nodes(node.children)
            )
        elif isinstance(node, ScriptBlock):
            node = replace(node, comment=None, end_comment=None)
        else:
            node = replace(node, comment=None)
        normalized.append(node)
    return normalized


def canonical_text(nodes: list[Node]) -> str:
    """The normalized canonical text of a node list - the key duplicate detection matches on."""
    return print_nodes(normalize_nodes(nodes))


@dataclass(frozen=True, slots=True)
class Cluster:
    """One duplicated chunk and everywhere it occurs. `lines` is the normalized size of a
    single occurrence; `snippet` its canonical text."""

    kind: str  # "block" | "run"
    title: str  # "Object GondorFighter" | "run of 7 nodes"
    snippet: str
    lines: int
    occurrences: tuple[Span, ...]

    @property
    def saved_lines(self) -> int:
        """Lines removed by extracting: the copies collapse to one shared body plus one
        `#include` line per occurrence."""
        count = len(self.occurrences)
        return max(0, self.lines * (count - 1) - count)


class _Interner:
    """Maps a node's canonical text to a small token id, remembering each token's text and
    normalized line count so runs can be sized and rendered without re-printing."""

    def __init__(self):
        self._ids: dict[str, int] = {}
        self.texts: list[str] = []
        self.lines: list[int] = []

    def intern(self, node: Node) -> int:
        text = print_nodes([node])
        token = self._ids.get(text)
        if token is None:
            token = len(self.texts)
            self._ids[text] = token
            self.texts.append(text)
            self.lines.append(line_count([node]))
        return token


def find_duplicates(
    documents: list[IniDocument], *, min_lines: int = 10, min_occurrences: int = 2
) -> list[Cluster]:
    """Duplicate clusters across `documents`, largest saving first. A cluster is dropped
    when every one of its occurrences already lies inside a bigger reported one, so nested
    blocks of a duplicated parent and sub-runs of a longer run are not re-reported."""
    normalized = [replace(doc, children=normalize_nodes(doc.children)) for doc in documents]
    interner = _Interner()
    candidates = _block_candidates(normalized, interner, min_lines, min_occurrences)
    candidates += _run_candidates(normalized, interner, min_lines, min_occurrences)
    return _select(candidates)


def _block_title(node: Block | ScriptBlock) -> str:
    if isinstance(node, ScriptBlock):
        return "script block"
    return f"{node.name} {node.label}".strip() if node.label else node.name


def _block_candidates(
    documents: list[IniDocument], interner: _Interner, min_lines: int, min_occurrences: int
) -> list[Cluster]:
    """Whole-node duplicates: every `Block`/`ScriptBlock` at any depth, grouped by
    canonical text."""
    groups: dict[int, list[Span]] = defaultdict(list)
    titles: dict[int, str] = {}
    for document in documents:
        for node in walk_nodes(document):
            if not isinstance(node, (Block, ScriptBlock)):
                continue
            if line_count([node]) < min_lines:
                continue
            token = interner.intern(node)
            groups[token].append(node.span)
            titles.setdefault(token, _block_title(node))
    clusters = []
    for token, spans in groups.items():
        if len(spans) < min_occurrences:
            continue
        spans.sort(key=lambda span: (span.file, span.line_start))
        clusters.append(
            Cluster(
                kind="block",
                title=titles[token],
                snippet=interner.texts[token],
                lines=interner.lines[token],
                occurrences=tuple(spans),
            )
        )
    return clusters


def _run_candidates(
    documents: list[IniDocument], interner: _Interner, min_lines: int, min_occurrences: int
) -> list[Cluster]:
    """Maximal duplicated runs of 2+ sibling nodes. Every sibling sequence (a document's or
    block's children) is tokenized - an `#include` becomes a never-matching barrier - and the
    sequences are concatenated with unique separators so repeats never cross a boundary."""
    tokens: list[int] = []
    spans: list[Span | None] = []
    barrier = -1
    for document in documents:
        sequences = [document.children]
        for node in walk_nodes(document):
            if isinstance(node, Block):
                sequences.append(node.children)
        for sequence in sequences:
            for node in sequence:
                if isinstance(node, Include):
                    tokens.append(barrier)
                    spans.append(None)
                    barrier -= 1
                else:
                    tokens.append(interner.intern(node))
                    spans.append(node.span)
            tokens.append(barrier)
            spans.append(None)
            barrier -= 1

    clusters = []
    for positions, length in _maximal_repeats(tokens):
        if length < 2:  # single-node duplicates are the whole-block detector's job
            continue
        lines = sum(interner.lines[tokens[positions[0] + offset]] for offset in range(length))
        if lines < min_lines:
            continue
        occurrences = _non_overlapping(sorted(positions), length, spans)
        if len(occurrences) < min_occurrences:
            continue
        occurrences.sort(key=lambda span: (span.file, span.line_start))
        snippet = "".join(interner.texts[tokens[positions[0] + offset]] for offset in range(length))
        clusters.append(
            Cluster(
                kind="run",
                title=f"run of {length} sibling nodes",
                snippet=snippet,
                lines=lines,
                occurrences=tuple(occurrences),
            )
        )
    return clusters


def _maximal_repeats(tokens: list[int]) -> list[tuple[list[int], int]]:
    """Every maximal repeat in `tokens` as (start positions, length): extending any reported
    repeat one token left or right breaks at least one occurrence. Negative tokens never
    match anything. Top-down class refinement: seed with the positions of each token, extend
    right while all occurrences agree, report when left-maximal (a left-extension of the
    whole class is found from the earlier seed instead), then split by the next token and
    refine each sub-class."""
    seeds: dict[int, list[int]] = defaultdict(list)
    for index, token in enumerate(tokens):
        if token >= 0:
            seeds[token].append(index)
    stack = [(positions, 1) for positions in seeds.values() if len(positions) >= 2]
    repeats = []
    size = len(tokens)
    while stack:
        positions, length = stack.pop()
        while length < MAX_RUN_TOKENS:
            following = {tokens[p + length] if p + length < size else -1 for p in positions}
            if len(following) == 1 and next(iter(following)) >= 0:
                length += 1
            else:
                break
        preceding = {tokens[p - 1] if p > 0 else -1 for p in positions}
        if not (len(preceding) == 1 and next(iter(preceding)) >= 0):
            repeats.append((positions, length))
        if length >= MAX_RUN_TOKENS:
            continue
        splits: dict[int, list[int]] = defaultdict(list)
        for p in positions:
            if p + length < size and tokens[p + length] >= 0:
                splits[tokens[p + length]].append(p)
        for group in splits.values():
            if len(group) >= 2:
                stack.append((group, length + 1))
    return repeats


def _non_overlapping(positions: list[int], length: int, spans: list[Span | None]) -> list[Span]:
    """Occurrence spans for a repeat, greedily skipping starts that overlap the previously
    kept occurrence (tandem repeats count each full period once)."""
    occurrences = []
    next_free = 0
    for p in positions:
        if p < next_free:
            continue
        first, last = spans[p], spans[p + length - 1]
        assert first is not None and last is not None
        occurrences.append(first.merge(last))
        next_free = p + length
    return occurrences


def _select(candidates: list[Cluster]) -> list[Cluster]:
    """Largest-saving-first selection with containment suppression: a candidate is kept
    unless every occurrence lies wholly inside an occurrence of an already-kept cluster."""
    candidates.sort(
        key=lambda c: (
            -c.saved_lines,
            c.kind != "block",
            c.title,
            c.occurrences[0].file,
            c.occurrences[0].line_start,
        )
    )
    kept: list[Cluster] = []
    covered: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for cluster in candidates:
        contained = all(
            any(
                start <= span.line_start and span.line_end <= end
                for start, end in covered[span.file]
            )
            for span in cluster.occurrences
        )
        if contained:
            continue
        kept.append(cluster)
        for span in cluster.occurrences:
            covered[span.file].append((span.line_start, span.line_end))
    return kept
