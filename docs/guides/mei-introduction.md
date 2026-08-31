---
title: Introduction to MEI and XML
---

# Introduction to MEI and XML

The **Music Encoding Initiative (MEI)** is a framework for representing music
notation in a structured, machine-readable form. MEI is based on **XML**, so an
MEI file is a plain-text document with an explicit hierarchy.

For musicologists, this makes it possible to:

- describe notation precisely;
- document editorial decisions;
- process musical data computationally;
- validate encodings automatically;
- exchange data between tools and projects.

The [MEI Guidelines introduction](https://music-encoding.org/guidelines/v5/content/introduction.html)
is the official starting point. This guide first explains the smaller set of
ideas needed to read, write, and render a basic file.

## The very short version

You can think of the relationship like this:

- **music notation** is the thing we want to describe;
- **XML** is the language used to write that description;
- a **schema** is the rulebook that says what is allowed;
- **MEI** is a music-specific XML vocabulary.

MEI is therefore not just arbitrary XML. It is a specialized XML language for
music notation.

## What is XML?

XML stands for **eXtensible Markup Language**. For an absolute beginner, the
most useful definition is:

> XML is a way of writing structured information with labelled elements.

For example:

```xml
<note pname="c" oct="4" dur="4"/>
```

This says that:

- the element is called `note`;
- its pitch name is `c`;
- its octave is `4`;
- its written duration is `4`.

XML is built primarily from **elements** and **attributes**.

### Elements

Elements are named building blocks such as:

- `<measure>`;
- `<staff>`;
- `<layer>`;
- `<note>`;
- `<rest>`.

An element that contains other material has opening and closing tags:

```xml
<measure>
  ...
</measure>
```

An empty element can use a shorter form:

```xml
<note pname="c" oct="4" dur="4"/>
```

### Attributes

Attributes add information to an element:

```xml
<note pname="f" oct="5" dur="2"/>
```

Here, `pname` is the pitch name, `oct` is the octave, and `dur` is the
duration. A useful beginner distinction is:

- an **element** says what kind of thing this is;
- an **attribute** records information about that thing.

## What is a schema?

A **schema** is a set of rules for an XML language. It is like a grammar or
rulebook: it describes which elements are allowed, where they may occur, which
attributes they may carry, and which values are valid.

Schema validation can answer questions such as:

- Is a `<note>` allowed here?
- May this `<measure>` contain a `<staff>`?
- Is this attribute value part of the MEI vocabulary?
- Is required structural information missing?

Project-level consistency checks complement the schema by testing relationships
that a schema alone may not enforce, such as local publication rules or whether
every reference resolves to an existing `xml:id`.

Together, schema validation and consistency checks make encodings more
consistent, collaboration safer, and exchange between tools more reliable.
Within CAMAT, the [MEI consistency tools](../api/mei_consistency.md) provide
both the packaged MEI 5.1 CMN schema pass and additional editorial checks.

## How XML, MEI, and the schema fit together

MEI is an XML-based encoding framework whose rules are shared rather than
invented separately by every project:

- XML supplies the syntax;
- MEI supplies the music-specific elements and attributes;
- the schema checks whether the encoding conforms to the selected MEI model;
- project checks test additional editorial expectations.

## A simple MEI fragment

```xml
<measure n="1">
  <staff n="1">
    <layer n="1">
      <note pname="c" oct="4" dur="4"/>
      <note pname="d" oct="4" dur="4"/>
      <note pname="e" oct="4" dur="4"/>
      <note pname="f" oct="4" dur="4"/>
    </layer>
  </staff>
</measure>
```

Read this as one measure containing one staff, which contains one layer with
four notes.

## Basic musical hierarchy

A common beginner hierarchy inside a score is:

```text
score
└── section
    └── measure
        └── staff
            └── layer
                └── note / rest / chord / etc.
```

In simplified terms:

- `score` is the whole score representation;
- `section` groups a segment of the music;
- `measure` is one bar;
- `staff` identifies one staff in that measure;
- `layer` is one musical stream or voice on that staff;
- `note`, `rest`, or `chord` is an event in the layer.

## Score and staff definitions

Two important context-setting elements are `<scoreDef>` and `<staffDef>`. They
do not normally encode individual notes. Instead, they define the notational
environment:

- `scoreDef` holds settings that can apply to the score;
- `staffDef` holds settings for a particular staff.

They are commonly used for clefs, key signatures, meters, staff lines, labels,
and other staff properties. Their values often act like defaults that remain in
force until a later definition changes them.

## Basic notation in MEI

### Notes and pitch

In Common Music Notation, a basic pitched note can be described with three
attributes:

- `pname`: pitch name;
- `oct`: octave;
- `dur`: written duration.

```xml
<note pname="c" oct="4" dur="4"/>
```

This is a C4 quarter note. Another example:

```xml
<note pname="g" oct="5" dur="2"/>
```

This is a G5 half note.

### Accidentals

A written accidental can be encoded with `accid`:

```xml
<note pname="f" oct="4" dur="4" accid="s"/>
```

Here, `pname="f"` supplies the diatonic pitch name and `accid="s"` records a
written sharp.

### Duration

The `dur` attribute uses note-value denominators. Common values include:

| Value | Written duration |
| --- | --- |
| `1` | whole note |
| `2` | half note |
| `4` | quarter note |
| `8` | eighth note |

For example:

```xml
<note pname="a" oct="4" dur="8"/>
```

### Measures

Measures use the `<measure>` element:

```xml
<measure n="12">
  ...
</measure>
```

The `n` attribute carries the measure number or label. The measure contains the
musical material belonging to that bar.

### Staves and layers

Within a measure, notation is commonly organized through `<staff>` and
`<layer>`:

```xml
<measure n="1">
  <staff n="1">
    <layer n="1">
      <note pname="c" oct="4" dur="4"/>
    </layer>
  </staff>
</measure>
```

The staff number identifies the staff; the layer number identifies the musical
stream or voice on that staff.

### Key signatures

Key signatures are generally defined at score or staff level, often with the
`keysig` attribute:

```xml
<scoreDef keysig="1s"/>
```

Here, `1s` means one sharp. Similarly:

```xml
<scoreDef keysig="2f"/>
```

means two flats. The key signature applies to the following music until it is
changed.

### Meter

Meter is also normally defined in `<scoreDef>` or `<staffDef>`. The basic
attributes are `meter.count` for the upper number and `meter.unit` for the
lower number:

```xml
<scoreDef meter.count="4" meter.unit="4"/>
```

This means 4/4. Another example:

```xml
<scoreDef meter.count="3" meter.unit="8"/>
```

This means 3/8.

### Clefs and staff lines

Clefs are usually part of a score or staff definition:

```xml
<staffDef n="1" lines="5" clef.shape="G" clef.line="2"/>
```

This defines a normal five-line staff with a G clef on line 2. Including
`lines="5"` explicitly is useful in small standalone examples because some
rendering contexts should not be expected to infer the staff layout.

## Why `xml:id` matters

One of the most important attributes in MEI is `xml:id`. It gives an element a
unique identifier inside the document:

```xml
<note pname="g" oct="4" dur="4" xml:id="n42"/>
```

The note now has a stable identity. Other elements can point to that identity,
which is important for control events, annotations, facsimile alignment, and
analytical results.

### Linking a dynamic to a note

```xml
<measure n="10">
  <staff n="1">
    <layer n="1">
      <note pname="f" oct="4" dur="4"/>
      <note pname="g" oct="4" dur="4" xml:id="n10_2"/>
      <note pname="a" oct="4" dur="4"/>
      <note pname="c" oct="5" dur="4"/>
    </layer>
  </staff>

  <dynam startid="#n10_2">f</dynam>
</measure>
```

The second note has `xml:id="n10_2"`. The dynamic's
`startid="#n10_2"` points to that identifier; the `#` marks it as a reference
to an element within the document.

This mechanism is useful when:

- encoding slurs, ties, dynamics, and other control elements;
- linking notation to facsimile zones;
- attaching annotations;
- documenting editorial intervention;
- aligning musical data across tools;
- connecting an analytical result back to the score.

A note does not always require an `xml:id`, but a stable identifier becomes
essential as soon as another object must refer to that exact note. Systematic,
stable identifiers are therefore a strong default for editorial workflows.

## A fragment that brings the musical ideas together

The following example contains the core musical logic described above, but is
still only a score fragment:

```xml
<score>
  <scoreDef keysig="1s" meter.count="4" meter.unit="4"/>
  <section>
    <measure n="1">
      <staff n="1">
        <layer n="1">
          <note pname="g" oct="4" dur="4" xml:id="m1n1"/>
          <note pname="a" oct="4" dur="4" accid="s" xml:id="m1n2"/>
          <note pname="b" oct="4" dur="4" xml:id="m1n3"/>
          <note pname="c" oct="5" dur="4" xml:id="m1n4"/>
        </layer>
      </staff>
      <dynam startid="#m1n2">f</dynam>
    </measure>
  </section>
</score>
```

It includes a key signature, meter, one measure, one staff, one layer, four
notes, an accidental, stable identifiers, and a dynamic linked to a note. It
does not yet contain the full document wrapper expected by most MEI tools.

## The structure of a complete MEI file

A complete MEI document normally has a larger hierarchy around the score. It
helps to distinguish the **document level** from the **music level**:

```text
mei
├── meiHead
└── music
    └── body
        └── mdiv
            └── score
                ├── scoreDef
                └── section
                    └── measure
                        └── staff
                            └── layer
                                └── note / rest / chord / etc.
```

Read this as:

- `<mei>`: the whole document;
- `<meiHead>`: metadata about the document and its encoding;
- `<music>`: the musical content;
- `<body>`: the main musical body;
- `<mdiv>`: a musical division, such as a movement, act, or scene;
- `<score>`: the score representation;
- `<scoreDef>`: the opening notational context;
- `<section>`: a segment of music;
- `<measure>`, `<staff>`, and `<layer>`: the measured notation hierarchy;
- `<note>`, `<rest>`, or `<chord>`: musical events.

### A complete minimal example

```xml
<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1">
  <meiHead>
    <fileDesc>
      <titleStmt>
        <title>Minimal MEI example</title>
      </titleStmt>
      <pubStmt/>
    </fileDesc>
  </meiHead>

  <music>
    <body>
      <mdiv>
        <score>
          <scoreDef keysig="1s" meter.count="4" meter.unit="4">
            <staffGrp>
              <staffDef
                n="1"
                lines="5"
                clef.shape="G"
                clef.line="2"
              />
            </staffGrp>
          </scoreDef>

          <section>
            <measure n="1">
              <staff n="1">
                <layer n="1">
                  <note pname="g" oct="4" dur="4" xml:id="m1n1"/>
                  <note pname="a" oct="4" dur="4" accid="s" xml:id="m1n2"/>
                  <note pname="b" oct="4" dur="4" xml:id="m1n3"/>
                  <note pname="c" oct="5" dur="4" xml:id="m1n4"/>
                </layer>
              </staff>
              <dynam startid="#m1n2">f</dynam>
            </measure>
          </section>
        </score>
      </mdiv>
    </body>
  </music>
</mei>
```

Compared with the fragment, this example adds:

- `<mei>` as the document root;
- the MEI XML namespace in `xmlns`;
- `meiversion` to identify the MEI version;
- `<meiHead>` for metadata;
- `<music>`, `<body>`, and `<mdiv>` around the score;
- `<staffGrp>` and `<staffDef>` to describe the staff.

### The role of `meiHead`

The `<meiHead>` contains metadata about the encoded object and the encoding. It
can record, for example:

- title and source information;
- editorial responsibility;
- encoding notes;
- revision history.

A teaching example may have a very short header. A research edition can use a
much richer one.

### The role of `body` and `mdiv`

The `<body>` contains the main musical content. Within it, `<mdiv>` represents
a large musical division such as a whole piece, movement, act, or scene. One
`<mdiv>` is normally sufficient for a small standalone example.

## A practical beginner rule

When writing MEI for testing or rendering, build the hierarchy in this order:

1. Start with `<mei>`.
2. Add `<meiHead>`.
3. Add `<music>`.
4. Inside `<music>`, add `<body>`.
5. Inside `<body>`, add `<mdiv>`.
6. Inside `<mdiv>`, add `<score>`.
7. Inside `<score>`, add `<scoreDef>` and `<section>`.
8. Inside `<section>`, add measures, staves, layers, and events.

This prevents a useful score fragment from being mistaken for a complete MEI
document.

## Memory aid

- **MEI document** = metadata + music;
- **music** = body + divisions + score content;
- **score content** = definitions + sections + measures + staves + layers + events.

## Try and check the example

Open [`mei_render.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_render.ipynb),
replace the example text with your own MEI, and select **Render MEI**. Use the
score zoom controls to enlarge the notation without rendering again. The
notebook uses the same packaged Verovio helpers as the rest of CAMAT and lets
you switch between rendered pages without leaving Jupyter.

When a clean MEI corresponds to a BSB source page, continue with
[`mei_single_file_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_single_file_iiif_integration.ipynb)
for one file, or
[`mei_batch_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_batch_iiif_integration.ipynb)
for several pages.

Rendering is a useful feedback loop, but a score that renders is not
necessarily valid or editorially consistent. Continue with
[Handling MEI files](edition-building.md#check-combine-and-review-reports) for schema
and consistency checks, or use the
[Verovio Editor](https://editor.verovio.org/) as an external rendering tool.
