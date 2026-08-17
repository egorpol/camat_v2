
* [x] Move `convert_sources(...)` out of a file named `scripts/test_...` into a supported `camat.conversion` API and proper CLI.
* [x] Add resumable conversion: skip an output when source hash, route, options, and tool versions are unchanged.
* [x] Record music21/MuseScore versions, conversion duration, final redirected URL, and Verovio options alongside the existing hashes.
* [x] Add download preflight controls: streaming, maximum file size, content-type checks, and clearer download/parse/export failure categories.
* [x] Keep validation explicitly layered: downloaded → converted → valid MEI → rendered → parsed by CAMAT → editorially inspected.
