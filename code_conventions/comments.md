# Comment Writing Conventions

## 1. Goal

Comments should help someone understand the code the first time they read it.
The goal is not to make comments longer. The goal is to explain what an
object, method, or rule function actually does.

Comments must prioritize understanding:

- what the object or method represents
- what information it contains
- what work it performs
- how each argument affects the logic
- what the returned value looks like
- what happens when an input is missing or cannot be parsed

## 2. General Principle

Write comments in the language of the code interface, not in the language of
an architecture status report.

Prefer concrete descriptions such as:

- fetch package information
- select a bounded shortlist
- fetch detail for each selected version
- normalize raw responses into package and candidate records

Avoid abstract phrases such as:

- `build evidence block`
- `prepare planning input`
- `expand metadata record`
- `visible versions`

Do not use a term unless the current code context defines it clearly.

## 3. Class Docstrings

A class docstring should first answer: "What kind of object is this?"

Then explain what information the object contains. Use this structure:

1. Define the object's role in one direct sentence.
2. List the information carried by the object in two to four lines.
3. Add a short example.

Recommended:

```python
"""Input object for one package metadata lookup.

It tells the metadata service:
- which package to inspect
- why it was selected
- what the current workspace already knows about its constraint and version

Example:
    Inspect `custom_lint` because it directly depends on `analyzer`, the
    workspace currently constrains it to `^0.6.0`, and the currently resolved
    version is `0.6.4`.
"""
```

Avoid:

```python
"""One package request that will be expanded into metadata evidence."""
```

This is too abstract. The reader still does not know what information the
object contains.

## 4. Method Docstrings

Use this order by default:

1. State what the method actually does.
2. If the method has several steps, list one to four concrete actions.
3. Document `Args`.
4. Document `Returns`.
5. Add an `Example`.

Recommended:

```python
"""Build normalized package metadata from registry data and shortlist results.

This method:
1. fetches package-level registry info for each requested package
2. selects a bounded shortlist from the versions returned by the
   hosted Dart pub package endpoint
   (currently the official `pub.dev` API:
   `GET https://pub.dev/api/packages/{package}`)
3. fetches detail for each shortlisted version
4. converts the raw registry payloads into stable package/candidate
   metadata records

Args:
    ...

Returns:
    ...

Example:
    ...
"""
```

## 5. Documenting Arguments

Do not repeat only the type or variable name. Explain:

- the argument's domain meaning
- how the method uses it
- what happens when it is omitted, empty, or unparsable
- a short example when it makes the rule easier to understand

Avoid:

```python
current_version: Currently used package version.
```

Prefer:

```python
current_version: Currently used package version. When present, the
    selector can choose the latest stable version within the current
    major line and the nearest higher-major candidate. For example,
    `1.2.0` means "current major line is 1.x". When omitted or
    unparsable, the selector falls back to only the global latest
    stable version because it has no reliable current-major baseline.
```

## 6. Documenting Return Values

For a simple scalar, explain the returned meaning directly.

For a nested structure, explain the hierarchy before listing fields. State
which record contains which nested records.

Recommended:

```python
Returns:
    Top-level metadata grouped by package.

    The returned structure has two nested levels:

    1. package record
       One package record represents one inspected package. It explains
       why that package was queried and contains the candidate list for
       that package.

       Fields:
       - `package`
       - `selectionReason`
       - `currentConstraint`
       - `targetDependency`
       - `targetConstraint`
       - `candidates`

    2. candidate record
       One candidate record represents one specific shortlisted
       version inside that package.

       Fields:
       - `version`
       - `published`
       - `isPrerelease`
       - `sdkConstraint`
       - `targetDependencyConstraint`
       - `dependencies`
       - `compatibilityVerdict`
       - `rejectionReason`
```

Do not list fields without explaining their containment relationship.

## 7. Private Method Docstrings

Private methods should also have docstrings when they carry explicit rules.
This especially applies to:

- rule evaluation functions
- constraint parsers
- candidate selectors
- helpers that affect edge-case behavior

Document what the method does, its arguments, its return value, and a short
example.

Recommended:

```python
"""Return the latest stable candidate from the nearest higher major.

Args:
    stable_versions: Parsed stable versions keyed by `Version`.
    current_major: Current workspace major line used as the baseline.

Returns:
    The newest stable candidate from the closest higher major line, or
    `None` when no higher major exists.

Example:
    Versions `1.4.0`, `2.2.0`, `3.1.0` with `current_major=1` return
    `2.2.0`, not `3.1.0`, because `2.x` is the nearest higher line.
"""
```

## 8. Practices to Avoid

### Do not use undefined terms

Avoid phrases such as:

- `visible versions`
- `metadata evidence`
- `consumer near conflict target`

Replace them with facts expressed by the current code, such as:

- `versions returned by GET /api/packages/{package}`
- `package directly depending on analyzer`

### Do not describe future orchestration

Do not document a current method only from the perspective of a later
iteration.

Avoid:

- `consumed by the planning loop`
- `used by later orchestration`
- `prepared for later LLM use`

If the current implementation does not perform that work, the comment will
mislead the reader.

### Do not use abstract purpose labels instead of actions

Avoid:

- `build evidence`
- `prepare metadata`
- `expand request`

Prefer:

- fetch package info
- select shortlist
- fetch version detail
- normalize package and candidate records

## 9. Review Checklist

When adding similar code:

1. Write docstrings for objects and methods that carry non-obvious behavior.
2. Include a short example.
3. For complex return values, explain hierarchy before listing fields.
4. Explain how missing, empty, or unparsable arguments affect behavior.
5. Add docstrings for private methods that encode explicit rules.
6. Use terms defined by the current code context.
7. Describe current behavior, not speculative future usage.

## 10. Summary

Comments should read like documentation, but they must remain grounded in the
facts of the current code.
