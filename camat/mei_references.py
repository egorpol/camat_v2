"""Shared supported URI-pointer attributes for MEI checks and transformations.

This registry deliberately names pointer attributes rather than treating every
attribute as a reference. Full schema-aware URI and document resolution is a
separate validation layer; consumers of this registry currently handle local
fragment tokens.
"""

REFERENCE_ATTRS = frozenset({
    "facs", "startid", "endid", "target", "plist", "corresp", "sameas",
    "next", "prev", "copyof", "synch", "decls", "resp", "source",
})
