## ADDED Requirements

### Requirement: Level-based emoji prefix on console and UI logs

The logging layer SHALL prepend a level-based emoji to each log record rendered to the console handler and the UI ring-buffer handler. The mapping SHALL be `WARNING → ⚠️` and `ERROR`/`CRITICAL → 🚨`. Records at `INFO` and `DEBUG` levels SHALL NOT receive an emoji prefix.

#### Scenario: Warning record gets a warning emoji

- **WHEN** a logger emits a record at `WARNING` level whose message does not already begin with an emoji
- **THEN** the rendered console line and the UI ring-buffer entry begin with `⚠️` followed by the existing `levelname/name - message` format

#### Scenario: Error and critical records get an alarm emoji

- **WHEN** a logger emits a record at `ERROR` or `CRITICAL` level whose message does not already begin with an emoji
- **THEN** the rendered console line and the UI ring-buffer entry begin with `🚨`

#### Scenario: Info and debug records are unchanged

- **WHEN** a logger emits a record at `INFO` or `DEBUG` level
- **THEN** no emoji is prepended and the line keeps its current format

### Requirement: No duplicate emoji when message already has one

The formatter SHALL NOT prepend an emoji when the record's message already begins with an emoji, so that existing hand-typed emoji messages and startup lines render with exactly one leading emoji.

#### Scenario: Message already starts with an emoji

- **WHEN** a `WARNING` record's message already begins with an emoji (e.g. `⚠️ SLOW TICK ...`)
- **THEN** the formatter leaves the message as-is and does not add a second emoji

#### Scenario: Existing error emoji is preserved

- **WHEN** an `ERROR` record's message already begins with `❌` or another emoji
- **THEN** the formatter does not replace or duplicate it

### Requirement: JSON file logs remain free of injected emojis

The JSON file handler SHALL NOT have emojis injected by the formatter, preserving machine-readable logs where the level is carried by the `levelname` field.

#### Scenario: File log record stays structured

- **WHEN** any record at any level is written to the JSON file handler
- **THEN** the emitted JSON message field contains no formatter-injected emoji prefix
