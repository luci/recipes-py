# TurboCI in Recipes

[TOC]

This is a short guide for Recipes/TurboCI integration.

## What is TurboCI?

TurboCI is an internal CI orchestration service designed and built to support
the continuous integration needs of Chromium, Android and other Open Source
projects.

Its protobuf interface is defined in the [turboci/proto] repo.

*** note
As of 2025Q3, there is no production-worthy public implementation of this
service - however, there is a fully in-memory fake implementation built into
Recipes.
***

TurboCI is designed around a couple core concepts:

TurboCI workflows can be modeled as a [graph] where the nodes are data and
actions taken as part of the workflow, and the edges represent dependency
relationships between those things.

TurboCI includes two node types with distinct purposes:
  * `Checks` - These nodes represent work that needs to be done by the workflow,
    along with the results of executing that work. Checks may have dependencies
    on other Checks, which indicate results which must be available before it
    makes sense to process this Check (e.g. a test would need the output
    binaries from a build in order for something to start generating results for
    that test). Checks are coarsely categorized into 'kinds':
    * `SOURCE` checks represent source data for the rest of the workflow to
      consume. Sources typically will be from e.g. git repos, but could also
      encompass raw data fetched from elsewhere, static text, or other sorts of
      source control systems.
    * `BUILD` checks represent a transformation of sources into some consumable
      (usually executable) product like binaries or into source archives (like
      python wheels). `BUILD` checks typically depend on one or more `SOURCE`
      checks that tell them what source(s) to build.
    * `TEST` checks represent the execution of some executable payload and
      a record of the results of running this. `TEST` checks typically depend on
      one or more `BUILD` checks, but could directly depend on `SOURCE` checks
      if they can be executed directly from the sources without any extensive
      preparation.
    * `ANALYSIS` checks represent the combination of other check results and/or
      other data sources into some sort of summary. Examples could be something
      which makes some analysis over a source repo, or consumes a built binary
      to analyze its structure, or consumes test results to make additional
      determinations on them (e.g. "some of these tests are flaky", "the CL
      didn't cause the failures here", etc.)
  * `Stages` - These are executable actions done as part of the workflow, which
    edit the graph by recording results on Checks, and/or modify the plan by
    editing Checks and/or adding more Stages to the graph. The orchestration
    service is in charge of executing these stages. A recipe executing in
    a Buildbucket Builder is an example of a Stage.

[turboci/proto]: https://chromium.googlesource.com/infra/turboci/proto
[graph]: https://en.wikipedia.org/wiki/Graph_(abstract_data_type)

## API overview

*** note
If you already understand the API concepts, you can skip forward to
[Using TurboCI in Recipes](#Using-TurboCI-in-Recipes).
***

TurboCI has two main RPCs; WriteNodes and QueryNodes.

[`WriteNodes`] allows you to write data to a large number of Checks and/or Stages in
a single transactional write.

[`QueryNodes`] allows you to inspect the current state of the graph by querying
for Checks by various structural aspects (e.g. id, kind, types of options, types
of results, current state).

The two RPCs can also be used in conjunction to implement a read-modify-write
transaction on arbitrary subsets of the graph.


The recipe engine provides a convenient wrapper around these with
`turboci.write_nodes` and `turboci.query_nodes`, and
`turboci.run_transaction` which will manage the combination of them to implement
a read-modify-write transaction.

If you want to use the raw client interface, you may get the client via
`turboci.get_client()`.

[`WriteNodes`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/orchestrator/v1/write_nodes_request.proto#24
[`QueryNodes`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/orchestrator/v1/query_nodes_request.proto#15

### Node lifecycle

All nodes in TurboCI exhibit a lifecycle which is enforced by TurboCI itself.
The spirit of this lifecycle enforcement is to make the evolution of data in the
graph predictable by making as much of it 'append only' as possible.

There are, however, some concessions for practicality (for example, the ability
to overwrite option data during a Check's PLANNING state to allow
collaborative/parallel editing of the Check).

In the real service implementation, however, an edit log for every write is
also stored, and is queryable via QueryNodes. The intent is to allow these
practical evolutions of the workflow data while still retaining debuggability.

#### Checks

[`CheckState`] has one implied value and four explicit values:
  * Creation
  * `PLANNING`
  * `PLANNED`
  * `WAITING`
  * `FINAL`

Checks are created in the PLANNING state by default.
States progress linearly from `PLANNING` -> `PLANNED` -> `WAITING` -> `FINAL`.

[`CheckState`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/orchestrator/v1/check_state.proto#16

##### Check Creation

Checks are created in the PLANNING state. The following fields are ONLY settable
at the time the Check is created.

  * `identifier` (required) - This is an [`identifier.Check`]. The `id` portion of
    this should be carefully chosen to be meaningful to your workflow. Checks
    are uniquely identified by this field (so, there cannot be two Checks in the
    same WorkPlan with the `id` "bob"). Once chosen, a Check cannot change its
    identifier. The WorkPlan portion of this identifier will be automatically
    filled in by `WriteNodes` when the recipe is running within a TurboCI
    WorkPlan.
  * `kind` (required) - This will be a value of [`CheckKind`] and broadly
    categorizes this Check as a Source, Build, Test, or Analysis. Once chosen,
    a Check cannot change its `kind`.
  * `realm` - This is the LUCI realm that this Check will belong to. If left
    empty, will inherit the realm of the current builder. Once chosen, a Check
    cannot change its `realm` (however; a Check may later have options or
    results added which belong to different realms).

[`identifier.Check`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/ids/v1/identifier.proto#64
[`CheckKind`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/orchestrator/v1/check_kind.proto#12

##### CheckState: `PLANNING`

In the `PLANNING` state, Check options and dependencies can be freely mutated.

Options are protobuf [`Any`] messages with an optional associated `realm`. Once
an option is associated with a `realm`, that `realm` cannot be changed. Options
are *uniquely* identified within a Check by their `type_url`. So, if you write
an option with the protobuf type `a.b.Message`, attempting to write another
option of the same type will overwrite the first one.

Additionally, Checks can have dependencies on other Checks. These represent
a logic data dependency (e.g. a `BUILD` may depend on a `SOURCE` check), and the
orchestrator will unblock this check when these dependencies are satisfied. See
[Dependencies](#Dependencies) for more info.

[`Any`]: https://github.com/protocolbuffers/protobuf/blob/main/src/google/protobuf/any.proto

##### CheckState: `PLANNED`

In the `PLANNED` state, the workflow cannot explicitly modify anything about the
Check - instead TurboCI will watch the dependencies of the Check, and when they
become resolved, the Check will advance to the `WAITING` state.

##### CheckState: `WAITING`

In the `WAITING` state, stages in the workflow write results to the check.
Like options, results are a collection of [`Any`], with an optional associated
`realm`.

##### CheckState: `FINAL`

In the `FINAL` state, the Check is fully immutable.

Any other nodes with dependency edges pointing to this Check will see those
edges resolved.

#### Stages

TBD: As of 2025Q3, the fake does not emulate Stages, nor does the service
implement writing them.

### Dependencies

Dependencies in TurboCI are expressed as Edges between nodes. All Edges are
defined on the dependent node, and have a target to the dependency node. That
is, if "A" depends on "B", then the edge is defined on "A" and its target is
"B".

Dependencies have 3 parts:
  * The dependency predicate
  * Resolution events
  * Resolution

Writers to the graph are only concerned about composing the predicate, which is
a [`DependencyGroup`] which is composed of:
  * Edges
  * Nested DependencyGroups
  * An integer `threshold`.

The threshold describes how many items in a DependencyGroup need to be satisfied
for the overall DependencyGroup to be satisfied. If it's unset, it means 'all of
the items'.

This allows you to express simple boolean logic expressions in terms of edges in
the graph (e.g. `A or B` using a threshold of 1), as well as more complex
expressions in a compact form (e.g. 'two of A, B, C or D' using a threshold of
2).

Once your node is finished planning (the `PLANNED` state for Checks and Stages),
the predicate is frozen, and TurboCI begins resolving dependencies (so, when
a target becomes `FINAL`, it will appear on the dependent node as a 'resolution
event').

When enough resolution events have propagated to the dependent node to resolve
its predicate, TurboCI will record the subset of the predicate edges needed to
satisfy the Dependencies in the `satisfied` field. When this happens, the node
will be advanced to its next state (`WAITING` in the case of Checks, and
`ATTEMPTING` in the case of Stages).

[`DependencyGroup`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/orchestrator/v1/write_nodes_request.proto#45

## Using TurboCI in Recipes

*** note
It's highly recommended you first enable code completion via pyright by adding
a `pyproject.toml` to your recipe repo. This should live at the root of the
project, and the contained paths will be relative to this root.

If placed adjacent to `recipes.py` it would consist of:

```toml
[tool.pyright]
venvPath = '.recipe_deps/_venv'
venv = 'normal'
extraPaths = ['.recipe_deps/_path']
```

If you place it elsewhere in your project, you will need to adjust these paths
accordingly.

Then, either enable `pyright` as an LSP or use an IDE which has pyright (or
another LSP which accepts pyright configuration) as the python LSP (e.g.
vscode).

This will allow you to get completion and type checking for all symbols in the
turboci namespace, as well as all protobuf stubs in the `PB` import namespace.
***

There is a TurboCI client which is fully integrated with the recipe engine. To
use it, import it like:

```python
from recipe_engine import turboci
```

This contains all public symbols for interacting with turboci. During
simulation, and when the recipe is running in a context outside of a TurboCI
workflow, the recipe engine provides a high-fidelity fake which understands most
aspects of the main TurboCI API. When the recipe runs in a context within
a TurboCI workflow, these same public symbols will transparently connect to the
live service under the authority of the current build.

### Writing node data

To write node data, you'll need to use `turboci.write_nodes` with one or more
nodes (e.g. Checks). In the simplest form, this looks like:

```python
turboci.write_nodes(
  turboci.reason('creating the_build from config XXX'),
  turboci.check('the_build', kind='CHECK_KIND_BUILD'),
)
```

This would ensure that there is a BUILD Check called `the_build` in the graph
(but not much else). This could raise an error if there was already a non-BUILD
Check in the graph called `the_build`.

#### Reason? What's that?

A `reason` is always required for every `write_nodes` call and serves as
a record of *why* the change in the associated write was made. This can be as
basic as a human-readable string as in the example above, but if you need any
downstream systems to make sense of this reason in the edit log, you should
attach one or more protobuf messages to the reason:

```python
better_reason = turboci.reason(
    'creating the_build from config XXX',
    ConfigRef(origin=..., version=...),
)
```

For this reason, we call the string a ['low effort' `Reason`]. It's better than
no reason at all, but it's usually not as good as some structured data.

['low effort' `Reason`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/orchestrator/v1/write_nodes_request.proto#74

#### Writing Options

You can write option data to checks as long as the check is in the `PLANNING`
state.

```python
data = MyProtoMessage(...)
turboci.write_nodes(
  turboci.reason(...),
  turboci.check('the_build', options=[data])
)
```

If `the_build` is still in `PLANNING`, this will (over)write any option data of
type `MyProtoMessage` on the check. A Check can have any number of different
option data types as needed.

#### Writing Dependencies

You can write dependency predicates to checks as long as the check is in the
`PLANNING` state. When you write dependencies to a check, they will fully
replace any existing dependencies on that check.

```python
turboci.write_nodes(
  turboci.reason(...),
  turboci.check('the_build', deps=turboci.dep_group(
    'other_check/A',
    'other_check/B',
    threshold = 1,
  ))
)
```

The target checks must already be in the graph, OR must be created in the same
`write_nodes` call.

#### Writing Result Data

You can write results to Checks as long as the check is in the `WAITING` state.

The `write_nodes` API makes it appear that there is only one result set per
Check, but if you look at the [`Check` proto], you'll see that a single Check
may have many `Result` messages. The reason for this is that it's permitted for
multiple Stages to all contribute Results to the same check - TurboCI
automatically associates a Result with each Stage Attempt which writes result
data to the check.

The upshot of this is that from the *writer's* perspective, you don't have to
worry about this - you just need to write data and TurboCI will take care of the
Result allocation and association for you.

Writing Result data works similarly to how writing options works:

```python
result = MyResultMessage(...)
turboci.write_nodes(
  turboci.reason(...),
  turboci.check('the_build', results=[result])
)
```

The same rules apply regarding `type_url` uniqueness.

However, unlike Options, you cannot conflict with anything else when writing
result data, because every Stage Attempt (i.e. buildbucket build) has it's own
Result slot to write into.

[`Check` proto]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/orchestrator/v1/check.proto#194

#### Evolving state

Once you're done PLANNING the check, you can evolve it to the PLANNED state to
signal that no more modifications should be allowed:

```python
turboci.write_nodes(
  turboci.reason(...),
  turboci.check('the_build', state='CHECK_STATE_PLANNED')
)
```

If the Check has dependencies, TurboCI will start propagating resolution events
for them - otherwise if the Check has NO dependencies, it will immediately
transition to `CHECK_STATE_WAITING`.

Similarly, when the Check has all the results it needs, you can evolve it to
`CHECK_STATE_FINAL`, at which point it will be fully immutable.

### Querying the graph

To query the graph, you'll need to use `turboci.query_nodes` with one or more
queries.

In the simplest form, this looks like:

```python
from PB.turboci.graph.orchestrator.v1.query import Query

result = turboci.query_nodes(turboci.make_query(
    Query.Select.CheckPattern(kind='CHECK_KIND_BUILD'),
))

# NOTE: By default, this will only return nodes in the *current* workplan,
# but this API is designed to allow queries across workplans. For that
# reason `result.graph` is a map key'd by workplan ID.
#
# If you don't know what ID the current workplan is, you can get the
# workplan view by doing:
#
#   workplan = next(iter(result.graph.values()))
#
# And then this contains all our queried data:
#
#   workplan.checks["the_build"] => CheckView of the_build
```

This [`CheckView`] however, may be sparser than you want. In order to see the
more pertinent content, we'll need to understand how TurboCI services queries in
terms of query phases, and how TurboCI deals with data types.

[`CheckView`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/orchestrator/v1/check_view.proto#17

#### Query Phases

Each [`Query`] is composed of 3 phases:

  * Selection
  * Expansion
  * Collection

The `turboci.make_query` function assists in the composition of a `Query`
message.

[`Query`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/orchestrator/v1/query.proto#36

##### Query Phase: Selection

Each Query begins with the selection of one or more nodes by direct search in
the graph. There are two main ways to do this:

  * Direct supply of nodes:
    ```python
    Query.Select(nodes=[id1, id2, ...])
    ```
    Use this if you know exactly what nodes you want to start with. You can use
    the following helpers to assemble identifiers:
    * `turboci.wrap_id` - Wraps a subordinate id like an [`identifier.Check`] into
      an [`identifier.Identifier`].
    * `turboci.check_id` - Helper to generate an [`identifier.Check`] from
      a simple string.
    * `turboci.collect_check_ids` - Helper to collect strings and
      `identifier.Check` instances into a sequence of `identifier.Identifier`.

  * Check patterns:
    ```python
    Query.Select.CheckPattern(
       kind='CHECK_KIND_BUILD',
       id_regex=...,
       with_option_types=[type_url1, type_url2, ...],
       state='CHECK_STATE_WAITING',
       with_result_data_types=[type_url1, type_url2, ...],
    )
    ```
    Use this if you know something about the pattern of the Check, but don't
    know its id exactly. You can use the following helpers to assemble type
    urls:
    * `turboci.type_url_for` - Get a singular type URL from a protobuf Message
      or Message instance.
    * `turboci.type_urls` - Get a sequence of type URLs from protobuf Messages
      or Message instances. Also accepts `str` to allow pre-made type URLs to be
      mixed in with a list of protobuf Messages.

Once the selection phase is over, the Query logically has a set of selected
nodes, and the query will then perform the expansion phase (if any), followed by
the collection phase (if any).

[`identifier.Identifier`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/ids/v1/identifier.proto#22

##### Query Phase: Expansion

Expansion has to do with following edges out from the selected node(s).
Currently the only expansion opportunities are for 'dependencies' and
'dependents'.

Both of these accept a `mode` argument which can either be:
  * `QUERY_EXPAND_DEPS_MODE_EDGES` - This follows `node.dependencies.edges`,
    meaning that all *potential* dependencies will be selected.
  * `QUERY_EXPAND_DEPS_MODE_SATISFIED` - This follows
    `node.dependencies.satisfied` meaning that all *actual, resolved*
    dependencies will be selected. Note that nodes in a state prior to
    `CHECK_STATE_WAITING` or `STAGE_STATE_ATTEMPTING` have *no* satisfied edges.

Example data:

```
# A depends on B or C
A -> {B or C}

(B is satisfied, C is not)
```

To expand dependencies, use `Query.Expand.Dependencies(mode=?)`. If you supply
`A` with mode `EDGES`, this will expand to include `B` and `C`. If you supply
`A` with mode `SATISFIED`, this will expand to include `B`.

To expand dependents, use `Query.Expand.Dependents(mode=?)`. If you supply
`C` with mode `EDGES`, this will expand to include `A`. If you supply
`C` with mode `SATISFIED`, this will not include any additional nodes (because
`A`'s satisfied dependencies do not include `C`).

##### Query Phase: Collection

Finally, after selection and expansion, the Query will do collection. Collection
is where the Query can include any derivative information logically contained
by the selected nodes.

The main collection option you'll use is:

```python
Query.Collect.Check(options=true, results=true, edits=...)
```

If options and/or results are `true`, will include data from those in the result
(according to the supplied [TypeURLs in the Query](#typeurls-in-the-query)).

#### TypeURLs in the Query

By default TurboCI will not return data that your client doesn't know how to
parse. Doing so is counter productive for a couple reasons:
  1. It couples your transactions to data you can't use.
  1. It bloats the response size.
  1. It hampers auditability and can lead to surprising coupling ("I didn't
     realize that $stageA was reading this data type!").

To combat this, every Query is given a list of `type_urls` that the client
knows/wants to observe. TurboCI will only return data types (i.e. Check Options
and Check Result Data) whose type is in this list.

As a special concession for UIs and debugging, the value `*` **will** return
all data types; but this will require an extra permission to use which service
accounts will typically not have. UIs and debugging tasks DO need to see
'everything' in order to be maximally useful.

If you're using `turboci.make_query`, you can easily supply these as protobuf
Message types or instances:

```python
q = turboci.make_query(
    Query.Select.CheckPattern(kind='CHECK_KIND_ANALYSIS'),
    Query.Expand.Dependencies(),
    Query.Collect.Check(options=true),
    types=[MyOptionType, OtherOptionType],
)
```

#### Helper function `turboci.read_checks`

In order to make the relatively simple query "read me checks with these ids"
easier, there is a helper function to read checks:

```python
checks = turboci.read_checks(
    'the_build', 'other_check', check_identifier_object,
    collect=Query.Collect.Check(options=True),
    types=[MyMessageType],
)
# => [
#  CheckView('the_build'),
#  CheckView('other_check'),
#  CheckView(check_identifier_object)
# ]
```


### Running a transaction

Individual `write_nodes` and `query_nodes` are always individually atomic, but
sometimes you need to chain them together.

In order to safely do read-modify-write operations on the graph, you need to use
a transaction. A transaction in TurboCI essentially boils down to a series of
`query_nodes` operations, followed by at most one `write_nodes`.

Care should be taken to not use/cache any data queried during the transaction
until after the transaction finishes successfully.

You can run a transaction like:

```python
def _mutate(txn: turboci.Transaction):
    my_check = txn.read_checks('the_build')[0]
    my_data_url = turboci.type_url_for(MyOpportunisticData)

    if not my_check.state == CheckState.CHECK_STATE_PLANNING:
        return

    if not any(ref.type_url == my_data_url for ref in my_check.options):
        txn.write_nodes(
            turboci.reason('adding some additional opportunistic data'),
            turboci.check(
                'the_build', options=[MyOpportunisticData(...)],
            ))

turboci.run_transaction(_mutate)
```

That's about it; When the transaction runs, it will read the current state of
the check called `'the_build'`, see if it's still in the PLANNING phase, and if
it doesn't already have `MyOpportunisticData`. If both conditions are true, it
will do a write to add this data.

If another process modifies `'the_build'` during this transaction, when the
`write_nodes` call happens, it will raise a special exception which
`turboci.run_transaction` will catch and retry.

Transactions enable serialization of writes to mutable data (mostly Check
Options), but also can allow safe conditional creation of Stages (e.g. read
check X, then write stage Y (but only if X didn't change in the meantime)).

Transactions are granular to the level of individual nodes (down to specific
datums). It's allowed for multiple processes to mutate different existing option
data at the same time without conflicting, as long as those two processes don't
also read that other data.

### Simulation Testing Integration

Recipes, of course, has simulation testing via `recipes.py test`. The TurboCI
fake integrates with this in the following ways in `GenTests`:

  * Every test case gets a fresh (empty) TurboCI fake.
  * Your test can include one or more `write_nodes` calls into a given test case
    before `RunSteps` executes with `api.turboci_write_nodes(*CheckWrite)`. Note
    that `turboci.check(...)` works nicely to prepare `CheckWrite` messages here
    as well.
  * `api.assert_turboci_graph` works like `api.post_check` except that it's
    given a [`GraphView`] for the entire fake TurboCI graph state at the end of the
    test case (rather than getting a 'step dict').

Putting this all together, you might do something like:

```python
def GenTests(api):
  ...

  def _assert_graph(assert_, graph: GraphView):
    assert_('build' in graph.checks)
    build_view = graph.checks['build']

    # assert that our build check depends on the source check we wrote in
    # turboci_write_nodes below.
    assert_(any(
      edge.identifier.check.id == 'source'
      for edge in build_view.check.dependencies.edges
    ))

    assert_(turboci.get_option(MyOption, build_view) == MyOption(...))

    # etc.

  yield api.test(
    'turboci_test',
    # ... Regular test inputs, assertions, etc.
    api.turboci_write_nodes(
        # NOTE: A `reason` is not needed here. The test will synthesize one.
        turboci.check('source', kind='CHECK_KIND_SOURCE', options=[...]),
    ),
    api.assert_turboci_graph(_assert_graph)
  )
```

[`GraphView`]: https://chromium.googlesource.com/infra/turboci/proto/+/refs/heads/main/turboci/graph/orchestrator/v1/graph_view.proto#17

### Limitations of the fake

The fake that's built into the recipe engine has a number of limitations.

  * Only emulates a single workplan. This means that all checks written will
    always belong to the workplan whose ID is the (invalid) "". Don't write code
    assuming that this will be safe. Note that it is ok (and preferable) for
    written data (using `turboci.write_nodes` or the raw `WriteNodes` RPC) to
    omit the workplan ID from written nodes. When a recipe executes in a TurboCI
    context, it will implicitly gain the current workplan ID as part of this
    context, and this will be the default namespace for all read and write
    actions performed from the recipe.
  * Does not emulate reading or writing Stages. Currently, attempting to write
    a Stage will raise a `NotImplementedError`.
  * Does not track edits. Although the fake does require that a `Reason` is
    supplied on every write (to encourage early adoption code to be compatible
    with the real service API when it comes online), these reasons are not
    currently persisted.
  * Does not model differing realms or any permissions. Although the fake does
    allow populating the `realm` field, it is ignored for reads.
  * Does not model multiple processes. Recipes are single-threaded python, and
    the fake is entirely in-memory. Currently the way that futures in Recipes
    work, they will only implicitly context switch on recipe step execution and
    similar edges. The upshot of this is that transactions are always expected
    to succeed on the first attempt, and Checks will only ever have one Result.
