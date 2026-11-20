"""MEI editorial container branch selection (``choice`` / ``app`` / ``subst``).

Stdlib-only internal helper. Not exported from ``camat.__init__``.

Default selection matches Verovio 6.3.0 when the corresponding XPath queries
are empty (``choiceXPathQuery`` / ``appXPathQuery`` / ``substXPathQuery``):

* ``<choice>`` / ``<subst>``: first child element in document order
* ``<app>``: first ``<lem>`` direct child if present, else first ``<rdg>``,
  else first child element

On schema-valid MEI 5.1 (``<lem>?`` then ``<rdg>+``), CAMAT and Verovio 6.3.0
agree because ``<lem>`` precedes any ``<rdg>``. CAMAT additionally prioritizes
``<lem>`` over ``<rdg>`` even when a noncanonical document puts ``<rdg>``
first; Verovio 6.3.0 with an empty ``appXPathQuery`` would take the first
recognized child in document order.

Reading wrappers (``sic``, ``corr``, ``lem``, ``rdg``, ``supplied``, …) are
expanded only when they are the selected branch of a ``choice`` / ``app`` /
``subst``. Standalone wrappers outside those containers are left intact.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Optional, Set

EDITORIAL_CONTAINERS = frozenset({"choice", "app", "subst"})

# Transparent reading / transcription wrappers that may sit between an
# editorial container and the selected musical content. Expanded only when
# reached as the selected branch of choice/app/subst — never standalone.
EDITORIAL_READING_WRAPPERS = frozenset(
    {
        "lem",
        "rdg",
        "sic",
        "corr",
        "orig",
        "reg",
        "abbr",
        "expan",
        "add",
        "del",
        "supplied",
        "unclear",
        "damage",
        "restore",
        "gap",
    }
)


def _local_name(tag: Any) -> str:
    raw = str(tag)
    return raw.rsplit("}", 1)[-1] if "}" in raw else raw


def _direct_element_children(el: Any) -> list[Any]:
    children: list[Any] = []
    for child in list(el):
        tag = getattr(child, "tag", None)
        if tag is None or callable(tag):
            continue
        children.append(child)
    return children


def select_editorial_branch(el: Any) -> Optional[Any]:
    """Return the selected direct child of a choice/app/subst, or ``None``."""
    name = _local_name(getattr(el, "tag", ""))
    children = _direct_element_children(el)
    if not children:
        return None
    if name == "app":
        for child in children:
            if _local_name(child.tag) == "lem":
                return child
        for child in children:
            if _local_name(child.tag) == "rdg":
                return child
        return children[0]
    if name in {"choice", "subst"}:
        return children[0]
    return None


def _expand_selected_branch(branch: Any) -> Iterator[Any]:
    """Expand one selected editorial branch tip to visible content elements."""
    tag = _local_name(getattr(branch, "tag", ""))
    if tag in EDITORIAL_CONTAINERS:
        yield from _expand_selected(branch)
        return
    if tag in EDITORIAL_READING_WRAPPERS:
        for child in _direct_element_children(branch):
            yield from _expand_selected(child)
        return
    yield branch


def _expand_selected(el: Any) -> Iterator[Any]:
    """Expand a direct child: unwrap editorial containers only."""
    tag = _local_name(getattr(el, "tag", ""))
    if tag in EDITORIAL_CONTAINERS:
        selected = select_editorial_branch(el)
        if selected is not None:
            yield from _expand_selected_branch(selected)
        return
    yield el


def iter_selected_children(el: Any) -> Iterator[Any]:
    """Yield direct children with ``choice`` / ``app`` / ``subst`` expanded."""
    for child in _direct_element_children(el):
        yield from _expand_selected(child)


def unselected_editorial_element_ids(root: Any) -> Set[int]:
    """Return ``id()`` values of every element inside an unselected branch.

    Covers all descendants of every non-selected direct child of ``<choice>``,
    ``<app>``, and ``<subst>``, including nested editorial containers.
    """
    unselected: Set[int] = set()

    def mark_subtree(el: Any) -> None:
        unselected.add(id(el))
        for child in _direct_element_children(el):
            mark_subtree(child)

    def walk(el: Any) -> None:
        tag = _local_name(getattr(el, "tag", ""))
        if tag in EDITORIAL_CONTAINERS:
            selected = select_editorial_branch(el)
            for child in _direct_element_children(el):
                if selected is not None and child is selected:
                    walk(child)
                else:
                    mark_subtree(child)
            return
        for child in _direct_element_children(el):
            walk(child)

    if root is not None:
        walk(root)
    return unselected


def selected_itertext(el: Any, unselected: Optional[Set[int]] = None) -> str:
    """Collect element text while skipping unselected editorial descendants.

    Preserves ``el.text``, text/tails of selected descendants, and the ``.tail``
    of skipped (unselected) elements when that tail belongs to the surrounding
    selected context. The editorial container's own ``.tail`` is not part of
    this element's text content (callers that walk siblings see it separately).
    """
    if el is None:
        return ""
    skip = unselected if unselected is not None else unselected_editorial_element_ids(el)
    parts: list[str] = []

    def walk(node: Any, *, include_tail: bool) -> None:
        if id(node) in skip:
            # Tail after an unselected element still belongs to the parent context.
            if include_tail and node.tail:
                parts.append(node.tail)
            return
        if node.text:
            parts.append(node.text)
        for child in list(node):
            tag = getattr(child, "tag", None)
            if tag is None or callable(tag):
                if getattr(child, "tail", None):
                    parts.append(child.tail)
                continue
            walk(child, include_tail=True)
        if include_tail and node.tail:
            parts.append(node.tail)

    walk(el, include_tail=False)
    return "".join(parts)


def iter_selected_elements(root: Any, *, local_names: Optional[Iterable[str]] = None) -> Iterator[Any]:
    """Document-order walk over elements outside unselected editorial branches."""
    unselected = unselected_editorial_element_ids(root)
    wanted = None if local_names is None else frozenset(local_names)
    for el in root.iter():
        tag = getattr(el, "tag", None)
        if tag is None or callable(tag):
            continue
        if id(el) in unselected:
            continue
        if wanted is not None and _local_name(tag) not in wanted:
            continue
        yield el


def resolve_editorial_containers_in_tree(root: Any) -> bool:
    """Replace ``choice`` / ``app`` / ``subst`` with selected branch children in-place.

    Returns True if any container was resolved. Selected elements keep their
    ``xml:id`` attributes. Reading wrappers around selected content are also
    unwrapped so consumers see the musical elements directly. Files without
    editorial containers are left untouched (returns False).
    """
    changed = False

    def _append_text(parent: Any, index: int, text: str) -> None:
        if not text:
            return
        if index > 0:
            prev = parent[index - 1]
            prev.tail = (prev.tail or "") + text
        else:
            parent.text = (parent.text or "") + text

    def process(parent: Any) -> None:
        nonlocal changed
        index = 0
        while index < len(parent):
            child = parent[index]
            tag = getattr(child, "tag", None)
            if tag is None or callable(tag):
                index += 1
                continue
            # Resolve nested containers first (deepest editorial wins cleanly).
            process(child)
            if _local_name(tag) not in EDITORIAL_CONTAINERS:
                index += 1
                continue
            changed = True
            selected = select_editorial_branch(child)
            container_tail = child.tail or ""
            leading_text = ""
            insert_nodes: list[Any] = []
            if selected is not None:
                sel_name = _local_name(selected.tag)
                if sel_name in EDITORIAL_READING_WRAPPERS:
                    leading_text = selected.text or ""
                    insert_nodes = list(selected)
                else:
                    insert_nodes = [selected]
            parent.remove(child)
            for offset, node in enumerate(insert_nodes):
                parent.insert(index + offset, node)
            if insert_nodes:
                if leading_text:
                    _append_text(parent, index, leading_text)
                insert_nodes[-1].tail = (insert_nodes[-1].tail or "") + container_tail
                index += len(insert_nodes)
            else:
                _append_text(parent, index, leading_text + container_tail)

    process(root)
    return changed
