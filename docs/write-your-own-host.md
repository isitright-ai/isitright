# Write your own host

!!! warning "Experimental"
    The extension interfaces are public but may change until a pack has been written by someone other than its author. This page describes what the 0.6 data pack and the example below rely on.

A host makes a world available to the thing under test and says how faithfully. The shape fits any tool that takes files in and writes a table out: a statistics package, a command-line converter, a scientific program. The example in [`examples/hosts/table_cli/`](https://github.com/isitright-ai/isitright/tree/main/examples/hosts/table_cli) wraps a small command-line analysis program (a stand-in for a package such as SPSS). It imports only from `isitright.core`.

## What you provide

1. **An entity schema and a world spec.** Collections, typed fields, keys, and the domain rules that make a changed state valid.

    ```python
    from isitright.core.entities import CollectionSpec, EntitySchema, FieldSpec
    from isitright.core.constraints import Range
    from isitright.core.spec import WorldSpec

    SCHEMA = EntitySchema(collections=[CollectionSpec(
        name="sales", key="id",
        fields=[FieldSpec(name="id", type="int"),
                FieldSpec(name="region", type="text"),
                FieldSpec(name="amount", type="float", nullable=True)])])
    SPEC = WorldSpec(id="sales", schema=SCHEMA,
                     constraints=[Range(path="sales.amount", min=0, max=1000)])
    ```

2. **A host.** An object with a `fidelity` and a `prepare(spec, world)` context manager that loads the state into whatever the tool reads and yields a handle to run it. The example writes the entities to `data.csv` in a temporary directory and yields a handle whose `run()` starts the program and reads `out.csv`.

    ```python
    class CliTableHost:
        fidelity = Fidelity.NATIVE_ISOLATED

        @contextmanager
        def prepare(self, spec, world):
            with tempfile.TemporaryDirectory() as scratch:
                ...  # write world.state.entities("sales") to scratch/data.csv
                yield Prepared(Path(scratch), self.command)
    ```

3. **An oracle.** Here a reference function that recomputes the right table from the state, compared with a core comparator (`NumericComparator` states its tolerance and the basis for it).

4. **Hints** that tell the search which collections and fields matter (`scope`, `column`, and the other kinds in `isitright.core.hints`).

## What you get

`search` visits worlds from the core's mutation families in priority order, validating each against your rules, and calls your `evaluate` function. `minimize_world` shrinks a disagreeing world to the fewest rows that still disagree. `ReplayArtifact` and the report classes record the result. The example's whole audit is one function:

```python
found = search(SPEC, base, HINTS, default_mutators(), evaluate, budget=Budget(attempts=200))
minimized = minimize_world(SPEC, found.findings[0].candidate.world, base.state,
                           disagrees, referenced=["sales"])
```

On the example, a program with a truncating mean (`--integer-mean`) is found and shrinks to three rows or fewer. The same program without the defect is not found in 200 worlds, which is not a statement that it is correct.

## What to decide

- **Fidelity.** `NATIVE_ISOLATED` means the real tool in a separate process. Say less if you emulate it.
- **Where the program runs.** If you run code you did not write, use a separate process with a timeout and read the data pack's host (`isitright/packs/data/host.py`) for the limits and for what they do not protect against.
- **Null and type conventions.** Decide how a missing value is written and read back, and test it at each boundary.
- **The oracle's limits.** A reference program is an implementation. Report where it can be wrong.
